"""Normalized trace schema shared by every adapter and analyzer.

Adapters translate framework-specific logs (LangGraph, generic JSONL, ...)
into a flat, ordered sequence of :class:`TraceEvent` records. Everything
downstream (flip detection, propagation tracing, cost analysis, scoring,
reports) consumes only this schema, so adding a new framework never touches
the analysis code.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"

#: Roles treated as agent output (participate in stance/flip analysis).
ASSISTANT_ROLES = frozenset({"assistant", "agent", "ai"})
#: Roles treated as tool/function output (count as evidence entering the run).
TOOL_ROLES = frozenset({"tool", "function"})


@dataclass(frozen=True)
class TraceEvent:
    """One utterance/step in a multi-agent run, in normalized form."""

    agent: str
    content: str
    turn: int
    run_id: str = "run-0"
    event_id: str = ""
    role: str = "assistant"
    timestamp: str | float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    #: Explicit stance label if the source framework already provides one.
    stance: str | None = None
    #: Explicit evidence references (URLs, doc ids, tool call ids) if provided.
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent:
            raise ValueError("TraceEvent.agent must be a non-empty string")
        if self.turn < 0:
            raise ValueError(f"TraceEvent.turn must be >= 0, got {self.turn}")
        if self.tokens_in < 0 or self.tokens_out < 0:
            raise ValueError("token counts must be >= 0")

    @property
    def is_assistant(self) -> bool:
        return self.role.lower() in ASSISTANT_ROLES

    @property
    def is_tool(self) -> bool:
        return self.role.lower() in TOOL_ROLES

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = list(self.evidence)
        return d


@dataclass
class Trace:
    """An ordered collection of events from one multi-agent run."""

    events: list[TraceEvent]
    run_id: str = "run-0"
    source: str = ""

    def __post_init__(self) -> None:
        self.events = sorted(self.events, key=lambda e: e.turn)

    @property
    def agents(self) -> list[str]:
        """Assistant agents in order of first appearance."""
        seen: list[str] = []
        for ev in self.events:
            if ev.is_assistant and ev.agent not in seen:
                seen.append(ev.agent)
        return seen

    @property
    def assistant_events(self) -> list[TraceEvent]:
        return [e for e in self.events if e.is_assistant]

    def events_for(self, agent: str) -> list[TraceEvent]:
        return [e for e in self.events if e.agent == agent]

    @property
    def total_tokens_in(self) -> int:
        return sum(e.tokens_in for e in self.events)

    @property
    def total_tokens_out(self) -> int:
        return sum(e.tokens_out for e in self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "source": self.source,
            "events": [e.to_dict() for e in self.events],
        }
