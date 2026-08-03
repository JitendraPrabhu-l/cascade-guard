"""A deliberately tiny YAML subset parser.

The core package ships with zero runtime dependencies, but policy files are
much nicer in YAML than JSON. Rather than force PyYAML on every user, this
module parses the subset a policy file actually needs:

- nested block mappings (any consistent indent)
- block sequences (``- item``) of scalars, inline mappings, or nested blocks
- scalars: strings (bare, single- or double-quoted), ints, floats, booleans,
  ``null``/``~``; ISO dates stay strings
- ``#`` comments and blank lines
- inline flow collections (``[a, b]`` / ``{k: v}``)

If PyYAML is installed, :func:`safe_load` defers to it, so anything outside
this subset still works for users who have that dependency. Constructs this
parser cannot handle raise :class:`PolicyError` with a line number rather
than silently mis-parsing.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from cascade_guard.exceptions import PolicyError

_BOOLS = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
#: Unquoted ISO dates become ``datetime.date``, matching PyYAML, so the two
#: backends produce identical objects.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def safe_load(text: str) -> Any:
    """Parse a YAML document. Uses PyYAML when available, else the subset."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return parse(text)
    try:
        return yaml.safe_load(text)
    except Exception as exc:  # pragma: no cover - depends on env
        raise PolicyError(f"invalid YAML: {exc}") from exc


class _Line:
    __slots__ = ("indent", "lineno", "text")

    def __init__(self, indent: int, text: str, lineno: int) -> None:
        self.indent = indent
        self.text = text
        self.lineno = lineno


def _strip_comment(raw: str) -> str:
    """Remove a trailing ``#`` comment that is not inside quotes."""
    quote: str | None = None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def _tokenize(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise PolicyError(f"line {lineno}: tabs are not allowed for indentation")
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        if stripped.lstrip().startswith("---"):
            continue
        indent = len(stripped) - len(stripped.lstrip())
        lines.append(_Line(indent, stripped.strip(), lineno))
    return lines


def parse(text: str) -> Any:
    """Parse using the built-in subset parser (no PyYAML required).

    A document with no content parses to ``None``, matching PyYAML, so
    callers see identical behavior whichever backend is in use.
    """
    lines = _tokenize(text)
    if not lines:
        return None
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines):
        raise PolicyError(
            f"line {lines[index].lineno}: unexpected indentation; check that nesting is consistent"
        )
    return value


def _parse_block(lines: list[_Line], start: int, indent: int) -> tuple[Any, int]:
    if lines[start].text.startswith("- "):
        return _parse_sequence(lines, start, indent)
    if lines[start].text == "-":
        return _parse_sequence(lines, start, indent)
    return _parse_mapping(lines, start, indent)


def _parse_mapping(lines: list[_Line], start: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    i = start
    while i < len(lines):
        line = lines[i]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise PolicyError(f"line {line.lineno}: unexpected indentation")
        if ":" not in line.text:
            raise PolicyError(f"line {line.lineno}: expected 'key: value', got {line.text!r}")
        key_raw, _, rest = line.text.partition(":")
        key = _scalar_key(key_raw, line.lineno)
        rest = rest.strip()
        if rest:
            result[key] = _parse_scalar(rest, line.lineno)
            i += 1
            continue
        # Value lives on the following, more-indented lines.
        if i + 1 < len(lines) and lines[i + 1].indent > indent:
            value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
            result[key] = value
        elif (
            i + 1 < len(lines)
            and lines[i + 1].indent == indent
            and (lines[i + 1].text.startswith("- ") or lines[i + 1].text == "-")
        ):
            # A sequence may sit at the same indent as its key.
            value, i = _parse_sequence(lines, i + 1, indent)
            result[key] = value
        else:
            result[key] = None
            i += 1
    return result, i


def _parse_sequence(lines: list[_Line], start: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise PolicyError(f"line {line.lineno}: unexpected indentation in sequence")
        if not (line.text.startswith("- ") or line.text == "-"):
            break
        item = line.text[1:].strip()
        if not item:
            if i + 1 < len(lines) and lines[i + 1].indent > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
                result.append(value)
                continue
            result.append(None)
            i += 1
            continue
        if ":" in item and not item.startswith(("[", "{", '"', "'")):
            # Inline mapping opening an item: "- key: value" plus any
            # deeper lines that belong to the same item.
            item_lines = [_Line(indent + 2, item, line.lineno)]
            j = i + 1
            while j < len(lines) and lines[j].indent > indent:
                item_lines.append(lines[j])
                j += 1
            value, consumed = _parse_mapping(item_lines, 0, indent + 2)
            if consumed != len(item_lines):
                raise PolicyError(f"line {line.lineno}: could not parse sequence item")
            result.append(value)
            i = j
            continue
        result.append(_parse_scalar(item, line.lineno))
        i += 1
    return result, i


def _parse_scalar(raw: str, lineno: int) -> Any:
    value = raw.strip()
    if not value:
        return None
    if value[0] in "\"'":
        if len(value) < 2 or value[-1] != value[0]:
            raise PolicyError(f"line {lineno}: unterminated quoted string: {raw!r}")
        return value[1:-1]
    if value in ("null", "~"):
        return None
    lowered = value.lower()
    if lowered in _BOOLS:
        return _BOOLS[lowered]
    if value.startswith(("[", "{")):
        return _parse_flow(value, lineno)
    if _ISO_DATE.match(value):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            pass  # e.g. 2026-13-45 — fall through and keep it a string
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_flow(value: str, lineno: int) -> Any:
    body = value[1:-1].strip() if len(value) >= 2 else ""
    if value.startswith("["):
        if not value.endswith("]"):
            raise PolicyError(f"line {lineno}: unterminated flow sequence: {value!r}")
        if not body:
            return []
        return [_parse_scalar(part, lineno) for part in _split_flow(body)]
    if not value.endswith("}"):
        raise PolicyError(f"line {lineno}: unterminated flow mapping: {value!r}")
    if not body:
        return {}
    result: dict[str, Any] = {}
    for part in _split_flow(body):
        if ":" not in part:
            raise PolicyError(f"line {lineno}: expected 'key: value' in {part!r}")
        key, _, val = part.partition(":")
        result[_scalar_key(key, lineno)] = _parse_scalar(val, lineno)
    return result


def _split_flow(body: str) -> list[str]:
    """Split on commas that are not inside quotes or nested brackets."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for ch in body:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch in "[{":
            depth += 1
            current.append(ch)
        elif ch in "]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _scalar_key(raw: str, lineno: int) -> str:
    key = raw.strip()
    if len(key) >= 2 and key[0] in "\"'" and key[-1] == key[0]:
        key = key[1:-1]
    if not key:
        raise PolicyError(f"line {lineno}: empty mapping key")
    return key
