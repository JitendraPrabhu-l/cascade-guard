"""Command-line interface.

cascade-guard analyze trace.jsonl --out report.html
cascade-guard analyze trace.jsonl --wrong-answer "blue" --json report.json
cascade-guard analyze trace.jsonl --policy cascade-guard.yaml    # policy gate
cascade-guard analyze trace.jsonl --record-baseline              # build history
cascade-guard guard trace.jsonl --halt-threshold 80              # runtime replay
cascade-guard fleet --out fleet.html                             # multi-run index
cascade-guard policy validate
cascade-guard demo --dir demo_output
cascade-guard formats
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cascade_guard import __version__
from cascade_guard.analyze import AnalysisReport, analyze_trace, apply_judge
from cascade_guard.baseline import BaselineStore
from cascade_guard.exceptions import CascadeGuardError
from cascade_guard.ingest import available_formats, load_trace
from cascade_guard.policy import Policy, find_policy_file, load_policy
from cascade_guard.report import render_html, render_text

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_GATE_FAILED = 2

DEFAULT_BASELINE_PATH = ".cascade-guard/baseline.jsonl"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cascade-guard",
        description=(
            "Multi-agent reliability profiler: detect sycophancy cascades, "
            "false consensus, error propagation, and token blowups in agent traces."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="analyze a trace file and report findings")
    analyze.add_argument("trace", help="path to the trace file (.json / .jsonl)")
    analyze.add_argument(
        "--format",
        default="auto",
        choices=["auto", *available_formats()],
        help="trace format (default: auto-detect)",
    )
    analyze.add_argument(
        "--wrong-answer",
        default=None,
        help="known-wrong final answer; enables the error propagation tracer",
    )
    analyze.add_argument("--out", default=None, help="write an HTML report to this path")
    analyze.add_argument("--json", default=None, help="write the full report as JSON")
    analyze.add_argument(
        "--fail-over",
        type=float,
        default=None,
        metavar="SCORE",
        help="exit with status 2 if cascade risk exceeds SCORE (CI gate, 0-100)",
    )
    analyze.add_argument(
        "--policy",
        default=None,
        metavar="PATH",
        help="policy file to enforce (default: auto-discover cascade-guard.yaml)",
    )
    analyze.add_argument(
        "--no-policy", action="store_true", help="ignore any discovered policy file"
    )
    analyze.add_argument(
        "--pipeline",
        default=None,
        help="pipeline name for baselines (default: from policy, else 'default')",
    )
    analyze.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE_PATH,
        metavar="PATH",
        help=f"baseline store path (default: {DEFAULT_BASELINE_PATH})",
    )
    analyze.add_argument(
        "--record-baseline",
        action="store_true",
        help="append this run's score to the baseline store",
    )
    analyze.add_argument(
        "--check-baseline",
        action="store_true",
        help="compare against baseline history and report drift",
    )
    analyze.add_argument(
        "--commit", default="", help="commit SHA to record alongside the baseline entry"
    )
    analyze.add_argument(
        "--judge",
        choices=["anthropic"],
        default=None,
        help="second-opinion each flip finding with an LLM judge (needs the "
        "'judge' extra and ANTHROPIC_API_KEY)",
    )
    analyze.add_argument(
        "--judge-model",
        default=None,
        help="model id for the LLM judge (default: claude-haiku-4-5)",
    )
    analyze.add_argument("--quiet", action="store_true", help="suppress the console report")

    guard = sub.add_parser(
        "guard",
        help="replay a trace through the runtime guard, showing live signals",
    )
    guard.add_argument("trace", help="path to the trace file")
    guard.add_argument("--format", default="auto", choices=["auto", *available_formats()])
    guard.add_argument("--policy", default=None, help="policy file supplying runtime settings")
    guard.add_argument("--no-policy", action="store_true", help="ignore any policy file")
    guard.add_argument(
        "--risk-threshold", type=float, default=None, help="risk at which to signal (0-100)"
    )
    guard.add_argument(
        "--halt-threshold",
        type=float,
        default=None,
        help="risk at which the guard recommends halting the run",
    )
    guard.add_argument(
        "--observe-only",
        action="store_true",
        help="downgrade every intervention to a warning",
    )
    guard.add_argument("--json", default=None, help="write the signal log as JSON")
    guard.add_argument(
        "--fail-on-halt",
        action="store_true",
        help="exit with status 2 if the guard recommended halting",
    )

    fleet = sub.add_parser("fleet", help="render the multi-run fleet dashboard")
    fleet.add_argument("--baseline", default=DEFAULT_BASELINE_PATH, help="baseline store path")
    fleet.add_argument("--out", default=None, help="write the fleet HTML dashboard here")
    fleet.add_argument("--json", default=None, help="write the fleet summary as JSON")

    policy_cmd = sub.add_parser("policy", help="inspect and validate policy files")
    policy_sub = policy_cmd.add_subparsers(dest="policy_command", required=True)
    validate = policy_sub.add_parser("validate", help="validate a policy file")
    validate.add_argument(
        "path", nargs="?", default=None, help="policy file (default: auto-discover)"
    )
    show = policy_sub.add_parser("show", help="print the effective policy as JSON")
    show.add_argument("path", nargs="?", default=None)

    demo = sub.add_parser(
        "demo", help="generate the labeled gang-up scenario and analyze it end to end"
    )
    demo.add_argument(
        "--dir", default="demo_output", help="output directory (default: demo_output)"
    )
    demo.add_argument(
        "--runtime",
        action="store_true",
        help="also replay the scenario through the runtime guard",
    )

    sub.add_parser("formats", help="list supported trace formats")
    return parser


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------


def _resolve_policy(
    explicit: str | None, disabled: bool, *, near: str | None = None
) -> Policy | None:
    if disabled:
        return None
    if explicit:
        return load_policy(explicit)
    found = find_policy_file(near or ".")
    return load_policy(found) if found else None


def _emit_outputs(report: AnalysisReport, args: argparse.Namespace) -> None:
    if not args.quiet:
        print(render_text(report))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(report), encoding="utf-8")
        print(f"HTML report written to {out}")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"JSON report written to {out}")


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def _cmd_analyze(args: argparse.Namespace) -> int:
    policy = _resolve_policy(args.policy, args.no_policy, near=args.trace)
    trace = load_trace(args.trace, fmt=args.format)
    report = analyze_trace(trace, wrong_answer=args.wrong_answer)

    if args.judge == "anthropic":
        from cascade_guard.judge.anthropic_judge import DEFAULT_MODEL, AnthropicJudge

        apply_judge(report, AnthropicJudge(model=args.judge_model or DEFAULT_MODEL))

    _emit_outputs(report, args)

    failed = False
    pipeline = args.pipeline or (policy.pipeline if policy else "default")

    if policy is not None:
        decision = policy.evaluate(report)
        if not args.quiet:
            print(f"\nPolicy: {policy.source} (pipeline '{policy.pipeline}')")
            for item in decision.suppressed:
                print(
                    f"  suppressed: {item['kind']} for {item['agent']} at turn "
                    f"{item['turn']} — {item['reason']}"
                )
            for warning in decision.warnings:
                print(f"  warning: {warning}")
            for reason in decision.reasons:
                print(f"  FAIL: {reason}")
            if decision.passed and not decision.reasons:
                print("  policy checks passed")
        failed = failed or not decision.passed

    store = BaselineStore(args.baseline)
    if args.check_baseline or (policy is not None and policy.baseline_enabled):
        max_regression = policy.max_regression if policy else None
        drift = store.compare(report, pipeline=pipeline, max_regression=max_regression)
        if not args.quiet:
            print(f"\nBaseline ({pipeline}, n={drift.n_history}):")
            if drift.has_baseline:
                print(
                    f"  median {drift.median:.1f}, current {drift.current:.1f} "
                    f"({drift.delta:+.1f}, z={drift.z_score:.2f})"
                )
            for reason in drift.reasons:
                prefix = "FAIL" if drift.regressed else "note"
                print(f"  {prefix}: {reason}")
        failed = failed or drift.regressed

    if args.record_baseline:
        record = store.append(report, pipeline=pipeline, commit=args.commit)
        if not args.quiet:
            print(f"\nBaseline updated: {store.path} ({record.pipeline})")

    threshold = args.fail_over
    if threshold is None and policy is not None:
        threshold = policy.fail_over
    if threshold is not None and report.score.cascade_risk > threshold:
        print(
            f"FAIL: cascade risk {report.score.cascade_risk:.1f} exceeds the "
            f"threshold of {threshold:.1f}",
            file=sys.stderr,
        )
        failed = True

    return EXIT_GATE_FAILED if failed else EXIT_OK


def _cmd_guard(args: argparse.Namespace) -> int:
    from cascade_guard.runtime import CascadeGuard

    policy = _resolve_policy(args.policy, args.no_policy, near=args.trace)
    kwargs = policy.guard_kwargs() if policy else {}
    if args.risk_threshold is not None:
        kwargs["risk_threshold"] = args.risk_threshold
    if args.halt_threshold is not None:
        kwargs["halt_threshold"] = args.halt_threshold
    if args.observe_only:
        kwargs["observe_only"] = True

    trace = load_trace(args.trace, fmt=args.format)
    guard = CascadeGuard(**kwargs)

    print(f"Replaying {len(trace.events)} event(s) through the runtime guard...\n")
    for signal in guard.observe_many(trace.events):
        marker = "!" if signal.actionable else "-"
        print(
            f" {marker} [turn {signal.event.turn}] {signal.kind.value} "
            f"({signal.severity}, risk {signal.risk:.0f}): {signal.message}"
        )
        if signal.actionable:
            target = signal.intervention.target_agent or "the crew"
            print(f"     -> {signal.intervention.kind.value} for {target}")

    snapshot = guard.snapshot()
    print(
        f"\nFinal risk: {guard.risk:.1f}/100  |  signals: {len(guard.signals)}  |  "
        f"mean observe cost: {snapshot.get('mean_observe_us', 0)} us/event"
    )
    if guard.should_halt:
        print("The guard recommended HALTING this run.")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"Signal log written to {out}")

    if args.fail_on_halt and guard.should_halt:
        return EXIT_GATE_FAILED
    return EXIT_OK


def _cmd_fleet(args: argparse.Namespace) -> int:
    from cascade_guard.report.fleet import (
        fleet_summary_dict,
        render_fleet_html,
        render_fleet_text,
    )

    store = BaselineStore(args.baseline)
    print(render_fleet_text(store))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_fleet_html(store), encoding="utf-8")
        print(f"\nFleet dashboard written to {out}")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(fleet_summary_dict(store), indent=2), encoding="utf-8")
        print(f"Fleet summary written to {out}")
    return EXIT_OK


def _cmd_policy(args: argparse.Namespace) -> int:
    path = args.path or find_policy_file(".")
    if path is None:
        print(
            "error: no policy file found. Create a cascade-guard.yaml or pass a path.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    policy = load_policy(path)
    if args.policy_command == "show":
        print(json.dumps(policy.to_dict(), indent=2))
        return EXIT_OK

    print(f"Policy {policy.source} is valid (pipeline '{policy.pipeline}').")
    expired = [s for s in policy.suppressions if s.expired()]
    for sup in expired:
        print(
            f"  warning: suppression for agent={sup.agent or '*'} "
            f"kind={sup.kind or '*'} expired on {sup.expires}"
        )
    return EXIT_OK


def _cmd_demo(args: argparse.Namespace) -> int:
    from cascade_guard.demo import WRONG_ANSWER, write_demo_trace

    directory = Path(args.dir)
    trace_path = write_demo_trace(directory)
    print(f"Demo trace written to {trace_path}")
    trace = load_trace(trace_path)
    report = analyze_trace(trace, wrong_answer=WRONG_ANSWER)
    print(render_text(report))

    html_path = directory / "demo_report.html"
    html_path.write_text(render_html(report), encoding="utf-8")
    json_path = directory / "demo_report.json"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"HTML report written to {html_path}")
    print(f"JSON report written to {json_path}")

    if args.runtime:
        from cascade_guard.runtime import CascadeGuard

        print("\n--- runtime guard replay ---")
        guard = CascadeGuard(halt_threshold=85.0)
        for signal in guard.observe_many(trace.events):
            marker = "!" if signal.actionable else "-"
            print(
                f" {marker} [turn {signal.event.turn}] {signal.kind.value} "
                f"(risk {signal.risk:.0f}): {signal.message}"
            )
            if signal.intervention.prompt:
                print(f"     -> inject: {signal.intervention.prompt[:90]}...")
        print(f"Final runtime risk: {guard.risk:.1f}/100")
    return EXIT_OK


def _cmd_formats() -> int:
    for name in available_formats():
        print(name)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "analyze":
            return _cmd_analyze(args)
        if args.command == "guard":
            return _cmd_guard(args)
        if args.command == "fleet":
            return _cmd_fleet(args)
        if args.command == "policy":
            return _cmd_policy(args)
        if args.command == "demo":
            return _cmd_demo(args)
        if args.command == "formats":
            return _cmd_formats()
    except CascadeGuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def entrypoint() -> None:  # console_scripts target
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
