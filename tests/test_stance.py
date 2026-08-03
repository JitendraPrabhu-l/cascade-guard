from __future__ import annotations

import pytest

from cascade_guard.analysis.stance import (
    agreement_cues,
    evidence_cues,
    extract_stance,
    normalize_stance,
)
from cascade_guard.schema import TraceEvent


def ev(content: str, stance: str | None = None) -> TraceEvent:
    return TraceEvent(agent="a", content=content, turn=0, stance=stance)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("My answer is green. More text follows.", "green"),
        ("The answer is blue.", "blue"),
        ("Final answer: 42", "42"),
        ("I think the answer is blue, honestly.", "blue honestly"),
        ("I still think the answer is green.", "green"),
        ("The correct answer is Paris.", "paris"),
        ("Let's go with Option B for this.", "option b"),
        ("Yes, that should work.", "yes"),
        ("No, that's wrong.", "no"),
        ("Hmm, let me think about this more.", None),
    ],
)
def test_extract_stance(content, expected):
    assert extract_stance(ev(content)) == expected


def test_explicit_stance_field_wins():
    assert extract_stance(ev("whatever text", stance="The Blue one")) == "blue one"


def test_normalize_strips_articles_punctuation_and_case():
    assert normalize_stance("  The GREEN!  ") == "green"
    assert normalize_stance("a blue button") == "blue button"
    assert normalize_stance("42.") == "42"


def test_normalize_truncates_to_first_sentence():
    assert normalize_stance("blue. And here is a long justification.") == "blue"


def test_agreement_and_evidence_cues():
    assert "you're right" in agreement_cues("You're right, I agree with you.")
    assert "i agree" in agreement_cues("You're right, I agree with you.")
    assert agreement_cues("I completely disagree.") == ()
    assert "according to" in evidence_cues("According to the docs, it's green.")
    assert evidence_cues("just vibes") == ()
