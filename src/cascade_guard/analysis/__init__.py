"""Analysis passes over normalized traces."""

from __future__ import annotations

from cascade_guard.analysis.cost import CostReport, analyze_cost
from cascade_guard.analysis.flips import FlipAnalysis, FlipFinding, analyze_flips
from cascade_guard.analysis.propagation import PropagationReport, trace_propagation
from cascade_guard.analysis.scoring import ScoreReport, score_trace
from cascade_guard.analysis.stance import extract_stance, normalize_stance

__all__ = [
    "CostReport",
    "FlipAnalysis",
    "FlipFinding",
    "PropagationReport",
    "ScoreReport",
    "analyze_cost",
    "analyze_flips",
    "extract_stance",
    "normalize_stance",
    "score_trace",
    "trace_propagation",
]
