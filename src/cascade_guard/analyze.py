"""Top-level analysis orchestration: trace in, full report out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from cascade_guard.analysis.cost import CostReport, analyze_cost
from cascade_guard.analysis.flips import FlipAnalysis, analyze_flips
from cascade_guard.analysis.propagation import PropagationReport, trace_propagation
from cascade_guard.analysis.scoring import ScoreReport, score_trace
from cascade_guard.schema import SCHEMA_VERSION, Trace

if TYPE_CHECKING:
    from cascade_guard.judge.base import FlipJudge


@dataclass
class AnalysisReport:
    trace: Trace
    flips: FlipAnalysis
    cost: CostReport
    score: ScoreReport
    propagation: PropagationReport | None = None
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    tool_version: str = ""

    @property
    def n_events(self) -> int:
        return len(self.trace.events)

    @property
    def n_agents(self) -> int:
        return len(self.trace.agents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "cascade-guard",
            "tool_version": self.tool_version,
            "generated_at": self.generated_at,
            "source": self.trace.source,
            "run_id": self.trace.run_id,
            "n_events": self.n_events,
            "agents": self.trace.agents,
            "score": self.score.to_dict(),
            "flips": {
                "opportunities": self.flips.opportunities,
                "resists": len(self.flips.resists),
                "total_flips": len(self.flips.flips),
                "unsupported_flips": len(self.flips.unsupported_flips),
                "findings": [f.to_dict() for f in self.flips.flips],
            },
            "propagation": self.propagation.to_dict() if self.propagation else None,
            "cost": self.cost.to_dict(),
        }


def analyze_trace(trace: Trace, wrong_answer: str | None = None) -> AnalysisReport:
    """Run every analysis pass over a normalized trace."""
    from cascade_guard import __version__

    flips = analyze_flips(trace)
    propagation = trace_propagation(trace, wrong_answer) if wrong_answer else None
    cost = analyze_cost(trace)
    score = score_trace(trace, flips, propagation)
    return AnalysisReport(
        trace=trace,
        flips=flips,
        cost=cost,
        score=score,
        propagation=propagation,
        tool_version=__version__,
    )


def apply_judge(report: AnalysisReport, judge: FlipJudge) -> None:
    """Annotate each flip finding with an LLM judge verdict (in place).

    Verdicts are attached as metadata; the heuristic score is deliberately
    left unchanged so results stay reproducible without API access.
    """
    for finding in report.flips.flips:
        verdict = judge.verify(finding, report.trace)
        finding.judge = verdict.to_dict()
