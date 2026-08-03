"""The streaming guard: feed it events, get signals back.

Usage from an agent harness::

    from cascade_guard.runtime import CascadeGuard

    guard = CascadeGuard(on_signal=my_handler)
    for step in graph.stream(inputs, stream_mode="updates"):
        for signal in guard.observe_langgraph_update(step):
            if signal.intervention.kind is InterventionKind.HALT:
                break

Design constraints that shaped this module:

- **Never blocks and never mutates.** ``observe`` returns recommendations;
  the caller decides. An exception in a user callback is captured, not
  raised, so a buggy handler cannot take down the agent run.
- **O(1) per event.** State is a handful of dicts keyed by agent; nothing
  re-scans history, so per-event cost does not grow with run length.
- **False-positive controls.** A run must reach ``min_agents`` and
  ``warmup_turns`` before actionable signals fire, each agent can only
  trigger a limited number of interventions, and repeat signals of the same
  kind for the same agent are suppressed.
"""

from __future__ import annotations

import contextlib
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from cascade_guard.analysis.cost import SPIKE_FACTOR, SPIKE_MIN_TOKENS
from cascade_guard.analysis.stance import agreement_cues, evidence_cues, extract_stance
from cascade_guard.runtime.interventions import (
    DEFAULT_PROMPTS,
    Intervention,
    InterventionKind,
    Signal,
    SignalKind,
)
from cascade_guard.schema import TraceEvent

#: Risk contributed by one unsupported flip, before the consensus multiplier.
_RISK_PER_UNSUPPORTED_FLIP = 28.0
#: Extra risk when a false consensus closes (every agent holds one stance).
_RISK_CONSENSUS_LOCK = 22.0
#: Risk contributed by a flip that did cite new evidence.
_RISK_PER_SUPPORTED_FLIP = 4.0

SignalHandler = Callable[[Signal], None]


@dataclass
class GuardState:
    """Everything the guard remembers about the run so far."""

    #: Latest stance per agent.
    stances: dict[str, str] = field(default_factory=dict)
    #: How many consecutive turns each agent has held its current stance.
    turns_held: dict[str, int] = field(default_factory=dict)
    #: Turn number of the last tool result (new evidence entering the run).
    last_tool_turn: int | None = None
    events_seen: int = 0
    unsupported_flips: int = 0
    supported_flips: int = 0
    risk: float = 0.0
    #: Interventions already recommended per agent (rate limiting).
    interventions_by_agent: Counter[str] = field(default_factory=Counter)
    #: (agent, signal kind) pairs already emitted (dedup).
    emitted: set[tuple[str, str]] = field(default_factory=set)
    consensus_locked: bool = False
    #: Running mean of output tokens, for spike detection without history.
    _token_total: int = 0
    _token_events: int = 0

    @property
    def mean_tokens_out(self) -> float:
        return self._token_total / self._token_events if self._token_events else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "events_seen": self.events_seen,
            "risk": round(self.risk, 1),
            "unsupported_flips": self.unsupported_flips,
            "supported_flips": self.supported_flips,
            "consensus_locked": self.consensus_locked,
            "stances": dict(self.stances),
        }


