from __future__ import annotations

import json

from cascade_guard.cli import EXIT_GATE_FAILED, EXIT_OK, main
from cascade_guard.demo import write_demo_trace


def test_demo_command_produces_all_artifacts(tmp_path, capsys):
    directory = tmp_path / "demo"
    assert main(["demo", "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Cascade risk" in out
    assert (directory / "demo_gangup.jsonl").exists()
    assert (directory / "demo_report.html").exists()
    assert (directory / "demo_report.json").exists()


def test_analyze_writes_html_and_json(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    html = tmp_path / "r.html"
    js = tmp_path / "r.json"
    code = main(
        [
            "analyze",
            str(trace),
            "--wrong-answer",
            "blue",
            "--out",
            str(html),
            "--json",
            str(js),
            "--quiet",
        ]
    )
    assert code == EXIT_OK
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["propagation"]["origin_agent"] == "bob"


def test_fail_over_gate(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    assert main(["analyze", str(trace), "--quiet", "--fail-over", "99"]) == EXIT_OK
    code = main(["analyze", str(trace), "--wrong-answer", "blue", "--quiet", "--fail-over", "10"])
    assert code == EXIT_GATE_FAILED
    assert "exceeds" in capsys.readouterr().err


def test_missing_file_is_a_clean_error(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing.jsonl")]) == 1
    assert "error:" in capsys.readouterr().err


def test_formats_command(capsys):
    assert main(["formats"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "langgraph" in out
    assert "generic" in out
