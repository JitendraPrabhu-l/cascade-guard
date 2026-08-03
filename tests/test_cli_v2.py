"""CLI coverage for the v2 surface: policy gating, baselines, guard, fleet."""

from __future__ import annotations

import json

from cascade_guard.cli import EXIT_ERROR, EXIT_GATE_FAILED, EXIT_OK, main
from cascade_guard.demo import write_demo_trace

STRICT_POLICY = """
version: 1
pipeline: test-crew
thresholds:
  fail_over: 10
  max_unsupported_flips: 0
"""

LENIENT_POLICY = """
version: 1
pipeline: test-crew
thresholds:
  fail_over: 99
  max_unsupported_flips: 5
"""

SUPPRESSING_POLICY = """
version: 1
pipeline: test-crew
thresholds:
  fail_over: 99
  max_unsupported_flips: 0
suppressions:
  - agent: alice
    kind: unsupported_flip
    reason: "accepted for this fixture"
"""


def _policy(tmp_path, text: str):
    path = tmp_path / "cascade-guard.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# -- analyze + policy --------------------------------------------------


def test_policy_gate_fails_the_run(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    policy = _policy(tmp_path, STRICT_POLICY)
    code = main(["analyze", str(trace), "--policy", str(policy), "--no-policy"])
    assert code == EXIT_OK  # --no-policy wins

    code = main(["analyze", str(trace), "--policy", str(policy)])
    assert code == EXIT_GATE_FAILED
    out = capsys.readouterr().out
    assert "unsupported flip(s) exceed the limit of 0" in out


def test_policy_gate_passes_when_lenient(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    policy = _policy(tmp_path, LENIENT_POLICY)
    assert main(["analyze", str(trace), "--policy", str(policy)]) == EXIT_OK
    assert "policy checks passed" in capsys.readouterr().out


def test_suppression_reported_and_applied(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    policy = _policy(tmp_path, SUPPRESSING_POLICY)
    assert main(["analyze", str(trace), "--policy", str(policy)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "suppressed: unsupported_flip for alice" in out
    assert "accepted for this fixture" in out


def test_policy_auto_discovered_next_to_the_trace(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    _policy(tmp_path, STRICT_POLICY)
    # No --policy flag: discovery walks up from the trace path.
    assert main(["analyze", str(trace), "--quiet"]) == EXIT_GATE_FAILED


def test_explicit_fail_over_overrides_policy(tmp_path):
    trace = write_demo_trace(tmp_path)
    _policy(tmp_path, LENIENT_POLICY)
    assert main(["analyze", str(trace), "--quiet", "--fail-over", "1"]) == EXIT_GATE_FAILED


# -- baselines ---------------------------------------------------------


def test_record_and_check_baseline(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    store = tmp_path / "baseline.jsonl"
    code = main(
        [
            "analyze",
            str(trace),
            "--no-policy",
            "--baseline",
            str(store),
            "--record-baseline",
            "--commit",
            "deadbeef",
            "--quiet",
        ]
    )
    assert code == EXIT_OK
    assert store.exists()
    record = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    assert record["commit"] == "deadbeef"
    assert record["pipeline"] == "default"

    main(["analyze", str(trace), "--no-policy", "--baseline", str(store), "--check-baseline"])
    assert "Baseline (default" in capsys.readouterr().out


def test_pipeline_flag_names_the_baseline_series(tmp_path):
    trace = write_demo_trace(tmp_path)
    store = tmp_path / "b.jsonl"
    main(
        [
            "analyze",
            str(trace),
            "--no-policy",
            "--baseline",
            str(store),
            "--record-baseline",
            "--pipeline",
            "my-crew",
            "--quiet",
        ]
    )
    assert json.loads(store.read_text(encoding="utf-8"))["pipeline"] == "my-crew"


# -- guard -------------------------------------------------------------


def test_guard_replays_and_reports_signals(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    log = tmp_path / "signals.json"
    code = main(["guard", str(trace), "--no-policy", "--json", str(log)])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "unsupported_flip" in out
    assert "consensus_locked" in out
    assert "Final risk" in out

    snapshot = json.loads(log.read_text(encoding="utf-8"))
    assert snapshot["unsupported_flips"] == 1
    assert any(s["kind"] == "unsupported_flip" for s in snapshot["signals"])


def test_guard_halt_gate(tmp_path):
    trace = write_demo_trace(tmp_path)
    args = ["guard", str(trace), "--no-policy", "--fail-on-halt"]
    assert main([*args, "--halt-threshold", "99"]) == EXIT_OK
    assert main([*args, "--halt-threshold", "10"]) == EXIT_GATE_FAILED


def test_guard_observe_only_never_halts(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    code = main(
        [
            "guard",
            str(trace),
            "--no-policy",
            "--observe-only",
            "--halt-threshold",
            "1",
            "--fail-on-halt",
        ]
    )
    assert code == EXIT_OK
    assert "HALTING" not in capsys.readouterr().out


def test_guard_reads_runtime_settings_from_policy(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    _policy(
        tmp_path,
        "version: 1\npipeline: p\nruntime:\n  risk_threshold: 5\n  halt_threshold: 5\n",
    )
    assert main(["guard", str(trace), "--fail-on-halt"]) == EXIT_GATE_FAILED
    assert "HALTING" in capsys.readouterr().out


# -- fleet & policy commands -------------------------------------------


def test_fleet_renders_from_the_store(tmp_path, capsys):
    trace = write_demo_trace(tmp_path)
    store = tmp_path / "b.jsonl"
    for name in ("crew-a", "crew-b"):
        main(
            [
                "analyze",
                str(trace),
                "--no-policy",
                "--baseline",
                str(store),
                "--record-baseline",
                "--pipeline",
                name,
                "--quiet",
            ]
        )
    html = tmp_path / "fleet.html"
    summary = tmp_path / "fleet.json"
    code = main(["fleet", "--baseline", str(store), "--out", str(html), "--json", str(summary)])
    assert code == EXIT_OK
    assert "crew-a" in capsys.readouterr().out
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert "crew-b" in json.loads(summary.read_text(encoding="utf-8"))["pipelines"]


def test_fleet_on_empty_store(tmp_path, capsys):
    assert main(["fleet", "--baseline", str(tmp_path / "none.jsonl")]) == EXIT_OK
    assert "No runs recorded" in capsys.readouterr().out


def test_policy_validate_and_show(tmp_path, capsys):
    policy = _policy(tmp_path, LENIENT_POLICY)
    assert main(["policy", "validate", str(policy)]) == EXIT_OK
    assert "is valid" in capsys.readouterr().out

    assert main(["policy", "show", str(policy)]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["pipeline"] == "test-crew"


def test_policy_validate_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nthresholds:\n  fail_over: 500\n", encoding="utf-8")
    assert main(["policy", "validate", str(bad)]) == EXIT_ERROR
    assert "between 0 and 100" in capsys.readouterr().err


def test_policy_validate_warns_on_expired_suppression(tmp_path, capsys):
    policy = _policy(
        tmp_path,
        'version: 1\nsuppressions:\n  - agent: alice\n    reason: "old"\n    expires: 2020-01-01\n',
    )
    assert main(["policy", "validate", str(policy)]) == EXIT_OK
    assert "expired" in capsys.readouterr().out


def test_demo_runtime_flag(tmp_path, capsys):
    assert main(["demo", "--dir", str(tmp_path / "d"), "--runtime"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "runtime guard replay" in out
    assert "Final runtime risk" in out
