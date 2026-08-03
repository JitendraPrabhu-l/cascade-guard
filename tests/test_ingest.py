from __future__ import annotations

import json

import pytest

from cascade_guard.exceptions import AdapterError
from cascade_guard.ingest import available_formats, load_trace
from cascade_guard.ingest.langgraph import LangGraphAdapter


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_available_formats_order_prefers_specific_first():
    formats = available_formats()
    assert formats.index("langgraph") < formats.index("generic")


def test_generic_adapter_accepts_alias_keys(tmp_path):
    path = tmp_path / "trace.jsonl"
    _write_jsonl(
        path,
        [
            {"name": "planner", "text": "The answer is 42.", "output_tokens": 9},
            {"agent": "critic", "content": "I agree.", "tokens_out": 4},
        ],
    )
    trace = load_trace(path)
    assert trace.agents == ["planner", "critic"]
    assert trace.events[0].tokens_out == 9
    assert trace.events[1].content == "I agree."


def test_generic_adapter_reads_json_array(tmp_path):
    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps([{"agent": "a", "content": "x"}, {"agent": "b", "content": "y"}]),
        encoding="utf-8",
    )
    trace = load_trace(path, fmt="generic")
    assert len(trace.events) == 2


def test_langgraph_updates_format(tmp_path):
    path = tmp_path / "lg.jsonl"
    _write_jsonl(
        path,
        [
            {
                "researcher": {
                    "messages": [
                        {
                            "type": "ai",
                            "content": "The answer is blue.",
                            "usage_metadata": {"input_tokens": 100, "output_tokens": 40},
                        }
                    ]
                }
            },
            {
                "critic": {
                    "messages": [{"type": "ai", "name": "critic-1", "content": "I disagree."}]
                }
            },
        ],
    )
    assert LangGraphAdapter.sniff(path)
    trace = load_trace(path)
    assert trace.source.endswith("lg.jsonl")
    assert trace.events[0].agent == "researcher"
    assert trace.events[0].tokens_out == 40
    assert trace.events[1].agent == "critic-1"
    assert trace.events[1].metadata["node"] == "critic"


def test_langgraph_lc_serialized_messages(tmp_path):
    path = tmp_path / "lg.jsonl"
    _write_jsonl(
        path,
        [
            {
                "messages": [
                    {
                        "lc": 1,
                        "type": "constructor",
                        "id": ["langchain", "schema", "messages", "AIMessage"],
                        "kwargs": {
                            "content": "The answer is green.",
                            "name": "alice",
                            "usage_metadata": {"input_tokens": 5, "output_tokens": 3},
                        },
                    },
                    {
                        "lc": 1,
                        "type": "constructor",
                        "id": ["langchain", "schema", "messages", "ToolMessage"],
                        "kwargs": {"content": "search result", "name": "web_search"},
                    },
                ]
            }
        ],
    )
    trace = load_trace(path, fmt="langgraph")
    assert trace.events[0].agent == "alice"
    assert trace.events[0].role == "assistant"
    assert trace.events[1].role == "tool"


def test_langgraph_content_block_lists(tmp_path):
    path = tmp_path / "lg.jsonl"
    _write_jsonl(
        path,
        [
            {
                "writer": {
                    "messages": [
                        {
                            "type": "ai",
                            "content": [
                                {"type": "text", "text": "part one"},
                                {"type": "text", "text": "part two"},
                            ],
                        }
                    ]
                }
            }
        ],
    )
    trace = load_trace(path)
    assert trace.events[0].content == "part one\npart two"


def test_unknown_format_and_missing_file(tmp_path):
    with pytest.raises(AdapterError):
        load_trace(tmp_path / "nope.jsonl")
    path = tmp_path / "t.jsonl"
    path.write_text('{"agent": "a", "content": "x"}', encoding="utf-8")
    with pytest.raises(AdapterError):
        load_trace(path, fmt="not-a-format")


def test_undetectable_file_raises(tmp_path):
    path = tmp_path / "junk.jsonl"
    path.write_text('{"foo": 1}', encoding="utf-8")
    with pytest.raises(AdapterError):
        load_trace(path)
