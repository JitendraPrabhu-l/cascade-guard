from __future__ import annotations

import pytest

from cascade_guard.demo import demo_events, write_demo_trace
from cascade_guard.ingest import load_trace
from cascade_guard.schema import Trace, TraceEvent


@pytest.fixture()
def gangup_trace(tmp_path) -> Trace:
    """The labeled gang-up scenario, loaded through the real generic adapter."""
    path = write_demo_trace(tmp_path)
    return load_trace(path)


@pytest.fixture()
def gangup_records() -> list[dict]:
    return demo_events()


def make_event(agent: str, content: str, turn: int, **kwargs) -> TraceEvent:
    return TraceEvent(agent=agent, content=content, turn=turn, **kwargs)
