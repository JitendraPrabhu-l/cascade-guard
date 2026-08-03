# Contributing to Cascade Guard

Thanks for considering a contribution! This project aims to stay small,
deterministic, and dependency-free at the core — please keep that in mind when
proposing features.

## Development setup

```bash
git clone https://github.com/jitendraprabhu/cascade-guard
cd cascade-guard
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Checks (run before pushing)

```bash
ruff check src tests
ruff format --check src tests
mypy
pytest
```

CI runs the same commands on Linux and Windows across Python 3.10–3.13.

## Ground rules

- **No new runtime dependencies in the core.** Optional integrations go behind
  extras (like the `judge` extra) with lazy imports and a clear error message.
- **Heuristic changes need labeled fixtures.** If you tune stance extraction or
  flip detection, add or update a test trace demonstrating the case — the demo
  gang-up scenario is the reference example of a labeled fixture.
- **Determinism is a feature.** Analyzers must produce identical output for
  identical input; no network, no clock-dependence (report timestamps aside).
- **New adapters** subclass `TraceAdapter`, register via `name`, implement
  `sniff` + `load`, and come with fixture files exercising real-world shapes.

## Pull requests

1. One logical change per PR; include tests and a CHANGELOG entry under
   `[Unreleased]`.
2. Keep public API additions documented in the README.
3. PRs that change scoring weights or thresholds should explain the rationale
   and show before/after scores on the bundled fixtures.

## Reporting bugs

Open an issue with: your trace format (a minimal redacted sample if possible),
the command you ran, expected vs. actual findings, and `cascade-guard --version`.
Never attach traces containing secrets or personal data — see SECURITY.md.
