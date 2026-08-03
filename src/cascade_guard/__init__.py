"""Cascade Guard: multi-agent reliability profiler.

Point it at your multi-agent trace logs and get a report on where agents
silently agreed with a wrong majority (sycophancy cascades), where errors
compounded across hops, and where token usage blew up.
"""

from __future__ import annotations

from cascade_guard.analyze import AnalysisReport, analyze_trace, apply_judge
from cascade_guard.ingest import available_formats, load_trace
from cascade_guard.schema import SCHEMA_VERSION, Trace, TraceEvent

__version__ = "0.1.0"

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisReport",
    "Trace",
    "TraceEvent",
    "__version__",
    "analyze_trace",
    "apply_judge",
    "available_formats",
    "load_trace",
]
