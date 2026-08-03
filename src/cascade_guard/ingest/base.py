"""Adapter interface and registry for trace ingestion."""

from __future__ import annotations

import abc
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from cascade_guard.exceptions import AdapterError
from cascade_guard.schema import Trace

_REGISTRY: dict[str, type[TraceAdapter]] = {}


class TraceAdapter(abc.ABC):
    """Parses one trace file format into the normalized :class:`Trace`."""

    name: ClassVar[str] = ""
    #: Auto-detection order: lower sniffs earlier. Specific formats use low
    #: values; the permissive generic adapter uses a high one.
    priority: ClassVar[int] = 50

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            _REGISTRY[cls.name] = cls

    @classmethod
    @abc.abstractmethod
    def sniff(cls, path: Path) -> bool:
        """Return True if this adapter believes it can parse ``path``."""

    @abc.abstractmethod
    def load(self, path: Path) -> Trace:
        """Parse ``path`` into a normalized trace. Raises AdapterError on failure."""


def available_formats() -> list[str]:
    ranked = sorted(_REGISTRY.items(), key=lambda item: (item[1].priority, item[0]))
    return [name for name, _ in ranked]


def load_trace(path: str | Path, fmt: str = "auto") -> Trace:
    """Load a trace file, auto-detecting the format unless one is named."""
    p = Path(path)
    if not p.exists():
        raise AdapterError(f"trace file not found: {p}")

    if fmt != "auto":
        cls = _REGISTRY.get(fmt)
        if cls is None:
            raise AdapterError(f"unknown format {fmt!r}; available: {available_formats()}")
        return cls().load(p)

    for name in available_formats():
        cls = _REGISTRY[name]
        try:
            if cls.sniff(p):
                return cls().load(p)
        except AdapterError:
            continue
    raise AdapterError(
        f"could not detect the format of {p}. "
        f"Pass --format explicitly (one of: {', '.join(available_formats())})."
    )


def iter_json_records(path: Path) -> Iterator[Any]:
    """Yield JSON records from a .json (document or list) or .jsonl file."""
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    if not stripped:
        raise AdapterError(f"{path} is empty")

    if path.suffix.lower() == ".json" or stripped.startswith("["):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{path}: invalid JSON: {exc}") from exc
        if isinstance(doc, list):
            yield from doc
        else:
            yield doc
        return

    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{path}:{lineno}: invalid JSON line: {exc}") from exc
