"""Self-contained static HTML report (no external assets, light + dark)."""

from __future__ import annotations

import html as _html

from cascade_guard.analyze import AnalysisReport

_GRADE_STATUS = {
    "A": ("good", "✓", "low risk"),
    "B": ("good", "✓", "low risk"),
    "C": ("warning", "⚠", "moderate risk"),
    "D": ("serious", "⚠", "elevated risk"),
    "F": ("critical", "✖", "high risk"),
}

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
  margin: 0;
  background: var(--page);
  color: var(--text-1);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 36px 0 12px; }
.sub { color: var(--text-2); margin: 0 0 24px; font-size: 13px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tile {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.tile .label { color: var(--muted); font-size: 12px; }
.tile .value { font-size: 26px; font-weight: 650; margin-top: 2px; }
.tile .note  { color: var(--text-2); font-size: 12px; margin-top: 2px; }
.chip {
  display: inline-block; font-size: 12px; font-weight: 600;
  padding: 1px 8px; border-radius: 999px; border: 1px solid currentColor;
  margin-left: 6px; vertical-align: middle;
}
.chip.good     { color: var(--good); }
.chip.warning  { color: var(--warning); }
.chip.serious  { color: var(--serious); }
.chip.critical { color: var(--critical); }
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.card .head { font-weight: 600; }
.card .meta { color: var(--text-2); font-size: 12.5px; margin-top: 2px; }
.card blockquote {
  margin: 8px 0 0; padding: 6px 12px;
  border-left: 2px solid var(--baseline);
  color: var(--text-2); font-size: 13px;
}
.empty { color: var(--muted); }
table { border-collapse: collapse; width: 100%; background: var(--surface-1);
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
th, td { text-align: left; padding: 7px 12px; border-top: 1px solid var(--grid); font-size: 13px; }
thead th { border-top: 0; color: var(--muted); font-weight: 600; font-size: 12px; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.bars { background: var(--surface-1); border: 1px solid var(--border);
        border-radius: 10px; padding: 14px 16px; }
.bar-row { display: grid; grid-template-columns: 150px 1fr 120px; align-items: center;
           gap: 10px; padding: 1px 0; }
.bar-row .who { color: var(--text-2); font-size: 12.5px; white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; }
.bar-track { position: relative; height: 12px; border-left: 1px solid var(--baseline); }
.bar-fill { position: absolute; inset: 0 auto 0 0; height: 12px;
            background: var(--series-1); border-radius: 0 4px 4px 0; min-width: 2px; }
.bar-row + .bar-row .bar-track { margin-top: 2px; }
.bar-val { font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums;
           white-space: nowrap; }
.spike-flag { color: var(--serious); font-weight: 600; }
footer { margin-top: 40px; color: var(--muted); font-size: 12px; }
"""


def _esc(value: object) -> str:
    return _html.escape(str(value), quote=True)


def _tile(label: str, value: str, note: str = "", chip: str = "") -> str:
    note_html = f'<div class="note">{note}</div>' if note else ""
    return (
        f'<div class="tile"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{value}{chip}</div>{note_html}</div>'
    )


def _grade_chip(grade: str) -> str:
    status, icon, label = _GRADE_STATUS.get(grade, ("critical", "✖", "unknown"))
    return f'<span class="chip {status}">{icon} {_esc(grade)} · {_esc(label)}</span>'


def _flip_cards(report: AnalysisReport) -> str:
    flips = report.flips.flips
    if not flips:
        return '<p class="empty">No position flips toward a majority were detected.</p>'
    cards = []
    for f in flips:
        kind = "evidence-based" if f.evidence_based else "unsupported"
        cues = ", ".join(f.agreement_cues) if f.agreement_cues else "none"
        judge_html = ""
        if f.judge:
            judge_html = (
                f'<div class="meta">LLM judge ({_esc(f.judge["model"])}): '
                f"sycophantic = {_esc(f.judge['is_sycophantic'])}, "
                f"confidence {_esc(f.judge['confidence'])} — "
                f"{_esc(f.judge['rationale'])}</div>"
            )
        cards.append(
            f'<div class="card">'
            f'<div class="head">Turn {f.event.turn}: {_esc(f.agent)} flipped '
            f"&ldquo;{_esc(f.from_stance)}&rdquo; &rarr; &ldquo;{_esc(f.to_stance)}&rdquo;</div>"
            f'<div class="meta">{kind} &middot; severity {_esc(f.severity)} &middot; '
            f"majority of {f.majority_size}/{f.peers_with_stance} peers &middot; "
            f"held prior stance for {f.turns_held} turn(s) &middot; "
            f"agreement cues: {_esc(cues)}</div>"
            f"{judge_html}"
            f"<blockquote>{_esc(f.event.content[:400])}</blockquote>"
            f"</div>"
        )
    return "".join(cards)


def _propagation_section(report: AnalysisReport) -> str:
    prop = report.propagation
    if prop is None:
        return (
            '<p class="empty">Not computed — pass <code>--wrong-answer</code> with the '
            "known-wrong final answer to trace which agent introduced it.</p>"
        )
    if prop.origin is None:
        return (
            f'<p class="empty">The wrong answer &ldquo;{_esc(prop.wrong_stance)}&rdquo; '
            "was never asserted in this trace.</p>"
        )
    adopters = ", ".join(_esc(a) for a in prop.adopter_agents) or "none"
    capit = (
        f'<div class="meta">Capitulated after initially disagreeing: '
        f"{', '.join(_esc(a) for a in prop.capitulated_agents)}</div>"
        if prop.capitulated_agents
        else ""
    )
    return (
        f'<div class="card">'
        f'<div class="head">&ldquo;{_esc(prop.wrong_stance)}&rdquo; was introduced by '
        f"{_esc(prop.origin_agent)} at turn {prop.origin.turn}</div>"
        f'<div class="meta">Adopted downstream by {len(prop.adopters)} of '
        f"{max(prop.total_agents - 1, 0)} other agent(s) ({adopters}) &middot; "
        f"infection rate {prop.infection_rate:.0%}</div>"
        f"{capit}"
        f"<blockquote>{_esc(prop.origin.content[:400])}</blockquote>"
        f"</div>"
    )


def _token_bars(report: AnalysisReport) -> str:
    cost = report.cost
    if not cost.has_token_data:
        return '<p class="empty">This trace carries no token metadata.</p>'
    rows = [t for t in cost.per_event if t.tokens_out > 0]
    if not rows:
        return '<p class="empty">No output-token data per event.</p>'
    peak = max(t.tokens_out for t in rows)
    out = ['<div class="bars">']
    for t in rows:
        width = max(0.5, 100.0 * t.tokens_out / peak)
        spike = ' <span class="spike-flag">▲ spike</span>' if t.is_spike else ""
        tip = f"turn {t.turn} · {t.agent} · {t.tokens_out:,} output tokens"
        out.append(
            f'<div class="bar-row" title="{_esc(tip)}">'
            f'<div class="who">t{t.turn} · {_esc(t.agent)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div>'
            f'<div class="bar-val">{t.tokens_out:,}{spike}</div>'
            f"</div>"
        )
    out.append("</div>")
    return "".join(out)


def _timeline_table(report: AnalysisReport) -> str:
    timeline = report.flips.timeline
    if not timeline:
        return '<p class="empty">No extractable stances in this trace.</p>'
    rows = "".join(
        f"<tr><td class='num'>{rec.event.turn}</td><td>{_esc(rec.event.agent)}</td>"
        f"<td>{_esc(rec.stance)}</td></tr>"
        for rec in timeline
    )
    return (
        "<table><thead><tr><th class='num'>Turn</th><th>Agent</th><th>Stance</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def render_html(report: AnalysisReport) -> str:
    score = report.score
    flips = report.flips
    cost = report.cost
    tokens_note = (
        f"in {cost.total_in:,} / out {cost.total_out:,}" if cost.has_token_data else "no data"
    )
    tiles = "".join(
        [
            _tile(
                "Cascade risk",
                f"{score.cascade_risk:.0f}<span style='color:var(--muted);font-size:15px'>"
                "/100</span>",
                chip=_grade_chip(score.grade),
            ),
            _tile(
                "Unsupported flips",
                str(len(flips.unsupported_flips)),
                note=f"{len(flips.flips)} flips total",
            ),
            _tile(
                "Pressure moments",
                str(flips.opportunities),
                note=f"{len(flips.resists)} resisted",
            ),
            _tile(
                "Agents / events",
                f"{report.n_agents} / {report.n_events}",
                note=_esc(", ".join(report.trace.agents[:4])),
            ),
            _tile("Output tokens", f"{cost.total_out:,}", note=tokens_note),
        ]
    )

    components = "".join(
        f"<tr><td>{_esc(name)}</td><td class='num'>{value:.3f}</td>"
        f"<td class='num'>{score.weights[name]:.2f}</td></tr>"
        for name, value in score.components.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cascade Guard report</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Cascade Guard &mdash; multi-agent reliability report</h1>
  <p class="sub">source: {_esc(report.trace.source or "(in-memory)")} &middot;
     run: {_esc(report.trace.run_id)} &middot; generated {_esc(report.generated_at)}</p>

  <div class="tiles">{tiles}</div>

  <h2>Score components</h2>
  <table><thead><tr><th>Component</th><th class="num">Value (0&ndash;1)</th>
  <th class="num">Weight</th></tr></thead><tbody>{components}</tbody></table>

  <h2>Sycophancy / flip findings</h2>
  {_flip_cards(report)}

  <h2>Error propagation</h2>
  {_propagation_section(report)}

  <h2>Output tokens per event</h2>
  {_token_bars(report)}

  <h2>Stance timeline</h2>
  {_timeline_table(report)}

  <footer>Generated by cascade-guard v{_esc(report.tool_version)} &middot;
  heuristic findings; review excerpts before acting on them.</footer>
</div>
</body>
</html>
"""
