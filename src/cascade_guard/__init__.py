"""Cascade Guard: multi-agent reliability profiler.

Point it at your multi-agent trace logs and get a report on where agents
silently agreed with a wrong majority (sycophancy cascades), where errors
compounded across hops, and where token usage blew up.

Post-hoc profiling::

    from cascade_guard import load_trace, analyze_trace

    report = analyze_trace(load_trace("trace.jsonl"), wrong_answer="blue")

Runtime guarding, during a live run::

    from cascade_guard import CascadeGuard

    guard = CascadeGuard(halt_threshold=85)
    for signal in guard.observe_many(events):
        ...
"""

from __future__ import annotations

from cascade_guard.analyze import AnalysisReport, analyze_trace, apply_judge
from cascade_guard.baseline import BaselineStore, DriftReport
from cascade_guard.ingest import available_formats, load_trace
from cascade_guard.policy import Policy, load_policy
from cascade_guard.runtime import CascadeGuard, Intervention, InterventionKind, Signal
from cascade_guard.schema import SCHEMA_VERSION, Trace, TraceEvent

__version__ = "0.2.0"

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisReport",
    "BaselineStore",
    "CascadeGuard",
    "DriftReport",
    "Intervention",
    "InterventionKind",
    "Policy",
    "Signal",
    "Trace",
    "TraceEvent",
    "__version__",
    "analyze_trace",
    "apply_judge",
    "available_formats",
    "load_policy",
    "load_trace",
]
