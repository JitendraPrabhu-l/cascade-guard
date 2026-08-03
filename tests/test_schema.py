from __future__ import annotations

import pytest

from cascade_guard.schema import Trace, TraceEvent


def test_event_validation_rejects_bad_values():
    with pytest.raises(ValueError):
        TraceEvent(agent="", content="x", turn=0)
    with pytest.raises(ValueError):
        TraceEvent(agent="a", content="x", turn=-1)
    with pytest.raises(ValueError):
        TraceEvent(agent="a", content="x", turn=0, tokens_out=-5)


def test_trace_sorts_events_by_turn():
    events = [
        TraceEvent(agent="b", content="second", turn=1),
        TraceEvent(agent="a", content="first", turn=0),
    ]
    trace = Trace(events=events)
    assert [e.turn for e in trace.events] == [0, 1]


def test_agents_in_order_of_first_appearance_assistant_only():
    events = [
        TraceEvent(agent="planner", content="hi", turn=0),
        TraceEvent(agent="search", content="result", turn=1, role="tool"),
        TraceEvent(agent="critic", content="hm", turn=2),
        TraceEvent(agent="planner", content="again", turn=3),
    ]
    trace = Trace(events=events)
    assert trace.agents == ["planner", "critic"]


def test_event_to_dict_roundtrips_evidence_as_list():
    ev = TraceEvent(agent="a", content="x", turn=0, evidence=("doc-1",))
    assert ev.to_dict()["evidence"] == ["doc-1"]


def test_trace_token_totals():
    events = [
        TraceEvent(agent="a", content="x", turn=0, tokens_in=10, tokens_out=5),
        TraceEvent(agent="b", content="y", turn=1, tokens_in=20, tokens_out=7),
    ]
    trace = Trace(events=events)
    assert trace.total_tokens_in == 30
    assert trace.total_tokens_out == 12
