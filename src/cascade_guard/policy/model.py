"""Policy model: declarative thresholds, suppressions, and gating rules.

A policy file is checked into the repo next to the pipeline it governs and
reviewed like any other config. Example ``cascade-guard.yaml``::

    version: 1
    pipeline: research-crew

    thresholds:
      fail_over: 60          # CI fails above this cascade risk
      warn_over: 40
      max_unsupported_flips: 2

    runtime:
      risk_threshold: 55
      halt_threshold: 85
      min_agents: 3
      warmup_turns: 2
      observe_only: false

    baseline:
      enabled: true
      max_regression: 10     # fail if risk rises this much over baseline

    suppressions:
      - agent: flaky-summarizer
        kind: unsupported_flip
        reason: "known verbose restatement, tracked in ENG-4821"
        expires: 2026-12-31

Suppressions **must** carry a reason and may carry an expiry; an expired
suppression stops suppressing and is reported, so stale exceptions surface
instead of silently accumulating.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cascade_guard.exceptions import PolicyError
from cascade_guard.policy.minyaml import safe_load

#: Filenames searched for, in order, when no policy path is given.
DEFAULT_POLICY_FILENAMES = ("cascade-guard.yaml", "cascade-guard.yml", ".cascade-guard.yaml")

_KNOWN_TOP_LEVEL = {
    "version",
    "pipeline",
    "thresholds",
    "runtime",
    "baseline",
    "suppressions",
}
_SUPPORTED_VERSIONS = (1,)


def _as_mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PolicyError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _as_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{where}: expected a number, got {value!r}")
    return float(value)


def _parse_date(value: Any, where: str) -> _dt.date | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise PolicyError(f"{where}: expected an ISO date (YYYY-MM-DD), got {value!r}") from exc


@dataclass(frozen=True)
class Suppression:
    """Silences one class of finding, with an audit trail."""

    reason: str
    agent: str | None = None
    kind: str | None = None
    expires: _dt.date | None = None

    def expired(self, today: _dt.date | None = None) -> bool:
        if self.expires is None:
            return False
        return (today or _dt.date.today()) > self.expires

    def matches(self, *, agent: str, kind: str) -> bool:
        if self.agent is not None and self.agent != agent:
            return False
        return not (self.kind is not None and self.kind != kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "kind": self.kind,
            "reason": self.reason,
            "expires": self.expires.isoformat() if self.expires else None,
        }


@dataclass
class PolicyDecision:
    """The outcome of evaluating a report against a policy."""

    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    expired_suppressions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "warnings": self.warnings,
            "suppressed": self.suppressed,
            "expired_suppressions": self.expired_suppressions,
        }


@dataclass
class Policy:
    """A parsed, validated policy."""

    pipeline: str = "default"
    version: int = 1
    fail_over: float | None = None
    warn_over: float | None = None
    max_unsupported_flips: int | None = None
    runtime: dict[str, Any] = field(default_factory=dict)
    baseline_enabled: bool = False
    max_regression: float | None = None
    suppressions: list[Suppression] = field(default_factory=list)
    source: str = ""

    # -- construction --------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "") -> Policy:
        data = _as_mapping(data, "policy")
        unknown = set(data) - _KNOWN_TOP_LEVEL
        if unknown:
            raise PolicyError(
                f"unknown top-level key(s): {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(_KNOWN_TOP_LEVEL))}"
            )
        version = data.get("version", 1)
        if version not in _SUPPORTED_VERSIONS:
            raise PolicyError(
                f"unsupported policy version {version!r}; this build supports "
                f"{', '.join(str(v) for v in _SUPPORTED_VERSIONS)}"
            )

        thresholds = _as_mapping(data.get("thresholds"), "thresholds")
        baseline = _as_mapping(data.get("baseline"), "baseline")
        runtime = _as_mapping(data.get("runtime"), "runtime")

        max_flips = thresholds.get("max_unsupported_flips")
        if max_flips is not None:
            max_flips = int(_as_number(max_flips, "thresholds.max_unsupported_flips"))

        policy = cls(
            pipeline=str(data.get("pipeline") or "default"),
            version=int(version),
            fail_over=(
                _as_number(thresholds["fail_over"], "thresholds.fail_over")
                if thresholds.get("fail_over") is not None
                else None
            ),
            warn_over=(
                _as_number(thresholds["warn_over"], "thresholds.warn_over")
                if thresholds.get("warn_over") is not None
                else None
            ),
            max_unsupported_flips=max_flips,
            runtime=runtime,
            baseline_enabled=bool(baseline.get("enabled", False)),
            max_regression=(
                _as_number(baseline["max_regression"], "baseline.max_regression")
                if baseline.get("max_regression") is not None
                else None
            ),
            suppressions=cls._parse_suppressions(data.get("suppressions")),
            source=source,
        )
        policy._validate()
        return policy

    @staticmethod
    def _parse_suppressions(raw: Any) -> list[Suppression]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise PolicyError("suppressions: expected a list")
        result: list[Suppression] = []
        for i, item in enumerate(raw):
            where = f"suppressions[{i}]"
            entry = _as_mapping(item, where)
            reason = entry.get("reason")
            if not reason or not str(reason).strip():
                raise PolicyError(f"{where}: a 'reason' is required so suppressions stay auditable")
            if entry.get("agent") is None and entry.get("kind") is None:
                raise PolicyError(
                    f"{where}: specify at least one of 'agent' or 'kind'; a "
                    "suppression matching everything would hide all findings"
                )
            result.append(
                Suppression(
                    reason=str(reason),
                    agent=str(entry["agent"]) if entry.get("agent") is not None else None,
                    kind=str(entry["kind"]) if entry.get("kind") is not None else None,
                    expires=_parse_date(entry.get("expires"), f"{where}.expires"),
                )
            )
        return result

    def _validate(self) -> None:
        for name in ("fail_over", "warn_over"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 100.0:
                raise PolicyError(f"thresholds.{name} must be between 0 and 100, got {value}")
        if (
            self.fail_over is not None
            and self.warn_over is not None
            and self.warn_over > self.fail_over
        ):
            raise PolicyError(
                f"thresholds.warn_over ({self.warn_over:g}) must not exceed "
                f"thresholds.fail_over ({self.fail_over:g})"
            )
        if self.max_unsupported_flips is not None and self.max_unsupported_flips < 0:
            raise PolicyError("thresholds.max_unsupported_flips must be >= 0")
        if self.max_regression is not None and self.max_regression < 0:
            raise PolicyError("baseline.max_regression must be >= 0")

    # -- evaluation ----------------------------------------------------

    def guard_kwargs(self) -> dict[str, Any]:
        """Runtime-guard constructor arguments declared by this policy."""
        allowed = {
            "risk_threshold",
            "halt_threshold",
            "min_agents",
            "warmup_turns",
            "max_interventions_per_agent",
            "observe_only",
        }
        unknown = set(self.runtime) - allowed
        if unknown:
            raise PolicyError(
                f"unknown runtime key(s): {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(allowed))}"
            )
        return dict(self.runtime)

    def evaluate(self, report: Any, *, today: _dt.date | None = None) -> PolicyDecision:
        """Evaluate an :class:`~cascade_guard.analyze.AnalysisReport`."""
        decision = PolicyDecision(passed=True)
        today = today or _dt.date.today()

        active: list[Suppression] = []
        for sup in self.suppressions:
            if sup.expired(today):
                decision.expired_suppressions.append(sup.to_dict())
                decision.warnings.append(
                    f"suppression for agent={sup.agent or '*'} kind={sup.kind or '*'} "
                    f"expired on {sup.expires}; it is no longer being applied"
                )
            else:
                active.append(sup)

        counted_flips = 0
        for finding in report.flips.unsupported_flips:
            match = next(
                (s for s in active if s.matches(agent=finding.agent, kind="unsupported_flip")),
                None,
            )
            if match is not None:
                decision.suppressed.append(
                    {
                        "agent": finding.agent,
                        "turn": finding.event.turn,
                        "kind": "unsupported_flip",
                        "reason": match.reason,
                    }
                )
            else:
                counted_flips += 1

        risk = report.score.cascade_risk
        if self.fail_over is not None and risk > self.fail_over:
            decision.passed = False
            decision.reasons.append(
                f"cascade risk {risk:.1f} exceeds fail_over threshold {self.fail_over:g}"
            )
        elif self.warn_over is not None and risk > self.warn_over:
            decision.warnings.append(
                f"cascade risk {risk:.1f} exceeds warn_over threshold {self.warn_over:g}"
            )

        if self.max_unsupported_flips is not None and counted_flips > self.max_unsupported_flips:
            decision.passed = False
            decision.reasons.append(
                f"{counted_flips} unsupported flip(s) exceed the limit of "
                f"{self.max_unsupported_flips}"
            )
        return decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "version": self.version,
            "source": self.source,
            "thresholds": {
                "fail_over": self.fail_over,
                "warn_over": self.warn_over,
                "max_unsupported_flips": self.max_unsupported_flips,
            },
            "runtime": self.runtime,
            "baseline": {
                "enabled": self.baseline_enabled,
                "max_regression": self.max_regression,
            },
            "suppressions": [s.to_dict() for s in self.suppressions],
        }


def find_policy_file(start: str | Path = ".") -> Path | None:
    """Search ``start`` and its parents for a policy file."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        for name in DEFAULT_POLICY_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def load_policy(path: str | Path) -> Policy:
    """Load and validate a policy file."""
    p = Path(path)
    if not p.is_file():
        raise PolicyError(f"policy file not found: {p}")
    try:
        raw = safe_load(p.read_text(encoding="utf-8-sig"))
    except PolicyError as exc:
        raise PolicyError(f"{p}: {exc}") from exc
    if raw is None:
        raise PolicyError(f"{p}: policy file is empty")
    try:
        return Policy.from_dict(raw, source=str(p))
    except PolicyError as exc:
        raise PolicyError(f"{p}: {exc}") from exc
