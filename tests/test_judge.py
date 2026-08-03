from __future__ import annotations

from dataclasses import dataclass

from cascade_guard.analyze import analyze_trace, apply_judge
from cascade_guard.judge.anthropic_judge import AnthropicJudge
from cascade_guard.judge.base import build_transcript


@dataclass
class _Block:
    type: str
    text: str


class _FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self.content = [_Block("text", text)]
        self.stop_reason = stop_reason


class _FakeClient:
    def __init__(self, text: str, stop_reason: str = "end_turn"):
        self._response = _FakeResponse(text, stop_reason)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_judge_annotates_flip_findings(gangup_trace):
    report = analyze_trace(gangup_trace)
    client = _FakeClient(
        '{"is_sycophantic": true, "confidence": 0.9, "rationale": "pure conformity"}'
    )
    apply_judge(report, AnthropicJudge(client=client))

    flip = report.flips.flips[0]
    assert flip.judge == {
        "is_sycophantic": True,
        "confidence": 0.9,
        "rationale": "pure conformity",
        "model": "claude-haiku-4-5",
    }
    # one API call per finding, transcript included in the prompt
    assert len(client.calls) == 1
    prompt = client.calls[0]["messages"][0]["content"]
    assert "FLIP UNDER REVIEW" in prompt
    assert client.calls[0]["model"] == "claude-haiku-4-5"


def test_judge_handles_refusal_and_garbage(gangup_trace):
    report = analyze_trace(gangup_trace)
    refusing = AnthropicJudge(client=_FakeClient("", stop_reason="refusal"))
    apply_judge(report, refusing)
    assert report.flips.flips[0].judge["is_sycophantic"] is None

    garbled = AnthropicJudge(client=_FakeClient("not json at all"))
    apply_judge(report, garbled)
    assert report.flips.flips[0].judge["confidence"] == 0.0


def test_transcript_marks_the_flip(gangup_trace):
    report = analyze_trace(gangup_trace)
    finding = report.flips.flips[0]
    transcript = build_transcript(finding, gangup_trace)
    assert "FLIP UNDER REVIEW" in transcript
    assert f"[turn {finding.event.turn}]" in transcript


def test_judge_does_not_change_the_score(gangup_trace):
    report = analyze_trace(gangup_trace)
    before = report.score.cascade_risk
    client = _FakeClient('{"is_sycophantic": false, "confidence": 1.0, "rationale": "ok"}')
    apply_judge(report, AnthropicJudge(client=client))
    assert report.score.cascade_risk == before
