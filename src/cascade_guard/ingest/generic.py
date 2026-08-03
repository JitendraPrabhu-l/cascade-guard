"""Generic adapter: Cascade Guard's own flat JSON/JSONL event format.

Each record is an object with at least an agent and a content field.
Common alias keys from ad-hoc logging setups are accepted so most
hand-rolled traces load without conversion:

    {"agent": "planner", "content": "The answer is 42.",
     "role": "assistant", "tokens_in": 120, "tokens_out": 45}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade_guard.exceptions import AdapterError
from cascade_guard.ingest.base import TraceAdapter, iter_json_records
from cascade_guard.schema import Trace, TraceEvent

_AGENT_KEYS = ("agent", "agent_name", "name", "speaker", "node")
_CONTENT_KEYS = ("content", "output", "text", "message", "response")
_TOKENS_IN_KEYS = ("tokens_in", "input_tokens", "prompt_tokens")
_TOKENS_OUT_KEYS = ("tokens_out", "output_tokens", "completion_tokens")


def _first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


class GenericAdapter(TraceAdapter):
    name = "generic"
    priority = 90  # permissive: sniff last during auto-detection

    @classmethod
    def sniff(cls, path: Path) -> bool:
        if path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
            return False
        for record in iter_json_records(path):
            if not isinstance(record, dict):
                return False
            return _first(record, _AGENT_KEYS) is not None and (
                _first(record, _CONTENT_KEYS) is not None
            )
        return False

    def load(self, path: Path) -> Trace:
        events: list[TraceEvent] = []
        for i, record in enumerate(iter_json_records(path)):
            if not isinstance(record, dict):
                raise AdapterError(f"{path}: record {i} is not a JSON object")
            agent = _first(record, _AGENT_KEYS)
            content = _first(record, _CONTENT_KEYS)
            if agent is None or content is None:
                raise AdapterError(
                    f"{path}: record {i} is missing an agent or content field "
                    f"(accepted agent keys: {_AGENT_KEYS}, content keys: {_CONTENT_KEYS})"
                )
            evidence = record.get("evidence") or ()
            if isinstance(evidence, str):
                evidence = (evidence,)
            events.append(
                TraceEvent(
                    agent=str(agent),
                    content=str(content),
                    turn=int(record.get("turn", i)),
                    run_id=str(record.get("run_id", "run-0")),
                    event_id=str(record.get("event_id", f"evt-{i}")),
                    role=str(record.get("role", "assistant")),
                    timestamp=record.get("timestamp"),
                    tokens_in=int(_first(record, _TOKENS_IN_KEYS) or 0),
                    tokens_out=int(_first(record, _TOKENS_OUT_KEYS) or 0),
                    stance=record.get("stance"),
                    evidence=tuple(str(e) for e in evidence),
                    metadata=dict(record.get("metadata") or {}),
                )
            )
        if not events:
            raise AdapterError(f"{path}: no events found")
        return Trace(events=events, run_id=events[0].run_id, source=str(path))
