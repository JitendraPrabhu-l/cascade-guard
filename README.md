# Cascade Guard

**Multi-agent reliability profiler.** Point it at your multi-agent trace logs
(LangGraph today; generic JSONL for everything else) and get a report on:

- **Sycophancy cascades** — where an agent silently flipped its position to match
  a wrong majority without any new evidence entering the run
- **Error propagation** — given a known-wrong final answer, which agent introduced
  it and how many downstream agents adopted it unchanged
- **False-consensus collapse** — how much stance diversity was lost between each
  agent's first and final position
- **Token blowups** — turns whose output-token usage spiked far above the run's median

The output is a single **cascade-risk score (0–100)** with a letter grade, a
self-contained HTML report, a JSON export, and a CI gate (`--fail-over`) so a
regressing pipeline fails the build.

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

Adapters for CrewAI, AutoGen, and OpenTelemetry GenAI spans are on the
[roadmap](ROADMAP.md); the generic format is the bridge until then.

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
- run: cascade-guard analyze artifacts/agent_trace.jsonl --fail-over 60 --json cascade.json
```

Exit codes: `0` ok, `1` usage/parse error, `2` cascade risk exceeded `--fail-over`.

## Design principles

- **Zero runtime dependencies.** The core is stdlib-only: nothing to audit,
  trivial to vendor, safe for locked-down environments.
- **Local-only by default.** No telemetry, no network calls unless you opt into
  the LLM judge.
- **Deterministic first.** Heuristics you can unit-test and reproduce; LLM
  judgment is an annotation layer, never the source of truth.
- **Framework-agnostic core.** Adapters normalize traces into one schema; the
  analyzers never know which framework produced them.

## Limitations (v0.1, honest edition)

- Stance extraction is regex-based; free-form debates without "the answer is X"
  style assertions produce fewer findings (use the `stance` field or the judge).
- English-language cue lists.
- One trace per invocation; no cross-run baselining yet (roadmap).

## Contributing & project docs

- [ROADMAP.md](ROADMAP.md) — v1.x and v2 (enterprise/runtime) scope
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, style, PR checklist
- [SECURITY.md](SECURITY.md) — vulnerability reporting
- [CHANGELOG.md](CHANGELOG.md)

Licensed under [Apache-2.0](LICENSE).
