"""Score history and statistical drift detection.

A fixed threshold answers "is this run bad?"; a baseline answers "is this run
worse than this pipeline usually is?" — which is the question that catches a
prompt change quietly making a crew more sycophantic while still sitting
under the absolute limit.

The store is a JSON Lines file (append-only, one record per run) so it diffs
cleanly in git, needs no database, and can be committed alongside the policy
or kept as a CI artifact.

Drift is flagged with a robust z-score built on the median and the median
absolute deviation, not the mean and standard deviation: cascade scores are
skewed and a couple of genuinely bad historical runs would otherwise inflate
the spread and mask a real regression.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cascade_guard.exceptions import BaselineError

if TYPE_CHECKING:
    from cascade_guard.analyze import AnalysisReport

#: Runs needed before drift is reported; below this the sample says nothing.
MIN_HISTORY = 5
#: Robust z-score at which a run is called drifted (~3 sigma equivalent).
DRIFT_Z = 3.0
#: Scale factor making MAD a consistent estimator of sigma for normal data.
_MAD_TO_SIGMA = 1.4826
#: Floor on the spread estimate, so a perfectly flat history does not make
#: every 0.1-point wobble look like an infinite z-score.
_MIN_SPREAD = 1.0


@dataclass(frozen=True)
class BaselineRecord:
    """One historical run."""

    pipeline: str
    cascade_risk: float
    grade: str
    unsupported_flips: int
    n_events: int
    n_agents: int
    recorded_at: str
    run_id: str = ""
    source: str = ""
    tool_version: str = ""
    commit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineRecord:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class DriftReport:
    """Comparison of one run against its pipeline's history."""

    pipeline: str
    current: float
    n_history: int
    median: float | None = None
    spread: float | None = None
    z_score: float | None = None
    delta: float | None = None
    drifted: bool = False
    regressed: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def has_baseline(self) -> bool:
        return self.median is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "current": round(self.current, 1),
            "n_history": self.n_history,
            "median": round(self.median, 1) if self.median is not None else None,
            "spread": round(self.spread, 2) if self.spread is not None else None,
            "z_score": round(self.z_score, 2) if self.z_score is not None else None,
            "delta": round(self.delta, 1) if self.delta is not None else None,
            "drifted": self.drifted,
            "regressed": self.regressed,
            "reasons": self.reasons,
        }


class BaselineStore:
    """Append-only JSONL store of per-pipeline run history."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, pipeline: str | None = None) -> list[BaselineRecord]:
        """Read history, optionally filtered to one pipeline (oldest first)."""
        if not self.path.exists():
            return []
        records: list[BaselineRecord] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BaselineError(f"could not read baseline store {self.path}: {exc}") from exc
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BaselineError(
                    f"{self.path}:{lineno}: corrupt baseline record: {exc}"
                ) from exc
            try:
                record = BaselineRecord.from_dict(data)
            except TypeError as exc:
                raise BaselineError(
                    f"{self.path}:{lineno}: baseline record is missing fields: {exc}"
                ) from exc
            if pipeline is None or record.pipeline == pipeline:
                records.append(record)
        return records

    def append(
        self,
        report: AnalysisReport,
        *,
        pipeline: str = "default",
        commit: str = "",
    ) -> BaselineRecord:
        """Record one run's outcome."""
        record = BaselineRecord(
            pipeline=pipeline,
            cascade_risk=round(report.score.cascade_risk, 2),
            grade=report.score.grade,
            unsupported_flips=len(report.flips.unsupported_flips),
            n_events=report.n_events,
            n_agents=report.n_agents,
            recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            run_id=report.trace.run_id,
            source=report.trace.source,
            tool_version=report.tool_version,
            commit=commit,
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict()) + "\n")
        except OSError as exc:
            raise BaselineError(f"could not write baseline store {self.path}: {exc}") from exc
        return record

    def compare(
        self,
        report: AnalysisReport,
        *,
        pipeline: str = "default",
        max_regression: float | None = None,
    ) -> DriftReport:
        """Compare a run against its pipeline's history."""
        history = self.load(pipeline)
        current = report.score.cascade_risk
        drift = DriftReport(pipeline=pipeline, current=current, n_history=len(history))

        if len(history) < MIN_HISTORY:
            drift.reasons.append(
                f"only {len(history)} historical run(s) for '{pipeline}'; "
                f"{MIN_HISTORY} are needed before drift is meaningful"
            )
            return drift

        scores = [r.cascade_risk for r in history]
        median = statistics.median(scores)
        mad = statistics.median([abs(s - median) for s in scores])
        spread = max(mad * _MAD_TO_SIGMA, _MIN_SPREAD)

        drift.median = median
        drift.spread = spread
        drift.delta = current - median
        drift.z_score = (current - median) / spread

        if drift.z_score >= DRIFT_Z:
            drift.drifted = True
            drift.reasons.append(
                f"cascade risk {current:.1f} is {drift.z_score:.1f} robust "
                f"sigma above the {pipeline} median of {median:.1f} "
                f"(n={len(history)})"
            )
        if max_regression is not None and drift.delta > max_regression:
            drift.regressed = True
            drift.reasons.append(
                f"cascade risk rose {drift.delta:.1f} over the baseline median, "
                f"exceeding the allowed regression of {max_regression:g}"
            )
        return drift

    def summary(self) -> dict[str, dict[str, Any]]:
        """Per-pipeline aggregate, for the fleet dashboard."""
        by_pipeline: dict[str, list[BaselineRecord]] = {}
        for record in self.load():
            by_pipeline.setdefault(record.pipeline, []).append(record)
        result: dict[str, dict[str, Any]] = {}
        for name, records in by_pipeline.items():
            scores = [r.cascade_risk for r in records]
            result[name] = {
                "runs": len(records),
                "median": round(statistics.median(scores), 1),
                "latest": round(scores[-1], 1),
                "worst": round(max(scores), 1),
                "last_recorded": records[-1].recorded_at,
            }
        return result
