"""Token/cost analysis: totals per agent and per-turn output-token spikes."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from cascade_guard.schema import Trace

#: An event must exceed both the relative and absolute thresholds to be a spike.
SPIKE_FACTOR = 2.0
SPIKE_MIN_TOKENS = 100


@dataclass(frozen=True)
class TurnCost:
    turn: int
    agent: str
    tokens_in: int
    tokens_out: int
    is_spike: bool


@dataclass
class CostReport:
    per_event: list[TurnCost] = field(default_factory=list)
    per_agent_out: dict[str, int] = field(default_factory=dict)
    total_in: int = 0
    total_out: int = 0
    median_out: float = 0.0

    @property
    def spikes(self) -> list[TurnCost]:
        return [t for t in self.per_event if t.is_spike]

    @property
    def has_token_data(self) -> bool:
        return self.total_in > 0 or self.total_out > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens_in": self.total_in,
            "total_tokens_out": self.total_out,
            "median_tokens_out": self.median_out,
            "per_agent_tokens_out": self.per_agent_out,
            "spikes": [
                {"turn": t.turn, "agent": t.agent, "tokens_out": t.tokens_out} for t in self.spikes
            ],
            "per_event": [
                {
                    "turn": t.turn,
                    "agent": t.agent,
                    "tokens_in": t.tokens_in,
                    "tokens_out": t.tokens_out,
                    "is_spike": t.is_spike,
                }
                for t in self.per_event
            ],
        }


def analyze_cost(trace: Trace) -> CostReport:
    report = CostReport()
    nonzero = [e.tokens_out for e in trace.events if e.tokens_out > 0]
    report.median_out = float(statistics.median(nonzero)) if nonzero else 0.0
    threshold = max(SPIKE_MIN_TOKENS, SPIKE_FACTOR * report.median_out)

    for event in trace.events:
        is_spike = bool(nonzero) and event.tokens_out > threshold
        report.per_event.append(
            TurnCost(
                turn=event.turn,
                agent=event.agent,
                tokens_in=event.tokens_in,
                tokens_out=event.tokens_out,
                is_spike=is_spike,
            )
        )
        report.total_in += event.tokens_in
        report.total_out += event.tokens_out
        if event.is_assistant:
            report.per_agent_out[event.agent] = (
                report.per_agent_out.get(event.agent, 0) + event.tokens_out
            )
    return report