class CascadeGuard:
    """Incremental cascade detector for a single live run."""

    def __init__(
        self,
        *,
        on_signal: SignalHandler | None = None,
        risk_threshold: float = 60.0,
        halt_threshold: float | None = None,
        min_agents: int = 3,
        warmup_turns: int = 2,
        max_interventions_per_agent: int = 2,
        prompts: dict[InterventionKind, str] | None = None,
        observe_only: bool = False,
    ) -> None:
        """
        Args:
            on_signal: Called for every emitted signal. Exceptions raised by
                the handler are swallowed so a broken handler cannot break
                the agent run.
            risk_threshold: Cumulative risk (0-100) at which a
                ``RISK_THRESHOLD`` signal fires.
            halt_threshold: Risk at which the guard recommends ``HALT``.
                ``None`` (default) means never recommend halting.
            min_agents: Suppress actionable signals until this many distinct
                agents have spoken — two agents cannot form a majority worth
                conforming to.
            warmup_turns: Suppress actionable signals for this many opening
                turns, so early position-finding is not read as capitulation.
            max_interventions_per_agent: Rate limit; further findings for
                that agent downgrade to ``WARN``.
            prompts: Override the default intervention prompt text.
            observe_only: Downgrade every intervention to ``WARN``. Use when
                first enabling the guard in production.
        """
        self.state = GuardState()
        self._on_signal = on_signal
        self.risk_threshold = risk_threshold
        self.halt_threshold = halt_threshold
        self.min_agents = min_agents
        self.warmup_turns = warmup_turns
        self.max_interventions_per_agent = max_interventions_per_agent
        self.prompts = {**DEFAULT_PROMPTS, **(prompts or {})}
        self.observe_only = observe_only
        self.signals: list[Signal] = []
        #: Wall-clock nanoseconds spent inside observe(), for latency budgets.
        self.observe_time_ns = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, event: TraceEvent) -> list[Signal]:
        """Feed one event to the guard; return any signals it produced."""
        started = time.perf_counter_ns()
        try:
            return self._observe(event)
        finally:
            self.observe_time_ns += time.perf_counter_ns() - started

    def observe_many(self, events: Iterable[TraceEvent]) -> Iterator[Signal]:
        """Feed a sequence of events, yielding signals as they are produced."""
        for event in events:
            yield from self.observe(event)

    def observe_langgraph_update(self, update: dict[str, Any]) -> list[Signal]:
        """Feed one ``stream_mode="updates"`` payload straight from LangGraph.

        Converts the update to normalized events with the same adapter logic
        the batch profiler uses, so live and post-hoc results agree.
        """
        from cascade_guard.ingest.langgraph import events_from_update

        signals: list[Signal] = []
        for event in events_from_update(update, start_turn=self.state.events_seen):
            signals.extend(self.observe(event))
        return signals

    @property
    def risk(self) -> float:
        return self.state.risk

    @property
    def should_halt(self) -> bool:
        """True once any emitted signal recommended halting the run."""
        return any(s.intervention.kind is InterventionKind.HALT for s in self.signals)

    def snapshot(self) -> dict[str, Any]:
        """Current guard state plus latency accounting, for logging."""
        data = self.state.to_dict()
        data["signals"] = [s.to_dict() for s in self.signals]
        data["observe_time_ms"] = round(self.observe_time_ns / 1e6, 3)
        if self.state.events_seen:
            data["mean_observe_us"] = round(self.observe_time_ns / self.state.events_seen / 1e3, 1)
        return data

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _observe(self, event: TraceEvent) -> list[Signal]:
        state = self.state
        state.events_seen += 1

        if event.is_tool:
            state.last_tool_turn = event.turn
            return []
        if not event.is_assistant:
            return []

        signals: list[Signal] = []
        if event.tokens_out > 0:
            signals.extend(self._check_token_spike(event))
            state._token_total += event.tokens_out
            state._token_events += 1

        stance = extract_stance(event)
        agree = agreement_cues(event.content)
        prior = state.stances.get(event.agent)
        majority = self._majority(event.agent)

        if prior is not None and majority is not None and majority[0] != prior:
            maj_stance, maj_size = majority
            effective = stance
            if effective is None and agree:
                effective = maj_stance

            if effective == maj_stance:
                signals.extend(self._handle_flip(event, prior, maj_stance, maj_size, agree))
                stance = effective

        if stance is not None:
            if state.stances.get(event.agent) == stance:
                state.turns_held[event.agent] = state.turns_held.get(event.agent, 0) + 1
            else:
                state.turns_held[event.agent] = 1
            state.stances[event.agent] = stance
            signals.extend(self._check_consensus(event))

        signals.extend(self._check_risk_threshold(event))
        for signal in signals:
            self._emit(signal)
        return signals

    def _majority(self, exclude_agent: str) -> tuple[str, int] | None:
        peers = [s for agent, s in self.state.stances.items() if agent != exclude_agent]
        if not peers:
            return None
        ranked = Counter(peers).most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None  # tied: no clear majority to conform to
        return ranked[0][0], ranked[0][1]

    def _handle_flip(
        self,
        event: TraceEvent,
        prior: str,
        maj_stance: str,
        maj_size: int,
        agree: tuple[str, ...],
    ) -> list[Signal]:
        state = self.state
        evid = evidence_cues(event.content)
        tool_evidence = state.last_tool_turn is not None and state.last_tool_turn >= event.turn - 1
        evidence_based = bool(evid) or bool(event.evidence) or tool_evidence
        held = state.turns_held.get(event.agent, 1)

        if evidence_based:
            state.supported_flips += 1
            state.risk = min(100.0, state.risk + _RISK_PER_SUPPORTED_FLIP)
            return [
                Signal(
                    kind=SignalKind.SUPPORTED_FLIP,
                    severity="info",
                    message=(
                        f"{event.agent} changed position from '{prior}' to "
                        f"'{maj_stance}' citing new evidence"
                    ),
                    event=event,
                    risk=state.risk,
                    intervention=Intervention(InterventionKind.NONE),
                    details={
                        "from_stance": prior,
                        "to_stance": maj_stance,
                        "evidence_cues": list(evid),
                    },
                )
            ]

        state.unsupported_flips += 1
        # Folding immediately is worse than folding after resisting.
        speed = 1.0 / (1.0 + max(0, held - 1))
        state.risk = min(100.0, state.risk + _RISK_PER_UNSUPPORTED_FLIP * (0.6 + 0.4 * speed))
        severity = "high" if agree else "medium"
        intervention = self._decide(
            event.agent,
            InterventionKind.REQUIRE_EVIDENCE,
            target_agent=event.agent,
            turn=event.turn,
        )
        return [
            Signal(
                kind=SignalKind.UNSUPPORTED_FLIP,
                severity=severity,
                message=(
                    f"{event.agent} adopted the majority position '{maj_stance}' "
                    f"(held by {maj_size} peer(s)) without new evidence, after "
                    f"holding '{prior}' for {held} turn(s)"
                ),
                event=event,
                risk=state.risk,
                intervention=intervention,
                details={
                    "from_stance": prior,
                    "to_stance": maj_stance,
                    "majority_size": maj_size,
                    "turns_held": held,
                    "agreement_cues": list(agree),
                },
            )
        ]

    def _check_consensus(self, event: TraceEvent) -> list[Signal]:
        state = self.state
        if state.consensus_locked or state.unsupported_flips == 0:
            return []
        if len(state.stances) < self.min_agents:
            return []
        if len(set(state.stances.values())) != 1:
            return []

        state.consensus_locked = True
        state.risk = min(100.0, state.risk + _RISK_CONSENSUS_LOCK)
        stance = next(iter(state.stances.values()))
        intervention = self._decide(event.agent, InterventionKind.INJECT_DISSENT, turn=event.turn)
        return [
            Signal(
                kind=SignalKind.CONSENSUS_LOCKED,
                severity="high",
                message=(
                    f"all {len(state.stances)} agents now hold '{stance}' after "
                    f"{state.unsupported_flips} unsupported flip(s) — this "
                    "consensus may be false"
                ),
                event=event,
                risk=state.risk,
                intervention=intervention,
                details={"stance": stance, "agents": sorted(state.stances)},
            )
        ]

    def _check_risk_threshold(self, event: TraceEvent) -> list[Signal]:
        """Fire once when risk crosses the warn threshold, and again for halt.

        The two thresholds are tracked independently so a caller who sets
        only ``halt_threshold`` still gets a halt recommendation, even when
        it sits below the default ``risk_threshold``.
        """
        state = self.state
        signals: list[Signal] = []
        halting = self.halt_threshold is not None and state.risk >= self.halt_threshold
        crossed_warn = state.risk >= self.risk_threshold

        if halting and ("*", "halt") not in state.emitted:
            state.emitted.add(("*", "halt"))
            # A halt supersedes the warn signal; don't emit both for one event.
            state.emitted.add(("*", SignalKind.RISK_THRESHOLD.value))
            assert self.halt_threshold is not None
            signals.append(self._risk_signal(event, self.halt_threshold, InterventionKind.HALT))
        elif crossed_warn and ("*", SignalKind.RISK_THRESHOLD.value) not in state.emitted:
            state.emitted.add(("*", SignalKind.RISK_THRESHOLD.value))
            signals.append(self._risk_signal(event, self.risk_threshold, InterventionKind.WARN))
        return signals

    def _risk_signal(self, event: TraceEvent, threshold: float, kind: InterventionKind) -> Signal:
        intervention = self._decide(event.agent, kind, turn=event.turn, rate_limit=False)
        return Signal(
            kind=SignalKind.RISK_THRESHOLD,
            severity="high",
            message=(
                f"cascade risk {self.state.risk:.0f} crossed the "
                f"{'halt' if kind is InterventionKind.HALT else 'configured'} "
                f"threshold of {threshold:.0f}"
            ),
            event=event,
            risk=self.state.risk,
            intervention=intervention,
            details={"threshold": threshold, "halt": kind is InterventionKind.HALT},
        )

    def _check_token_spike(self, event: TraceEvent) -> list[Signal]:
        state = self.state
        # Need a baseline before a value can be "unusual".
        if state._token_events < 3:
            return []
        threshold = max(SPIKE_MIN_TOKENS, SPIKE_FACTOR * state.mean_tokens_out)
        if event.tokens_out <= threshold:
            return []
        key = (event.agent, SignalKind.TOKEN_SPIKE.value)
        if key in state.emitted:
            return []
        state.emitted.add(key)
        return [
            Signal(
                kind=SignalKind.TOKEN_SPIKE,
                severity="low",
                message=(
                    f"{event.agent} produced {event.tokens_out:,} output tokens, "
                    f"over {SPIKE_FACTOR:g}x the running mean of "
                    f"{state.mean_tokens_out:.0f}"
                ),
                event=event,
                risk=state.risk,
                intervention=Intervention(InterventionKind.WARN),
                details={
                    "tokens_out": event.tokens_out,
                    "mean_tokens_out": round(state.mean_tokens_out, 1),
                },
            )
        ]

    def _decide(
        self,
        agent: str,
        kind: InterventionKind,
        *,
        turn: int,
        target_agent: str | None = None,
        rate_limit: bool = True,
    ) -> Intervention:
        """Apply warmup, quorum, rate limits, and observe-only downgrades."""
        state = self.state
        if self.observe_only:
            return Intervention(InterventionKind.WARN, target_agent=target_agent)
        if turn < self.warmup_turns or len(state.stances) < self.min_agents:
            return Intervention(InterventionKind.WARN, target_agent=target_agent)
        if rate_limit:
            if state.interventions_by_agent[agent] >= self.max_interventions_per_agent:
                return Intervention(InterventionKind.WARN, target_agent=target_agent)
            state.interventions_by_agent[agent] += 1
        return Intervention(kind, prompt=self.prompts.get(kind), target_agent=target_agent)

    def _emit(self, signal: Signal) -> None:
        self.signals.append(signal)
        if self._on_signal is None:
            return
        # A broken handler must never take down the agent run it is watching.
        with contextlib.suppress(Exception):
            self._on_signal(signal)
