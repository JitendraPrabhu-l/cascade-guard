# Cascade Guard

**Multi-agent reliability profiler and runtime guard.** Point it at your
multi-agent trace logs (LangGraph today; generic JSONL for everything else) and
get a report on:

- **Sycophancy cascades** — where an agent silently flipped its position to match
  a wrong majority without any new evidence entering the run
- **Error propagation** — given a known-wrong final answer, which agent introduced
  it and how many downstream agents adopted it unchanged
- **False-consensus collapse** — how much stance diversity was lost between each
  agent's first and final position
- **Token blowups** — turns whose output-token usage spiked far above the run's median

The output is a single **cascade-risk score (0–100)** with a letter grade, a
self-contained HTML report, a JSON export, and a CI gate so a regressing
pipeline fails the build.

Beyond post-hoc analysis, Cascade Guard also runs **during** a live run
([runtime guard](#runtime-guard)), enforces **policy-as-code**
([`cascade-guard.yaml`](#policy-as-code)), tracks **baselines and drift**
([regression detection](#baselines-and-drift-detection)), and rolls many runs
into a **fleet dashboard**.

Multi-agent evaluation is a widely acknowledged unsolved problem, and the
tendency of agents to agree with a majority even when it is wrong is one of its
nastiest failure modes: a run can be *confidently incorrect* because the agents
reinforced each other's errors. Academic work (SYCON-Bench's "turn of flip"
metric, cascade-detection research) is paper-and-benchmark shaped; Cascade Guard
is the drop-in tool shape — point it at a trace, get findings in an afternoon.

## Install

```bash
pip install cascade-guard              # zero runtime dependencies (stdlib only)
pip install "cascade-guard[judge]"     # + optional Anthropic LLM judge
```

Requires Python 3.10+.

## Quickstart

```bash
# See it work on a labeled synthetic scenario
# (three agents debate; two gang up on the one that is right, and it folds):
cascade-guard demo --dir demo_output
# -> demo_output/demo_gangup.jsonl, demo_report.html, demo_report.json

# Analyze your own trace
cascade-guard analyze trace.jsonl --out report.html --json report.json

# You know the final answer was wrong? Trace who introduced it:
cascade-guard analyze trace.jsonl --wrong-answer "blue" --out report.html

# Gate a CI pipeline on cascade risk (exit code 2 on breach):
cascade-guard analyze trace.jsonl --fail-over 60

# Watch a cascade form turn by turn, as the runtime guard would see it live:
cascade-guard guard trace.jsonl --halt-threshold 80
```

Or from Python:

```python
from cascade_guard import load_trace, analyze_trace

trace = load_trace("trace.jsonl")            # auto-detects the format
report = analyze_trace(trace, wrong_answer="blue")
print(report.score.cascade_risk, report.score.grade)
for flip in report.flips.unsupported_flips:
    print(flip.agent, flip.from_stance, "->", flip.to_stance)
```

## Runtime guard

The profiler tells you a run went wrong. The **runtime guard** tells you a run
*is* going wrong, while the agents are still talking — so you can intervene
before a false consensus locks in.

```python
from cascade_guard import CascadeGuard, InterventionKind

guard = CascadeGuard(halt_threshold=85)

for update in graph.stream(inputs, stream_mode="updates"):
    for signal in guard.observe_langgraph_update(update):
        print(signal.message)                      # what it saw
        if signal.intervention.kind is InterventionKind.HALT:
            raise RunHalted(signal.message)
        if signal.intervention.prompt:             # ready-to-inject text
            inject(signal.intervention.target_agent, signal.intervention.prompt)
```

On the bundled demo, the guard catches the cascade at the exact turn the
profiler flags:

```
! [turn 6] unsupported_flip (risk 22): alice adopted the majority position
    'blue' (held by 2 peers) without new evidence, after holding 'green' for 2 turns
    -> require_evidence for alice
! [turn 6] consensus_locked (risk 44): all 3 agents now hold 'blue' after
    1 unsupported flip — this consensus may be false
    -> inject_dissent for the crew
```

Signals carry a `kind` (`unsupported_flip`, `consensus_locked`,
`risk_threshold`, `token_spike`, `supported_flip`), a severity, the cumulative
risk, and a recommended `Intervention` (`require_evidence`, `inject_dissent`,
`halt`, `warn`, or `none`).

**Safety properties**, because this runs in your hot path:

- **It never mutates your run** — `observe()` returns recommendations; acting is
  your call. Start with `observe_only=True`.
- **A broken callback cannot break the run** — exceptions from `on_signal` are
  captured, never propagated.
- **O(1) per event** — no history rescans; a CI test asserts per-event cost
  stays flat as runs grow (tens of microseconds/event in practice).
- **False-positive controls** — `min_agents` (no majority to conform to below
  three), `warmup_turns` (early position-finding is not capitulation),
  `max_interventions_per_agent` (rate limiting), and per-kind deduplication.

## Policy-as-code

Check a `cascade-guard.yaml` in next to the pipeline it governs and review it
like any other config. It is auto-discovered by walking up from the trace path.

```yaml
version: 1
pipeline: research-crew

thresholds:
  fail_over: 60              # CI fails above this cascade risk
  warn_over: 40
  max_unsupported_flips: 0

runtime:                     # feeds the runtime guard
  risk_threshold: 55
  halt_threshold: 85
  observe_only: false

baseline:
  enabled: true
  max_regression: 10         # fail if risk rises this much over the baseline

suppressions:
  - agent: flaky-summarizer
    kind: unsupported_flip
    reason: "known verbose restatement, tracked in ENG-4821"
    expires: 2026-12-31
```

Suppressions **must carry a reason**, must be scoped to an agent or kind (a
catch-all would hide everything), and may carry an expiry — an expired
suppression stops suppressing *and* is reported, so stale exceptions surface
instead of silently accumulating.

```bash
cascade-guard policy validate          # check syntax + report expired rules
cascade-guard policy show              # print the effective policy as JSON
cascade-guard analyze trace.jsonl      # policy auto-discovered and enforced
```

YAML support needs no dependency: the package ships a small YAML-subset parser
covering everything a policy file uses, and defers to PyYAML when it happens to
be installed.

## Baselines and drift detection

A fixed threshold answers "is this run bad?". A baseline answers "is this run
worse than this pipeline *usually* is?" — which is what catches a prompt change
quietly making a crew more sycophantic while still under the absolute limit.

```bash
cascade-guard analyze trace.jsonl --record-baseline --check-baseline \
  --pipeline research-crew --commit "$GITHUB_SHA"
```

History is an append-only JSONL file (diffs cleanly in git, no database). Drift
uses a **robust z-score** built on the median and median absolute deviation, not
mean/stddev — cascade scores are skewed, and a couple of genuinely bad historical
runs would otherwise inflate the spread and mask a real regression. Drift is only
reported once there are at least 5 runs; below that it says so rather than
guessing.

The baseline store holds **scores and counts only — no prompt text**, so it is
safe to commit.

## Fleet dashboard

```bash
cascade-guard fleet --baseline .cascade-guard/baseline.jsonl --out fleet.html
```

A static, self-contained page: per-pipeline latest risk, median, delta,
unsupported-flip count, and a trend sparkline over the last 20 runs. No server,
no database, no network — publish it as a CI artifact. Because it aggregates
from the baseline store, it contains no trace content and is safe to share more
widely than a run report.

## Trace formats

### LangGraph (`--format langgraph`)

Dump a LangGraph run to JSONL and point Cascade Guard at it:

```python
import json

with open("trace.jsonl", "w") as f:
    for update in graph.stream(inputs, stream_mode="updates"):
        f.write(json.dumps(update, default=lambda o: o.dict()) + "\n")
```

Both plain LangChain message dicts and `lc`-serialized (`dumpd`) messages are
understood; node names become agent names unless a message carries its own.

### Generic JSONL (`--format generic`)

One JSON object per line; only `agent` and `content` are required. Common alias
keys (`name`, `text`, `output`, `output_tokens`, ...) are accepted:

```json
{"agent": "planner", "role": "assistant", "content": "The answer is 42.",
 "tokens_in": 300, "tokens_out": 45, "turn": 0}
```

Optional fields: `turn`, `run_id`, `event_id`, `role` (`assistant`/`user`/`tool`),
`timestamp`, `tokens_in`, `tokens_out`, `stance` (explicit stance label),
`evidence` (list of references), `metadata` (object).

Adapters for CrewAI, AutoGen, and OpenTelemetry GenAI spans are planned;
the generic format is the bridge until then.

## How detection works

1. **Stance extraction** (deterministic heuristics): each agent event is scanned
   for an asserted position — "the answer is X", "final answer: X", option
   letters, yes/no — normalized for comparison. Frameworks that already label
   stances can pass them explicitly via the `stance` field.
2. **Flip detection**: an event is a *flip* when the agent previously held a
   different stance, the other agents' latest stances formed a differing
   majority, and the agent adopted that majority. A flip is **unsupported** when
   no new evidence entered the run (no evidence cues in the message, no explicit
   `evidence` refs, no tool result since the agent's prior stance). The
   *turns-held* count — how long the agent resisted before folding — adapts
   SYCON-Bench's "turn of flip" metric to agent-to-agent traces.
3. **Propagation tracing** (`--wrong-answer`): finds the earliest assertion of
   the wrong answer, then every downstream agent that repeated it — including
   agents that first disagreed and then capitulated.
4. **Scoring**: weighted blend of unsupported-flip rate (weighted by
   capitulation speed), consensus-entropy collapse, and infection rate,
   rescaled to 0–100. Weights renormalize over the components computable for
   the given trace, so a trace without ground truth is still scored.

Everything above is deterministic and reproducible offline. The **LLM judge**
is strictly optional (`--judge anthropic`): it second-opinions each flip finding
with one small Anthropic API call (default model `claude-haiku-4-5`) and attaches
the verdict as metadata — it never changes the heuristic score.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cascade-guard analyze trace.jsonl --judge anthropic --out report.html
```

## CI usage

```yaml
# GitHub Actions example
- run: pip install cascade-guard
- run: |
    cascade-guard analyze artifacts/agent_trace.jsonl \
      --policy cascade-guard.yaml \
      --baseline .cascade-guard/baseline.jsonl \
      --record-baseline --check-baseline \
      --commit "$GITHUB_SHA" --json cascade.json
```

Exit codes: `0` pass, `1` usage/parse error, `2` a gate failed — a threshold, a
policy rule, or a baseline regression.

## Command reference

| Command | Purpose |
|---|---|
| `analyze` | Profile a trace; enforce policy, thresholds, and baselines |
| `guard` | Replay a trace through the runtime guard, showing live signals |
| `fleet` | Render the multi-run dashboard from the baseline store |
| `policy validate` / `show` | Check a policy file; print the effective config |
| `demo [--runtime]` | Generate and analyze the labeled gang-up scenario |
| `formats` | List supported trace formats |

## Design principles

- **Zero runtime dependencies.** The core is stdlib-only: nothing to audit,
  trivial to vendor, safe for locked-down environments. A CI job asserts this
  on every commit.
- **Local-only by default.** No telemetry, no network calls unless you opt into
  the LLM judge. Nothing is written outside the paths you specify.
- **Deterministic first.** Heuristics you can unit-test and reproduce; LLM
  judgment is an annotation layer, never the source of truth.
- **Framework-agnostic core.** Adapters normalize traces into one schema; the
  analyzers never know which framework produced them.
- **Advisory, never coercive.** The runtime guard recommends; your harness
  decides. It cannot mutate a run or crash one via a callback.

## Limitations (honest edition)

- Stance extraction is regex-based; free-form debates without "the answer is X"
  style assertions produce fewer findings (use the `stance` field or the judge).
- English-language cue lists.
- The runtime guard sees only what you feed it — if your harness batches events,
  detection is only as timely as the batch.
- Drift detection needs ≥5 historical runs per pipeline before it reports.

## Contributing & project docs

- [docs/deployment.md](docs/deployment.md) — air-gapped installs, egress, data
  handling, rollout, supply-chain verification
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, style, PR checklist
- [SECURITY.md](SECURITY.md) — vulnerability reporting
- [CHANGELOG.md](CHANGELOG.md)

Licensed under [Apache-2.0](LICENSE).
