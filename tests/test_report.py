from __future__ import annotations

import json

from cascade_guard.analyze import analyze_trace
from cascade_guard.demo import WRONG_ANSWER
from cascade_guard.report import render_html, render_text


def test_text_report_mentions_key_findings(gangup_trace):
    report = analyze_trace(gangup_trace, wrong_answer=WRONG_ANSWER)
    text = render_text(report)
    assert "Cascade risk" in text
    assert "alice" in text
    assert "'green' -> 'blue'" in text
    assert "introduced by bob" in text
    assert "token spike" in text


def test_html_report_is_self_contained_and_escaped(gangup_trace):
    report = analyze_trace(gangup_trace, wrong_answer=WRONG_ANSWER)
    html = render_html(report)
    assert html.startswith("<!DOCTYPE html>")
    assert "alice" in html
    assert "Cascade risk" in html
    assert "▲ spike" in html
    # self-contained: no external fetches
    assert "http://" not in html
    assert "https://" not in html
    assert "<script src" not in html


def test_html_escapes_hostile_content(gangup_trace):
    from cascade_guard.schema import Trace, TraceEvent

    trace = Trace(
        events=[
            TraceEvent(agent="<script>alert(1)</script>", content="The answer is x.", turn=0),
            TraceEvent(agent="b", content="The answer is <img onerror=x>.", turn=1),
        ],
        source="evil.jsonl",
    )
    html = render_html(analyze_trace(trace))
    assert "<script>alert(1)</script>" not in html
    assert "<img onerror" not in html


def test_report_to_dict_is_json_serializable(gangup_trace):
    report = analyze_trace(gangup_trace, wrong_answer=WRONG_ANSWER)
    payload = json.dumps(report.to_dict())
    data = json.loads(payload)
    assert data["tool"] == "cascade-guard"
    assert data["score"]["grade"] in "ABCDF"
    assert data["flips"]["unsupported_flips"] == 1
