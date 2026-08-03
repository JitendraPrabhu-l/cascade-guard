# Enterprise deployment guide

Cascade Guard is designed to be boring to deploy: the core has **zero runtime
dependencies**, performs **no network I/O**, and emits **no telemetry**. This
guide covers the questions that come up in a security or platform review.

## Table of contents

- [Install modes](#install-modes)
- [Air-gapped installs](#air-gapped-installs)
- [Network egress](#network-egress)
- [Data handling and retention](#data-handling-and-retention)
- [Runtime guard in production](#runtime-guard-in-production)
- [CI integration](#ci-integration)
- [Supply-chain verification](#supply-chain-verification)
- [Upgrade policy](#upgrade-policy)

## Install modes

| Mode | Command | Pulls |
|---|---|---|
| Core (recommended) | `pip install cascade-guard` | nothing but the package itself |
| With LLM judge | `pip install "cascade-guard[judge]"` | `anthropic` |
| Development | `pip install "cascade-guard[dev]"` | pytest, ruff, mypy |

The core install is verified dependency-free by a dedicated CI job on every
commit, so a locked-down environment can vendor a single wheel.

**Policy files** are YAML. PyYAML is *not* required — the package ships a
small YAML-subset parser covering everything a policy file needs. If PyYAML is
already present in your environment, Cascade Guard uses it automatically.

## Air-gapped installs

```bash
# On a connected machine:
pip download cascade-guard --no-deps -d ./wheels

# Transfer ./wheels, then on the air-gapped host:
pip install --no-index --find-links ./wheels cascade-guard
```

Nothing else is needed. There is no model download, no first-run setup step,
and no license check. Verify with:

```bash
cascade-guard demo --dir /tmp/cg-demo --runtime
```

If that prints a report and a runtime replay, the install is complete.

## Network egress

| Component | Makes network calls? |
|---|---|
| Trace ingestion, analysis, scoring | **No** |
| Console / HTML / JSON reports | **No** (reports embed all assets) |
| Runtime guard | **No** |
| Baselines, policy, fleet dashboard | **No** (local files only) |
| `--judge anthropic` | **Yes** — `api.anthropic.com` |

Only the optional judge egresses. Behind a proxy:

```bash
export HTTPS_PROXY=http://proxy.internal:3128
export ANTHROPIC_API_KEY=...        # or use `ant auth login`
cascade-guard analyze trace.jsonl --judge anthropic
```

To guarantee no egress anywhere in a pipeline, simply do not pass `--judge`;
there is no ambient/background mode that could call out.

## Data handling and retention

**Traces are sensitive.** Agent logs routinely contain user prompts, retrieved
documents, tool outputs, and occasionally credentials. Treat Cascade Guard's
inputs and outputs at the same classification as the traces themselves.

What each artifact contains:

| Artifact | Contains trace content? | Notes |
|---|---|---|
| HTML report | **Yes** — excerpts up to 400 chars per finding | escape-tested; self-contained |
| JSON report | **Yes** — excerpts up to 280 chars per finding | |
| Baseline store (`.jsonl`) | **No** — scores and counts only | plus the trace *path* and run id |
| Fleet dashboard | **No** — aggregates from the baseline store | safe to publish more widely |
| Guard signal log | **Yes** — stance strings and messages | |

Practical consequences:

- The **baseline store is safe to commit to git**; reports generally are not.
- The **fleet dashboard is the artifact to share broadly** — it carries scores
  and trends, never prompt text.
- If you must publish a report, review the excerpts first, or run without
  `--out`/`--json` and rely on exit codes plus the baseline entry.

Cascade Guard writes only where you tell it to: `--out`, `--json`,
`--baseline`, and the `demo` directory. It never writes to a home directory,
temp cache, or hidden state location on its own.

## Runtime guard in production

The guard is designed to be safe to leave on:

- **It never mutates your run.** `observe()` returns recommendations; acting on
  them is your harness's decision.
- **A broken callback cannot break the run.** Exceptions raised by an
  `on_signal` handler are captured, never propagated.
- **Cost is O(1) per event** — state is a few dicts keyed by agent, and a CI
  test asserts per-event cost stays flat as run length grows (typically tens of
  microseconds per event).

Recommended rollout:

1. **Week 1 — observe only.** `observe_only: true` in policy. Log signals;
   change nothing. Establish what your normal rate of findings looks like.
2. **Week 2 — soft interventions.** Turn off `observe_only` but leave
   `halt_threshold` unset. The guard will recommend `require_evidence` and
   `inject_dissent`; wire those prompts into your harness.
3. **Week 3+ — hard gates.** Set `halt_threshold` for pipelines where a false
   consensus is expensive, and tune `min_agents` / `warmup_turns` /
   `max_interventions_per_agent` against the baseline you gathered.

```python
from cascade_guard import CascadeGuard, InterventionKind

guard = CascadeGuard(observe_only=True, on_signal=log_signal)

for update in graph.stream(inputs, stream_mode="updates"):
    for signal in guard.observe_langgraph_update(update):
        if signal.intervention.kind is InterventionKind.HALT:
            raise RunHalted(signal.message)
        if signal.intervention.prompt:
            inject(signal.intervention.target_agent, signal.intervention.prompt)
```

## CI integration

```yaml
- run: pip install cascade-guard
- run: |
    cascade-guard analyze artifacts/trace.jsonl \
      --policy cascade-guard.yaml \
      --baseline .cascade-guard/baseline.jsonl \
      --record-baseline --check-baseline \
      --commit "$GITHUB_SHA" \
      --json cascade.json
```

Exit codes: `0` pass, `1` usage/parse error, `2` a gate failed (threshold,
policy rule, or baseline regression). Commit the updated baseline store from
your default branch only, so feature branches compare against trunk rather
than each other.

## Supply-chain verification

Every tagged release publishes:

- **Wheel and sdist** via PyPI Trusted Publishing (OIDC — no long-lived token
  exists to be stolen), with PEP 740 attestations
- **Sigstore signatures** (`.sigstore` bundles) attached to the GitHub release
- **SLSA v1 build provenance** attesting how the artifacts were built
- **A CycloneDX SBOM** (`sbom.cdx.json`)

Verify a downloaded wheel:

```bash
python -m pip install sigstore
python -m sigstore verify identity \
  --cert-identity-regexp 'https://github.com/.*/cascade-guard/.*' \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  cascade_guard-*.whl
```

The release workflow also fails the build if the git tag and
`__version__` disagree, so a mislabeled release cannot ship.

## Upgrade policy

The project follows SemVer. Within a major version:

- The **trace schema** carries `SCHEMA_VERSION`; readers tolerate unknown
  fields, so a newer producer will not break an older consumer.
- **Baseline records** ignore unknown fields for the same reason — a store
  written by a newer version stays readable.
- **Policy files** carry an explicit `version:` and are rejected with a clear
  error rather than silently misinterpreted if the schema moves on.
- **Signal kinds** are stable lowercase strings, safe to reference in
  suppression rules and alerting.

Scoring weights are the one thing that can shift a number without a schema
change; those changes are called out in the CHANGELOG with before/after scores
on the bundled fixtures.
