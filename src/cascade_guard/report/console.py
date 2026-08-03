"""Plain-text report for terminals and CI logs."""

from __future__ import annotations

from cascade_guard.analyze import AnalysisReport

_RULE = "-" * 72


def render_text(report: AnalysisReport) -> str:
    lines: list[str] = []
    add = lines.append

    add(_RULE)
    add(f"Cascade Guard report  |  source: {report.trace.source or '(in-memory)'}")
    add(_RULE)
    add(f"Cascade risk: {report.score.cascade_risk:.1f}/100  (grade {report.score.grade})")
    for name, value in report.score.components.items():
        weight = report.score.weights[name]
        add(f"  - {name:<18} {value:.3f}  (weight {weight:.2f})")
    add("")
    add(
        f"Agents: {report.n_agents} ({', '.join(report.trace.agents)})  |  "
        f"Events: {report.n_events}"
    )

    flips = report.flips
    add(
        f"Conformity pressure moments: {flips.opportunities}  |  "
        f"flips: {len(flips.flips)} ({len(flips.unsupported_flips)} unsupported)  |  "
        f"resists: {len(flips.resists)}"
    )
    add("")

    if flips.flips:
        add("Flip findings:")
        for f in flips.flips:
            kind = "evidence-based" if f.evidence_based else "UNSUPPORTED"
            add(
                f"  [turn {f.event.turn}] {f.agent}: '{f.from_stance}' -> "
                f"'{f.to_stance}' toward majority of {f.majority_size} "
                f"({kind}, severity {f.severity}, held {f.turns_held} turn(s))"
            )
            if f.agreement_cues:
                add(f"      agreement cues: {', '.join(f.agreement_cues)}")
            if f.judge:
                verdict = f.judge
                add(
                    f"      judge[{verdict['model']}]: sycophantic="
                    f"{verdict['is_sycophantic']} "
                    f"(confidence {verdict['confidence']}): {verdict['rationale']}"
                )
    else:
        add("Flip findings: none")
    add("")

    prop = report.propagation
    if prop is not None:
        if prop.origin is not None:
            add(
                f"Error propagation ('{prop.wrong_stance}'): introduced by "
                f"{prop.origin_agent} at turn {prop.origin.turn}; adopted by "
                f"{len(prop.adopters)}/{max(prop.total_agents - 1, 0)} downstream "
                f"agent(s) ({', '.join(prop.adopter_agents) or 'none'}) — "
                f"infection rate {prop.infection_rate:.0%}"
            )
            if prop.capitulated_agents:
                add(
                    "  capitulated after initially disagreeing: "
                    + ", ".join(prop.capitulated_agents)
                )
        else:
            add(
                f"Error propagation: wrong answer '{prop.wrong_stance}' was never "
                "asserted in this trace"
            )
        add("")

    cost = report.cost
    if cost.has_token_data:
        add(
            f"Tokens: in {cost.total_in:,}  out {cost.total_out:,}  "
            f"(median out/turn: {cost.median_out:.0f})"
        )
        if cost.spikes:
            for spike in cost.spikes:
                add(
                    f"  token spike: turn {spike.turn} ({spike.agent}) produced "
                    f"{spike.tokens_out:,} output tokens"
                )
        else:
            add("  no output-token spikes detected")
    else:
        add("Tokens: no token metadata in this trace")
    add(_RULE)
    return "\n".join(lines)
