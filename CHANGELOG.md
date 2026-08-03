# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
