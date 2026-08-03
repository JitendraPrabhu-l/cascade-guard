from __future__ import annotations

import pytest

from cascade_guard.analysis.flips import analyze_flips
from cascade_guard.analysis.propagation import trace_propagation
from cascade_guard.analysis.scoring import score_trace
from cascade_guard.demo import WRONG_ANSWER
from cascade_guard.schema import Trace, TraceEvent


def test_gangup_score_without_ground_truth(gangup_trace):
    flips = analyze_flips(gangup_trace)
    report = score_trace(gangup_trace, flips)
    assert 0.0 <= report.cascade_risk <= 100.0
    assert set(report.components) == {"flip", "consensus_collapse"}
    assert report.weights["flip"] == pytest.approx(0.5 / 0.8)
    assert report.cascade_risk > 30  # a real cascade must not score as clean


def test_gangup_score_with_ground_truth(gangup_trace):
    flips = analyze_flips(gangup_trace)
    prop = trace_propagation(gangup_trace, WRONG_ANSWER)
    report = score_trace(gangup_trace, flips, prop)
    assert set(report.components) == {"flip", "consensus_collapse", "propagation"}
    assert report.components["propagation"] == 1.0
    assert sum(report.weights.values()) == pytest.approx(1.0)
    assert report.cascade_risk == pytest.approx(55.7, abs=1.0)
    assert report.grade == "C"


def test_clean_trace_scores_zero():
    trace = Trace(
        events=[
            TraceEvent(agent="a", content="The answer is red.", turn=0),
            TraceEvent(agent="b", content="The answer is red.", turn=1),
        ]
    )
    flips = analyze_flips(trace)
    report = score_trace(trace, flips)
    assert report.cascade_risk == 0.0
    assert report.grade == "A"


def test_grades_cover_the_scale():
    from cascade_guard.analysis.scoring import _grade

    assert _grade(0) == "A"
    assert _grade(25) == "B"
    assert _grade(45) == "C"
    assert _grade(65) == "D"
    assert _grade(95) == "F"


def test_propagation_without_origin_is_excluded(gangup_trace):
    flips = analyze_flips(gangup_trace)
    prop = trace_propagation(gangup_trace, "purple")  # never asserted
    report = score_trace(gangup_trace, flips, prop)
    assert "propagation" not in report.components
