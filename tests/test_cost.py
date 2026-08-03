from __future__ import annotations

from cascade_guard.analysis.cost import analyze_cost
from cascade_guard.schema import Trace, TraceEvent


def test_gangup_cost_flags_the_blowup_turn(gangup_trace):
    report = analyze_cost(gangup_trace)
    assert report.total_out == sum(e.tokens_out for e in gangup_trace.events)
    spikes = report.spikes
    assert len(spikes) == 1
    assert spikes[0].agent == "alice"
    assert spikes[0].tokens_out == 610


def test_no_token_data_means_no_spikes():
    trace = Trace(
        events=[
            TraceEvent(agent="a", content="x", turn=0),
            TraceEvent(agent="b", content="y", turn=1),
        ]
    )
    report = analyze_cost(trace)
    assert not report.has_token_data
    assert report.spikes == []


def test_small_absolute_values_are_not_spikes():
    # 40 > 2*median(10) but below the absolute floor of 100 tokens.
    trace = Trace(
        events=[
            TraceEvent(agent="a", content="x", turn=0, tokens_out=10),
            TraceEvent(agent="b", content="y", turn=1, tokens_out=10),
            TraceEvent(agent="c", content="z", turn=2, tokens_out=40),
        ]
    )
    assert analyze_cost(trace).spikes == []


def test_per_agent_totals(gangup_trace):
    report = analyze_cost(gangup_trace)
    assert set(report.per_agent_out) == {"alice", "bob", "carol"}
    assert report.per_agent_out["alice"] == 120 + 130 + 610
