"""LangGraph adapter.

Parses trace files produced by dumping a LangGraph run to JSONL. Two common
shapes are supported, and they can be mixed in one file:

1. ``stream_mode="updates"`` dumps — one JSON object per graph step, mapping
   node name to its state update::

       {"researcher": {"messages": [{"type": "ai", "content": "...",
                                     "usage_metadata": {"input_tokens": 10,
                                                        "output_tokens": 5}}]}}

2. Plain message-list records — ``{"messages": [...]}`` — e.g. a dumped final
   state, or per-step message snapshots.

Message dicts may be either the plain LangChain shape (``type``/``content``/
``name``/``usage_metadata``) or the ``lc`` serialized-constructor shape
(``{"lc": 1, "type": "constructor", "id": [..., "AIMessage"],
"kwargs": {...}}``) produced by ``langchain_core.load.dumpd``.

To produce a compatible file from a LangGraph app::

    import json
    with open("trace.jsonl", "w") as f:
        for update in graph.stream(inputs, stream_mode="updates"):
            f.write(json.dumps(update, default=lambda o: o.dict()) + "\\n")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade_guard.exceptions import AdapterError
from cascade_guard.ingest.base import TraceAdapter, iter_json_records
from cascade_guard.schema import Trace, TraceEvent

_ROLE_MAP = {
    "ai": "assistant",
    "aimessage": "assistant",
    "aimessagechunk": "assistant",
    "assistant": "assistant",
    "human": "user",
    "humanmessage": "user",
    "user": "user",
    "tool": "tool",
    "toolmessage": "tool",
    "function": "tool",
    "system": "system",
    "systemmessage": "system",
}


def _message_payload(msg: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Return (fields, raw_type) for plain or lc-serialized message dicts."""
    if msg.get("lc") is not None and isinstance(msg.get("kwargs"), dict):
        ident = msg.get("id")
        raw_type = ident[-1] if isinstance(ident, list) and ident else ""
        return msg["kwargs"], str(raw_type)
    raw_type = str(msg.get("type") or msg.get("role") or "")
    return msg, raw_type


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return "" if content is None else str(content)


def _iter_message_groups(record: dict[str, Any]) -> list[tuple[str | None, list[Any]]]:
    """Yield (node_name, messages) groups found in one JSON record."""
    groups: list[tuple[str | None, list[Any]]] = []
    if isinstance(record.get("messages"), list):
        groups.append((None, record["messages"]))
        return groups
    for node, payload in record.items():
        if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
            groups.append((node, payload["messages"]))
    return groups


def events_from_update(record: dict[str, Any], start_turn: int = 0) -> list[TraceEvent]:
    """Convert one LangGraph update payload into normalized events.

    Shared by the file adapter and the runtime guard so a live run and its
    post-hoc analysis see identical events.
    """
    events: list[TraceEvent] = []
    turn = start_turn
    for node, messages in _iter_message_groups(record):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            event = _parse_message(msg, node, turn)
            if event is not None:
                events.append(event)
                turn += 1
    return events


def _parse_message(msg: dict[str, Any], node: str | None, turn: int) -> TraceEvent | None:
    fields, raw_type = _message_payload(msg)
    role = _ROLE_MAP.get(raw_type.lower(), "assistant")
    content = _text_content(fields.get("content"))
    if not content and role != "tool":
        return None
    agent = str(fields.get("name") or node or role)
    usage = fields.get("usage_metadata") or {}
    if not isinstance(usage, dict):
        usage = {}
    metadata: dict[str, Any] = {}
    if fields.get("tool_calls"):
        metadata["tool_calls"] = fields["tool_calls"]
    if node is not None:
        metadata["node"] = node
    return TraceEvent(
        agent=agent,
        content=content,
        turn=turn,
        event_id=str(fields.get("id") or f"lg-{turn}"),
        role=role,
        tokens_in=int(usage.get("input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        metadata=metadata,
    )


class LangGraphAdapter(TraceAdapter):
    name = "langgraph"
    priority = 10

    @classmethod
    def sniff(cls, path: Path) -> bool:
        if path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
            return False
        for checked, record in enumerate(iter_json_records(path)):
            if not isinstance(record, dict):
                return False
            if _iter_message_groups(record):
                return True
            if checked >= 4:
                break
        return False

    def load(self, path: Path) -> Trace:
        events: list[TraceEvent] = []
        for record in iter_json_records(path):
            if not isinstance(record, dict):
                continue
            events.extend(events_from_update(record, start_turn=len(events)))
        if not events:
            raise AdapterError(
                f"{path}: no LangGraph messages found. Expected 'updates'-style "
                "records ({node: {'messages': [...]}}) or {'messages': [...]} records."
            )
        return Trace(events=events, source=str(path))
