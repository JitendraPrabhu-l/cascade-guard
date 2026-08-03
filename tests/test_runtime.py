from __future__ import annotations

import pytest

from cascade_guard.runtime import CascadeGuard, InterventionKind, SignalKind
from cascade_guard.schema import TraceEvent


def ev(agent: str, content: str, turn: int, **kwargs) -> TraceEvent:
    return TraceEvent(agent=agent, content=content, turn=turn, **kwargs)


def _gangup_events() -> list[TraceEvent]:
    return [
        ev("alice", "My answer is green.", 0),
        ev("bob", "The answer is blue.", 1),
        ev("carol", "The answer is blue.", 2),
        ev("alice", "I still think the answer is green.", 3),
        ev("alice", "You're right, I'll go along. The answer is blue.", 4),
    ]


def test_guard_detects_the_cascade_live():
    guard = CascadeGuard()
    signals = list(guard.observe_many(_gangup_events()))
    kinds = [s.kind for s in signals]

    assert SignalKind.UNSUPPORTED_FLIP in kinds
    assert SignalKind.CONSENSUS_LOCKED in kinds
    flip = next(s for s in signals if s.kind is SignalKind.UNSUPPORTED_FLIP)
    assert flip.event.agent == "alice"
    assert flip.event.turn == 4
    assert flip.details["from_stance"] == "green"
    assert flip.details["to_stance"] == "blue"
    assert flip.intervention.kind is InterventionKind.REQUIRE_EVIDENCE
    assert flip.intervention.prompt  # a ready-to-inject prompt is supplied
    assert guard.risk > 0


def test_guard_agrees_with_the_batch_profiler(gangup_trace):
    """A run the guard flags is a run the profiler flags, and vice versa."""
    from cascade_guard.analyze import analyze_trace

    batch = analyze_trace(gangup_trace)
    guard = CascadeGuard()
    signals = list(guard.observe_many(gangup_trace.events))

    live_flips = [s for s in signals if s.kind is SignalKind.UNSUPPORTED_FLIP]
    assert len(live_flips) == len(batch.flips.unsupported_flips) == 1
    assert live_flips[0].event.turn == batch.flips.unsupported_flips[0].event.turn
    assert live_flips[0].event.agent == batch.flips.unsupported_flips[0].agent


def test_evidence_based_flip_is_informational_only():
    guard = CascadeGuard()
    events = [
        ev("a", "The answer is red.", 0),
        ev("b", "The answer is blue.", 1),
        ev("c", "The answer is blue.", 2),
        ev("a", "I checked the docs: the answer is blue.", 3),
    ]
    signals = list(guard.observe_many(events))
    flips = [s for s in signals if s.kind is SignalKind.SUPPORTED_FLIP]
    assert len(flips) == 1
    assert flips[0].intervention.kind is InterventionKind.NONE
    assert not flips[0].actionable
    assert guard.state.unsupported_flips == 0


def test_tool_result_counts_as_evidence():
    guard = CascadeGuard()
    events = [
        ev("a", "The answer is red.", 0),
        ev("b", "The answer is blue.", 1),
        ev("c", "The answer is blue.", 2),
        ev("search", "result: blue", 3, role="tool"),
        ev("a", "Fine, the answer is blue.", 4),
    ]
    signals = list(guard.observe_many(events))
    assert any(s.kind is SignalKind.SUPPORTED_FLIP for s in signals)
    assert guard.state.unsupported_flips == 0


def test_observe_only_downgrades_every_intervention():
    guard = CascadeGuard(observe_only=True)
    signals = list(guard.observe_many(_gangup_events()))
    assert signals  # detections still happen
    assert all(not s.actionable for s in signals)
    assert all(
        s.intervention.kind in (InterventionKind.NONE, InterventionKind.WARN) for s in signals
    )


def test_warmup_and_quorum_suppress_early_interventions():
    # Only two agents: no majority worth conforming to.
    guard = CascadeGuard(min_agents=3)
    events = [
        ev("a", "The answer is red.", 0),
        ev("b", "The answer is blue.", 1),
        ev("a", "OK, the answer is blue.", 2),
    ]
    signals = list(guard.observe_many(events))
    assert all(not s.actionable for s in signals)


def test_halt_threshold_recommends_halting():
    guard = CascadeGuard(risk_threshold=20.0, halt_threshold=20.0)
    list(guard.observe_many(_gangup_events()))
    assert guard.should_halt
    halts = [s for s in guard.signals if s.intervention.kind is InterventionKind.HALT]
    assert len(halts) == 1
    assert halts[0].kind is SignalKind.RISK_THRESHOLD


def test_no_halt_by_default():
    guard = CascadeGuard()
    list(guard.observe_many(_gangup_events()))
    assert not guard.should_halt


