"""Fleet dashboard: a static, self-contained index across many runs.

Answers the operator question the single-run report cannot: which of my
pipelines are getting worse? Renders from the baseline store, so it needs no
server, no database, and no network — just a file you can publish as a CI
artifact or on a static host.
"""

from __future__ import annotations

import html as _html
import statistics
from typing import Any

from cascade_guard.baseline import BaselineRecord, BaselineStore

_GRADE_STATUS = {
    "A": ("good", "✓"),
    "B": ("good", "✓"),
    "C": ("warning", "⚠"),
    "D": ("serious", "⚠"),
    "F": ("critical", "✖"),
}

#: Trend sparkline geometry.
_SPARK_W = 220
_SPARK_H = 40
_SPARK_POINTS = 20

_CSS = """
:root {
  color-scheme: light;
  --page:      #f9f9f7;
  --surface-1: #fcfcfb;
  --text-1:    #0b0b0b;
  --text-2:    #52514e;
  --muted:     #898781;
  --grid:      #e1e0d9;
  --baseline:  #c3c2b7;
  --border:    rgba(11,11,11,0.10);
  --series-1:  #2a78d6;
  --good:      #0ca30c;
  --warning:   #fab219;
  --serious:   #ec835a;
  --critical:  #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page:      #0d0d0d;
    --surface-1: #1a1a19;
    --text-1:    #ffffff;
    --text-2:    #c3c2b7;
    --muted:     #898781;
    --grid:      #2c2c2a;
    --baseline:  #383835;
    --border:    rgba(255,255,255,0.10);
    --series-1:  #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page:      #0d0d0d;
  --surface-1: #1a1a19;
  --text-1:    #ffffff;
  --text-2:    #c3c2b7;
  --muted:     #898781;
  --grid:      #2c2c2a;
  --baseline:  #383835;
  --border:    rgba(255,255,255,0.10);
  --series-1:  #3987e5;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--text-1);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1040px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 36px 0 12px; }
.sub { color: var(--text-2); margin: 0 0 24px; font-size: 13px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile { background: var(--surface-1); border: 1px solid var(--border);
        border-radius: 10px; padding: 14px 16px; }
.tile .label { color: var(--muted); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 650; margin-top: 2px; }
.tile .note { color: var(--text-2); font-size: 12px; margin-top: 2px; }
.chip { display: inline-block; font-size: 12px; font-weight: 600;
        padding: 1px 8px; border-radius: 999px; border: 1px solid currentColor;
        margin-left: 6px; vertical-align: middle; }
.chip.good { color: var(--good); }
.chip.warning { color: var(--warning); }
.chip.serious { color: var(--serious); }
.chip.critical { color: var(--critical); }
table { border-collapse: collapse; width: 100%; background: var(--surface-1);
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 9px 12px; border-top: 1px solid var(--grid);
         font-size: 13px; vertical-align: middle; }
thead th { border-top: 0; color: var(--muted); font-weight: 600; font-size: 12px; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.trend { width: 240px; }
.pipeline { font-weight: 600; }
.empty { color: var(--muted); }
footer { margin-top: 40px; color: var(--muted); font-size: 12px; }
"""


def _esc(value: object) -> str:
    return _html.escape(str(value), quote=True)


def _grade_for(score: float) -> str:
    for ceiling, letter in ((20.0, "A"), (40.0, "B"), (60.0, "C"), (80.0, "D")):
        if score < ceiling:
            return letter
    return "F"


def _grade_chip(grade: str) -> str:
    status, icon = _GRADE_STATUS.get(grade, ("critical", "✖"))
    return f'<span class="chip {status}">{icon} {_esc(grade)}</span>'


