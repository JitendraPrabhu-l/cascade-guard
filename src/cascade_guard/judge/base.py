"""Judge protocol: pluggable second opinions on flip findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from cascade_guard.analysis.flips import FlipFinding
from cascade_guard.schema import Trace


@dataclass(frozen=True)
class JudgeVerdict:
    #: True = sycophantic flip, False = justified update, None = undecided.
    is_sycophantic: bool | None
    confidence: float
    rationale: str
    model: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_sycophantic": self.is_sycophantic,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "model": self.model,
        }


@runtime_checkable
class FlipJudge(Protocol):
    def verify(self, finding: FlipFinding, trace: Trace) -> JudgeVerdict: ...


def build_transcript(finding: FlipFinding, trace: Trace, window: int = 8) -> str:
    """Render the events leading up to (and including) the flip as text."""
    flip_turn = finding.event.turn
    events = [e for e in trace.events if e.turn <= flip_turn]
    events = events[-window:]
    lines = []
    for e in events:
        marker = "  <-- FLIP UNDER REVIEW" if e.turn == flip_turn else ""
        lines.append(f"[turn {e.turn}] {e.agent} ({e.role}): {e.content}{marker}")
    return "\n".join(lines)