def test_halt_threshold_below_risk_threshold_still_fires():
    """A halt threshold under the (default) warn threshold must not be ignored."""
    guard = CascadeGuard(halt_threshold=10.0)  # risk_threshold stays at 60
    list(guard.observe_many(_gangup_events()))
    assert guard.risk >= 10.0
    assert guard.should_halt


def test_halt_signal_is_emitted_once():
    guard = CascadeGuard(halt_threshold=10.0)
    events = [*_gangup_events()]
    events += [
        ev("bob", "Confirming: the answer is blue.", 5),
        ev("carol", "Agreed, the answer is blue.", 6),
    ]
    list(guard.observe_many(events))
    halts = [s for s in guard.signals if s.intervention.kind is InterventionKind.HALT]
    assert len(halts) == 1


def test_rate_limit_downgrades_repeat_interventions():
    guard = CascadeGuard(max_interventions_per_agent=1)
    events = [
        ev("a", "The answer is red.", 0),
        ev("b", "The answer is blue.", 1),
        ev("c", "The answer is blue.", 2),
        ev("a", "OK, the answer is blue.", 3),  # flip 1 -> actionable
        ev("a", "Actually the answer is red.", 4),
        ev("b", "The answer is blue.", 5),
        ev("c", "The answer is blue.", 6),
        ev("a", "Fine, the answer is blue.", 7),  # flip 2 -> rate-limited
    ]
    signals = list(guard.observe_many(events))
    flips = [s for s in signals if s.kind is SignalKind.UNSUPPORTED_FLIP]
    assert len(flips) == 2
    assert flips[0].intervention.kind is InterventionKind.REQUIRE_EVIDENCE
    assert flips[1].intervention.kind is InterventionKind.WARN


def test_tied_majority_is_not_conformity_pressure():
    guard = CascadeGuard()
    events = [
        ev("a", "The answer is red.", 0),
        ev("b", "The answer is blue.", 1),
        ev("c", "The answer is green.", 2),
        ev("a", "Now the answer is blue.", 3),
    ]
    signals = list(guard.observe_many(events))
    assert not any(s.kind is SignalKind.UNSUPPORTED_FLIP for s in signals)


def test_callback_receives_signals_and_survives_exceptions():
    received = []

    def handler(signal):
        received.append(signal)
        raise RuntimeError("handler is broken")

    guard = CascadeGuard(on_signal=handler)
    signals = list(guard.observe_many(_gangup_events()))
    # A broken handler must not break the run, and must still see every signal.
    assert len(received) == len(signals) > 0


def test_langgraph_update_can_be_observed_directly():
    guard = CascadeGuard()
    updates = [
        {"a": {"messages": [{"type": "ai", "name": "a", "content": "The answer is red."}]}},
        {"b": {"messages": [{"type": "ai", "name": "b", "content": "The answer is blue."}]}},
        {"c": {"messages": [{"type": "ai", "name": "c", "content": "The answer is blue."}]}},
        {
            "a": {
                "messages": [
                    {
                        "type": "ai",
                        "name": "a",
                        "content": "You're right, I agree. The answer is blue.",
                    }
                ]
            }
        },
    ]
    signals = [s for u in updates for s in guard.observe_langgraph_update(u)]
    assert any(s.kind is SignalKind.UNSUPPORTED_FLIP for s in signals)


def test_token_spike_needs_a_baseline_first():
    guard = CascadeGuard()
    events = [
        ev("a", "one", 0, tokens_out=100),
        ev("b", "two", 1, tokens_out=100),
        ev("c", "three", 2, tokens_out=100),
        ev("a", "four", 3, tokens_out=900),
    ]
    signals = list(guard.observe_many(events))
    spikes = [s for s in signals if s.kind is SignalKind.TOKEN_SPIKE]
    assert len(spikes) == 1
    assert spikes[0].event.turn == 3


def test_snapshot_is_json_safe_and_reports_latency():
    import json

    guard = CascadeGuard()
    list(guard.observe_many(_gangup_events()))
    snapshot = guard.snapshot()
    json.dumps(snapshot)
    assert snapshot["events_seen"] == 5
    assert "mean_observe_us" in snapshot


def test_observe_cost_stays_flat_as_the_run_grows():
    """Per-event cost must not scale with history length."""
    guard = CascadeGuard()
    events = [ev(f"agent{i % 4}", f"The answer is opt{i % 3}.", i) for i in range(400)]
    list(guard.observe_many(events))
    mean_us = guard.observe_time_ns / len(events) / 1e3
    # Generous bound: this catches accidental O(n^2) rescans, not micro-regressions.
    assert mean_us < 500, f"observe() averaged {mean_us:.0f}us/event"


@pytest.mark.parametrize("kind", list(SignalKind))
def test_signal_kinds_are_stable_strings(kind):
    # Signal kinds are part of the policy/suppression contract.
    assert kind.value == kind.value.lower()
    assert " " not in kind.value