def _sparkline(scores: list[float]) -> str:
    """A 2px trend line with a surface-ringed end dot, per the mark spec."""
    points = scores[-_SPARK_POINTS:]
    if len(points) < 2:
        return '<span class="empty">—</span>'
    lo, hi = min(points), max(points)
    span = max(hi - lo, 1.0)
    pad = 5
    step = (_SPARK_W - 2 * pad) / (len(points) - 1)
    coords = [
        (
            pad + i * step,
            _SPARK_H - pad - ((v - lo) / span) * (_SPARK_H - 2 * pad),
        )
        for i, v in enumerate(points)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    end_x, end_y = coords[-1]
    return (
        f'<svg width="{_SPARK_W}" height="{_SPARK_H}" viewBox="0 0 {_SPARK_W} {_SPARK_H}" '
        f'role="img" aria-label="trend of the last {len(points)} runs">'
        f'<polyline points="{path}" fill="none" stroke="var(--series-1)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="4" fill="var(--series-1)" '
        f'stroke="var(--surface-1)" stroke-width="2"/></svg>'
    )


def _tile(label: str, value: str, note: str = "", chip: str = "") -> str:
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (
        f'<div class="tile"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{value}{chip}</div>{note_html}</div>'
    )


def render_fleet_html(store: BaselineStore) -> str:
    """Render the multi-run fleet index from a baseline store."""
    records = store.load()
    by_pipeline: dict[str, list[BaselineRecord]] = {}
    for record in records:
        by_pipeline.setdefault(record.pipeline, []).append(record)

    if not records:
        body = (
            '<p class="empty">No runs recorded yet. Add <code>--record-baseline</code> '
            "to your <code>cascade-guard analyze</code> invocations to build history.</p>"
        )
        tiles = ""
    else:
        all_scores = [r.cascade_risk for r in records]
        latest_scores = [recs[-1].cascade_risk for recs in by_pipeline.values()]
        worst_name, worst_recs = max(by_pipeline.items(), key=lambda kv: kv[1][-1].cascade_risk)
        fleet_median = statistics.median(latest_scores)
        tiles = "".join(
            [
                _tile(
                    "Fleet median risk",
                    f"{fleet_median:.0f}"
                    f"<span style='color:var(--muted);font-size:15px'>/100</span>",
                    chip=_grade_chip(_grade_for(fleet_median)),
                ),
                _tile("Pipelines", str(len(by_pipeline)), note=f"{len(records)} runs recorded"),
                _tile(
                    "Highest risk",
                    f"{worst_recs[-1].cascade_risk:.0f}",
                    note=_esc(worst_name),
                    chip=_grade_chip(worst_recs[-1].grade),
                ),
                _tile(
                    "All-time worst",
                    f"{max(all_scores):.0f}",
                    note="across every recorded run",
                ),
            ]
        )
        rows = []
        for name in sorted(by_pipeline):
            recs = by_pipeline[name]
            scores = [r.cascade_risk for r in recs]
            latest = recs[-1]
            median = statistics.median(scores)
            delta = latest.cascade_risk - median
            arrow = "▲" if delta > 0.5 else ("▼" if delta < -0.5 else "•")
            rows.append(
                f"<tr>"
                f'<td class="pipeline">{_esc(name)}</td>'
                f'<td class="num">{latest.cascade_risk:.1f}{_grade_chip(latest.grade)}</td>'
                f'<td class="num">{median:.1f}</td>'
                f'<td class="num">{arrow} {delta:+.1f}</td>'
                f'<td class="num">{latest.unsupported_flips}</td>'
                f'<td class="num">{len(recs)}</td>'
                f'<td class="trend">{_sparkline(scores)}</td>'
                f"<td>{_esc(latest.recorded_at)}</td>"
                f"</tr>"
            )
        body = (
            "<table><thead><tr><th>Pipeline</th><th class='num'>Latest risk</th>"
            "<th class='num'>Median</th><th class='num'>vs median</th>"
            "<th class='num'>Unsupported flips</th><th class='num'>Runs</th>"
            "<th>Trend (last 20 runs)</th><th>Last recorded</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cascade Guard &mdash; fleet</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Cascade Guard &mdash; fleet overview</h1>
  <p class="sub">source: {_esc(store.path)} &middot; {len(records)} run(s) across
     {len(by_pipeline)} pipeline(s)</p>
  <div class="tiles">{tiles}</div>
  <h2>Pipelines</h2>
  {body}
  <footer>Static report &mdash; regenerate with
  <code>cascade-guard fleet --baseline {_esc(store.path)}</code>.</footer>
</div>
</body>
</html>
"""


def render_fleet_text(store: BaselineStore) -> str:
    """Plain-text fleet summary for terminals and CI logs."""
    summary = store.summary()
    if not summary:
        return "No runs recorded yet. Use --record-baseline to build history."
    lines = ["Pipeline                     Latest   Median    Worst   Runs"]
    lines.append("-" * 62)
    for name in sorted(summary):
        s = summary[name]
        lines.append(
            f"{name[:26]:<26} {s['latest']:>7.1f} {s['median']:>8.1f} "
            f"{s['worst']:>8.1f} {s['runs']:>6}"
        )
    return "\n".join(lines)


def fleet_summary_dict(store: BaselineStore) -> dict[str, Any]:
    return {"path": str(store.path), "pipelines": store.summary()}
