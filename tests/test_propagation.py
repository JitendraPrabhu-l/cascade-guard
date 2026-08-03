from __future__ import annotations

from cascade_guard.analysis.propagation import trace_propagation
from cascade_guard.demo import WRONG_ANSWER


def test_gangup_propagation(gangup_trace):
    report = trace_propagation(gangup_trace, WRONG_ANSWER)

    assert report.origin is not None
    assert report.origin_agent == "bob"
    assert report.origin.turn == 1
    assert report.adopter_agents == ["carol", "alice"]
    assert report.capitulated_agents == ["alice"]  # first said green, then blue
    assert report.infection_rate == 1.0


def test_wrong_answer_never_asserted(gangup_trace):
    report = trace_propagation(gangup_trace, "purple")
    assert report.origin is None
    assert report.adopters == []
    assert report.infection_rate == 0.0


def test_to_dict_is_json_safe(gangup_trace):
    import json

    report = trace_propagation(gangup_trace, WRONG_ANSWER)
    json.dumps(report.to_dict())
