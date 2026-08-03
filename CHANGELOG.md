# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `mypy` failed on a checkout without the optional `anthropic` package
  installed (as in CI, where only the `dev` extra is present). Optional
  integrations are now declared in the mypy config, so type-checking no longer
  requires installing every extra.
- The bundled YAML parser returned `{}` for a comments-only or empty policy
  file where PyYAML returns `None`, so the "policy file is empty" error was
  raised only when PyYAML happened to be installed.
- The bundled YAML parser left unquoted ISO dates as strings where PyYAML
  produces `datetime.date`. Both backends now yield identical objects.

### Added

- A parametrized test asserting the bundled YAML parser and PyYAML agree, so
  behavior no longer depends on which backend is present. It skips when PyYAML
  is absent, since cross-checking is the point.

## [0.2.0] - 2026-08-03

Production/enterprise release: runtime guarding, policy-as-code, baselines,
fleet reporting, and supply-chain hardening. The core remains dependency-free
and performs no network I/O.

### Added

- **Runtime guard** (`cascade_guard.runtime`): `CascadeGuard.observe()` /
  `observe_many()` / `observe_langgraph_update()` emit `Signal`s carrying a
  recommended `Intervention` (`require_evidence`, `inject_dissent`, `halt`,
  `warn`, `none`) with ready-to-inject prompt text. Signal kinds:
  `unsupported_flip`, `supported_flip`, `consensus_locked`, `risk_threshold`,
  `token_spike`. Guarantees: never mutates the run, swallows callback
  exceptions, O(1) per event, and false-positive controls via `min_agents`,
  `warmup_turns`, `max_interventions_per_agent`, and `observe_only`.
- **Policy-as-code** (`cascade_guard.policy`): `cascade-guard.yaml` with
  thresholds, runtime settings, baseline gates, and auditable suppressions
  (reason required, scope required, optional expiry). Auto-discovery walks up
  from the trace path. Includes a YAML-subset parser so no dependency is
  needed; defers to PyYAML when installed.
- **Baselines and drift detection** (`cascade_guard.baseline`): append-only
  JSONL history per pipeline with robust-z-score drift detection (median/MAD)
  and a `max_regression` gate.
- **Fleet dashboard** (`cascade-guard fleet`): static, self-contained multi-run
  index with per-pipeline trend sparklines; contains no trace content.
- **New CLI commands**: `guard`, `fleet`, `policy validate`, `policy show`;
  `analyze` gains `--policy`, `--no-policy`, `--pipeline`, `--baseline`,
  `--record-baseline`, `--check-baseline`, `--commit`; `demo` gains `--runtime`.
- **Supply-chain hardening**: Sigstore signing, CycloneDX SBOM, SLSA v1
  provenance, PEP 740 attestations on publish, tag/version agreement check, a
  CI job asserting the core install pulls no dependencies, and a bandit scan.
- **Enterprise deployment guide** at `docs/deployment.md`.
- `cascade_guard.ingest.langgraph.events_from_update()` — public helper shared
  by the file adapter and the runtime guard, so live and post-hoc analysis see
  identical events.

### Fixed

- The runtime guard ignored `halt_threshold` when it was set below
  `risk_threshold` (the default 60), so `--halt-threshold 10` never fired. The
  warn and halt thresholds are now tracked independently.

### Changed

- Adapter auto-detection order is now explicit via a `priority` class
  attribute rather than import order.

## [0.1.0] - 2026-08-03

### Added

- Normalized trace schema (`TraceEvent` / `Trace`) with schema versioning
- Trace adapters: LangGraph (`updates` dumps, message lists, `lc`-serialized
  messages) and generic JSON/JSONL with alias-key tolerance
- Deterministic sycophancy/flip detection with turn-of-flip, agreement/evidence
  cues, tool-result-as-evidence, and resistance tracking
- Error-propagation tracer (`--wrong-answer`): origin agent, downstream
  adopters, capitulations, infection rate
- Consensus-collapse (stance-entropy) and output-token spike analysis
- Cascade-risk score (0–100) with letter grade and renormalizing weights
- Console, self-contained HTML (light/dark), and JSON reports
- CLI: `analyze` (with `--fail-over` CI gate), `demo`, `formats`
- Optional Anthropic LLM judge (`--judge anthropic`, `judge` extra) that
  annotates findings without changing the deterministic score
- Labeled synthetic "gang-up" demo scenario and full pytest suite
