from __future__ import annotations

import json

import pytest

from cascade_guard.analyze import analyze_trace
from cascade_guard.baseline import MIN_HISTORY, BaselineRecord, BaselineStore
from cascade_guard.exceptions import BaselineError


def _seed(path, pipeline: str, scores: list[float]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for i, score in enumerate(scores):
            fh.write(
                json.dumps(
                    {
                        "pipeline": pipeline,
                        "cascade_risk": score,
                        "grade": "A",
                        "unsupported_flips": 0,
                        "n_events": 8,
                        "n_agents": 3,
                        "recorded_at": f"2026-01-{i + 1:02d}T00:00:00+00:00",
                    }
                )
                + "\n"
            )


def test_append_and_load_roundtrip(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    report = analyze_trace(gangup_trace)
    record = store.append(report, pipeline="crew", commit="abc123")

    assert record.pipeline == "crew"
    assert record.commit == "abc123"
    loaded = store.load("crew")
    assert len(loaded) == 1
    assert loaded[0].cascade_risk == pytest.approx(report.score.cascade_risk, abs=0.01)


def test_append_creates_parent_directories(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "nested" / "deep" / "b.jsonl")
    store.append(analyze_trace(gangup_trace))
    assert store.path.exists()


def test_load_filters_by_pipeline(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    report = analyze_trace(gangup_trace)
    store.append(report, pipeline="a")
    store.append(report, pipeline="b")
    assert len(store.load()) == 2
    assert len(store.load("a")) == 1


def test_missing_store_is_empty_not_an_error(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "absent.jsonl")
    assert store.load() == []
    drift = store.compare(analyze_trace(gangup_trace))
    assert not drift.has_baseline
    assert not drift.regressed


def test_malformed_json_raises_with_line_number(tmp_path):
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [10.0])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
    with pytest.raises(BaselineError, match=r":2: corrupt baseline record"):
        BaselineStore(path).load()


def test_incomplete_record_raises_with_line_number(tmp_path):
    path = tmp_path / "b.jsonl"
    path.write_text('{"pipeline": "a"}\n', encoding="utf-8")
    with pytest.raises(BaselineError, match=r":1: baseline record is missing fields"):
        BaselineStore(path).load()


def test_small_history_reports_insufficient_data(tmp_path, gangup_trace):
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [10.0, 11.0])
    drift = BaselineStore(path).compare(analyze_trace(gangup_trace), pipeline="crew")
    assert not drift.drifted
    assert not drift.has_baseline
    assert str(MIN_HISTORY) in drift.reasons[0]


def test_drift_flags_a_regression(tmp_path, gangup_trace):
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [10.0, 11.0, 12.0, 10.5, 11.5, 9.5, 10.2, 11.1])
    drift = BaselineStore(path).compare(analyze_trace(gangup_trace), pipeline="crew")
    assert drift.has_baseline
    assert drift.drifted
    assert drift.z_score > 3.0
    assert drift.delta > 0


def test_stable_run_does_not_drift(tmp_path, gangup_trace):
    report = analyze_trace(gangup_trace)
    current = report.score.cascade_risk
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [current + d for d in (-1, 0, 1, -0.5, 0.5, 0.2, -0.2, 0.1)])
    drift = BaselineStore(path).compare(report, pipeline="crew")
    assert not drift.drifted
    assert not drift.regressed


def test_max_regression_gate(tmp_path, gangup_trace):
    report = analyze_trace(gangup_trace)
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [report.score.cascade_risk - 20] * 8)
    store = BaselineStore(path)
    assert store.compare(report, pipeline="crew", max_regression=5).regressed
    assert not store.compare(report, pipeline="crew", max_regression=50).regressed


def test_flat_history_does_not_explode_the_z_score(tmp_path, gangup_trace):
    """A zero-spread history must not make a trivial delta look infinite."""
    report = analyze_trace(gangup_trace)
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [report.score.cascade_risk] * 8)
    drift = BaselineStore(path).compare(report, pipeline="crew")
    assert drift.spread >= 1.0
    assert abs(drift.z_score) < 1.0
    assert not drift.drifted


def test_summary_groups_by_pipeline(tmp_path, gangup_trace):
    store = BaselineStore(tmp_path / "b.jsonl")
    report = analyze_trace(gangup_trace)
    store.append(report, pipeline="a")
    store.append(report, pipeline="a")
    store.append(report, pipeline="b")
    summary = store.summary()
    assert summary["a"]["runs"] == 2
    assert summary["b"]["runs"] == 1
    assert "median" in summary["a"]


def test_record_ignores_unknown_fields():
    record = BaselineRecord.from_dict(
        {
            "pipeline": "a",
            "cascade_risk": 1.0,
            "grade": "A",
            "unsupported_flips": 0,
            "n_events": 1,
            "n_agents": 1,
            "recorded_at": "now",
            "future_field": "from a newer version",
        }
    )
    assert record.pipeline == "a"


def test_drift_report_is_json_safe(tmp_path, gangup_trace):
    path = tmp_path / "b.jsonl"
    _seed(path, "crew", [10.0] * 8)
    drift = BaselineStore(path).compare(analyze_trace(gangup_trace), pipeline="crew")
    json.dumps(drift.to_dict())
