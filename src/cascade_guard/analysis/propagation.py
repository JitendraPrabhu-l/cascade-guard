"""Error propagation tracing.

Given a known-wrong final answer, walk the trace backwards to find which
agent introduced it first and how many downstream agents adopted it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cascade_guard.analysis.stance import extract_stance, normalize_stance
from cascade_guard.schema import Trace, TraceEvent


@dataclass
class PropagationReport:
    wrong_stance: str
    origin: TraceEvent | None = None
    #: First event per downstream agent that repeated the wrong stance.
    adopters: list[TraceEvent] = field(default_factory=list)
    #: Agents that first asserted a *different* stance, then adopted the
    #: wrong one anyway — the overlap between propagation and sycophancy.
    capitulated_agents: list[str] = field(default_factory=list)
    total_agents: int = 0

    @property
    def origin_agent(self) -> str | None:
        return self.origin.agent if self.origin else None

    @property
    def adopter_agents(self) -> list[str]:
        return [e.agent for e in self.adopters]

    @property
    def infection_rate(self) -> float:
        """Share of non-origin agents that adopted the wrong stance."""
        downstream = self.total_agents - (1 if self.origin else 0)
        if downstream <= 0:
            return 0.0
        return len(self.adopters) / downstream

    def to_dict(self) -> dict[str, Any]:
        return {
            "wrong_stance": self.wrong_stance,
            "origin_agent": self.origin_agent,
            "origin_turn": self.origin.turn if self.origin else None,
            "origin_excerpt": self.origin.content[:280] if self.origin else None,
            "adopters": [
                {"agent": e.agent, "turn": e.turn, "excerpt": e.content[:200]}
                for e in self.adopters
            ],
            "capitulated_agents": self.capitulated_agents,
            "total_agents": self.total_agents,
            "infection_rate": round(self.infection_rate, 4),
        }


def trace_propagation(trace: Trace, wrong_answer: str) -> PropagationReport:
    wrong = normalize_stance(wrong_answer)
    report = PropagationReport(wrong_stance=wrong, total_agents=len(trace.agents))
    if not wrong:
        return report

    first_stance: dict[str, str] = {}
    seen_adopters: set[str] = set()

    for event in trace.events:
        if not event.is_assistant:
            continue
        stance = extract_stance(event)
        if stance is None:
            continue
        first_stance.setdefault(event.agent, stance)
        if stance != wrong:
            continue
        if report.origin is None:
            report.origin = event
            continue
        if event.agent == report.origin.agent or event.agent in seen_adopters:
            continue
        seen_adopters.add(event.agent)
        report.adopters.append(event)
        if first_stance[event.agent] != wrong:
            report.capitulated_agents.append(event.agent)

    return report
