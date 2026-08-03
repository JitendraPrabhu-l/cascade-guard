"""Deterministic stance extraction and conversational cue detection.

A "stance" is the normalized position an agent is asserting (an answer,
option letter, yes/no, ...). Extraction is heuristic and deterministic on
purpose: it is cheap, reproducible, and unit-testable. The optional LLM
judge (``cascade_guard.judge``) can second-opinion individual findings, but
never replaces this layer.
"""

from __future__ import annotations

import re

from cascade_guard.schema import TraceEvent

_MAX_STANCE_LEN = 80

_SENTENCE_END = re.compile(r"[.!?\n]")
_NON_ALNUM = re.compile(r"[^0-9a-z\s\-]")
_WS = re.compile(r"\s+")
_LEADING_FILLER = (
    "the ",
    "a ",
    "an ",
    "that ",
    "it is ",
    "its ",
    "definitely ",
    "probably ",
    "clearly ",
)

_ANSWER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:my\s+)?final\s+answer\s*(?:is|:)\s*(?P<a>.+)", re.IGNORECASE),
    re.compile(r"(?:the|my)\s+answer\s+(?:is|:)\s*(?P<a>.+)", re.IGNORECASE),
    re.compile(r"(?:the\s+)?correct\s+(?:answer|choice)\s+is\s+(?P<a>.+)", re.IGNORECASE),
    re.compile(
        r"i\s+(?:now\s+)?(?:believe|think|conclude|maintain|still\s+think)\s+"
        r"(?:that\s+)?(?:the\s+answer\s+is\s+)?(?P<a>.+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bit\s+should\s+be\s+(?P<a>.+)", re.IGNORECASE),
)

_OPTION_PATTERN = re.compile(r"\boption\s+(?P<a>[a-e])\b", re.IGNORECASE)

AGREEMENT_CUES: tuple[str, ...] = (
    "i agree",
    "you're right",
    "you are right",
    "good point",
    "fair point",
    "that makes sense",
    "i'll go along",
    "i will go along",
    "i stand corrected",
    "on second thought",
    "you've convinced me",
    "you have convinced me",
    "i defer to",
    "changing my answer",
    "i change my answer",
    "i was wrong",
    "going with the majority",
    "go with the majority",
)

EVIDENCE_CUES: tuple[str, ...] = (
    "according to",
    "the documentation",
    "docs say",
    "the spec says",
    "source:",
    "http://",
    "https://",
    "i ran",
    "i tested",
    "i verified",
    "i checked",
    "the data shows",
    "tool output",
    "the output shows",
    "stack trace",
    "error message",
    "reproduce",
    "reproduced",
    "measured",
    "benchmark",
    "citation",
    "reference:",
)


def normalize_stance(text: str) -> str:
    """Collapse a raw stance phrase into a comparable canonical form."""
    text = text.strip().lower()
    match = _SENTENCE_END.search(text)
    if match:
        text = text[: match.start()]
    text = _NON_ALNUM.sub("", text)
    text = _WS.sub(" ", text).strip()
    changed = True
    while changed:
        changed = False
        for filler in _LEADING_FILLER:
            if text.startswith(filler):
                text = text[len(filler) :]
                changed = True
    return text[:_MAX_STANCE_LEN].strip()


def extract_stance(event: TraceEvent) -> str | None:
    """Extract the normalized stance an event asserts, if any."""
    if event.stance:
        normalized = normalize_stance(event.stance)
        return normalized or None

    content = event.content
    for pattern in _ANSWER_PATTERNS:
        match = pattern.search(content)
        if match:
            normalized = normalize_stance(match.group("a"))
            if normalized:
                return normalized

    match = _OPTION_PATTERN.search(content)
    if match:
        return f"option {match.group('a').lower()}"

    lowered = content.strip().lower()
    if lowered.startswith(("yes,", "yes.", "yes ")):
        return "yes"
    if lowered.startswith(("no,", "no.", "no ")):
        return "no"
    return None


def agreement_cues(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(cue for cue in AGREEMENT_CUES if cue in lowered)


def evidence_cues(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(cue for cue in EVIDENCE_CUES if cue in lowered)
