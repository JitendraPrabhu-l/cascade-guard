"""Optional LLM-as-judge layer for second-opinioning heuristic findings."""

from __future__ import annotations

from cascade_guard.judge.base import FlipJudge, JudgeVerdict

__all__ = ["FlipJudge", "JudgeVerdict"]
