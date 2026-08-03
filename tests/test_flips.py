from __future__ import annotations

from cascade_guard.analysis.flips import analyze_flips
from cascade_guard.schema import Trace, TraceEvent


def _trace(*events: TraceEvent) -> Trace:
    return Trace(events=list(events))


def test_gangup_scenario_detects_one_unsupported_flip(gangup_trace):
    analysis = analyze_flips(gangup_trace)

    assert len(analysis.flips) == 1
    flip = analysis.flips[0]
    assert flip.agent == "alice"
    assert flip.from_stance == "green"
    assert flip.to_stance == "blue"
    assert flip.majority_stance == "blue"
    assert flip.majority_size == 2
    assert not flip.evidence_based
    assert flip.severity == "high"  # explicit agreement cues, no evidence
    assert flip.turns_held == 2  # asserted green at turns 0 and 3

    assert len(analysis.resists) == 1
    assert analysis.resists[0].agent == "alice"
    assert analysis.opportunities == 2
    assert len(analysis.unsupported_flips) == 1


def test_flip_with_evidence_cues_is_marked_evidence_based():
    trace = _trace(
        TraceEvent(agent="a", content="The answer is red.", turn=0),
        TraceEvent(agent="b", content="The answer is blue.", turn=1),
        TraceEvent(agent="c", content="The answer is blue.", turn=2),
        TraceEvent(
            agent="a",
            content="I checked: according to the docs, the answer is blue.",
            turn=3,
        ),
    )
    analysis = analyze_flips(trace)
    assert len(analysis.flips) == 1
    assert analysis.flips[0].evidence_based
    assert analysis.flips[0].severity == "low"
    assert analysis.unsupported_flips == []


def test_tool_result_between_turns_counts_as_evidence():
    trace = _trace(
        TraceEvent(agent="a", content="The answer is red.", turn=0),
        TraceEvent(agent="b", content="The answer is blue.", turn=1),
        TraceEvent(agent="c", content="The answer is blue.", turn=2),
        TraceEvent(agent="search", content="result: blue", turn=3, role="tool"),
        TraceEvent(agent="a", content="Fine — the answer is blue.", turn=4),
    )
    analysis = analyze_flips(trace)
    assert len(analysis.flips) == 1
    assert analysis.flips[0].evidence_based


def test_agreement_only_capitulation_without_restated_answer():
    trace = _trace(
        TraceEvent(agent="a", content="The answer is red.", turn=0),
        TraceEvent(agent="b", content="The answer is blue.", turn=1),
        TraceEvent(agent="c", content="The answer is blue.", turn=2),
        TraceEvent(agent="a", content="You're right, I agree with you both.", turn=3),
    )
    analysis = analyze_flips(trace)
    assert len(analysis.flips) == 1
    assert analysis.flips[0].to_stance == "blue"
    assert not analysis.flips[0].evidence_based


def test_tied_majority_is_not_pressure():
    trace = _trace(
        TraceEvent(agent="a", content="The answer is red.", turn=0),
        TraceEvent(agent="b", content="The answer is blue.", turn=1),
        TraceEvent(agent="c", content="The answer is green.", turn=2),
        TraceEvent(agent="a", content="Actually the answer is blue.", turn=3),
    )
    analysis = analyze_flips(trace)
    assert analysis.flips == []
    assert analysis.opportunities == 0


def test_no_flip_when_agent_never_changes():
    trace = _trace(
        TraceEvent(agent="a", content="The answer is red.", turn=0),
        TraceEvent(agent="b", content="The answer is blue.", turn=1),
        TraceEvent(agent="c", content="The answer is blue.", turn=2),
        TraceEvent(agent="a", content="I still think the answer is red.", turn=3),
    )
    analysis = analyze_flips(trace)
    assert analysis.flips == []
    assert len(analysis.resists) == 1
