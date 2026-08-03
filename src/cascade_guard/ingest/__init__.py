"""Trace ingestion: adapters that normalize framework logs into the schema."""

from __future__ import annotations

from cascade_guard.ingest.base import TraceAdapter, available_formats, load_trace
from cascade_guard.ingest.generic import GenericAdapter
from cascade_guard.ingest.langgraph import LangGraphAdapter

__all__ = [
    "GenericAdapter",
    "LangGraphAdapter",
    "TraceAdapter",
    "available_formats",
    "load_trace",
]
