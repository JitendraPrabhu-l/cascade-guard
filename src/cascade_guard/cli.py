"""Command-line interface.

cascade-guard analyze trace.jsonl --out report.html
cascade-guard analyze trace.jsonl --wrong-answer "blue" --json report.json
cascade-guard analyze trace.jsonl --fail-over 60          # CI gate
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
from cascade_guard.exceptions import CascadeGuardError
from cascade_guard.ingest import available_formats, load_trace
from cascade_guard.report import render_html, render_text

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_GATE_FAILED = 2


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

    demo = sub.add_parser(
        "demo", help="generate the labeled gang-up scenario and analyze it end to end"
    )
    demo.add_argument(
        "--dir", default="demo_output", help="output directory (default: demo_output)"
    )

    sub.add_parser("formats", help="list supported trace formats")
    return parser


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


def _cmd_analyze(args: argparse.Namespace) -> int:
    trace = load_trace(args.trace, fmt=args.format)
    report = analyze_trace(trace, wrong_answer=args.wrong_answer)
    if args.judge == "anthropic":
        from cascade_guard.judge.anthropic_judge import DEFAULT_MODEL, AnthropicJudge

        judge = AnthropicJudge(model=args.judge_model or DEFAULT_MODEL)
        apply_judge(report, judge)
    _emit_outputs(report, args)
    if args.fail_over is not None and report.score.cascade_risk > args.fail_over:
        print(
            f"FAIL: cascade risk {report.score.cascade_risk:.1f} exceeds the "
            f"--fail-over threshold of {args.fail_over:.1f}",
            file=sys.stderr,
        )
        return EXIT_GATE_FAILED
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
