from __future__ import annotations

import json

from cascade_guard.analyze import analyze_trace
from cascade_guard.baseline import BaselineStore
from cascade_guard.report.fleet import (
    fleet_summary_dict,
    render_fleet_html,
    render_fleet_text,
)


def test_empty_store_renders_guidance(tmp_path):
    store = BaselineStore(tmp_path / "b.jsonl")
    html = render_fleet_html(store)
    assert html.startswith("<!DOCTYPE html>")
    assert "No runs recorded yet" in html
    assert "No runs recorded" in render_fleet_text(store)


def test_fleet_html_lists_pipelines(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    report = analyze_trace(gangup_trace)
    for _ in range(3):
        store.append(report, pipeline="research-crew")
    store.append(report, pipeline="support-triage")

    html = render_fleet_html(store)
    assert "research-crew" in html
    assert "support-triage" in html
    assert "<svg" in html  # trend sparkline rendered
    # self-contained: no external assets
    assert "http://" not in html
    assert "https://" not in html
    assert "<script" not in html


def test_fleet_html_escapes_pipeline_names(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    store.append(analyze_trace(gangup_trace), pipeline="<script>alert(1)</script>")
    html = render_fleet_html(store)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_single_run_has_no_sparkline(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    store.append(analyze_trace(gangup_trace), pipeline="solo")
    html = render_fleet_html(store)
    assert "solo" in html
    assert "—" in html  # trend placeholder for a single point


def test_fleet_text_table(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    store.append(analyze_trace(gangup_trace), pipeline="crew")
    text = render_fleet_text(store)
    assert "crew" in text
    assert "Latest" in text


def test_fleet_summary_is_json_safe(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    store.append(analyze_trace(gangup_trace), pipeline="crew")
    payload = json.dumps(fleet_summary_dict(store))
    assert "crew" in payload
