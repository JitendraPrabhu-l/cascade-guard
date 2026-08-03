"""Runtime guard mode: incremental cascade detection during a live run.

The batch profiler (:mod:`cascade_guard.analyze`) answers "did this run go
wrong?" after the fact. The runtime guard answers "is this run going wrong
right now?" while the agents are still talking, so a harness can intervene
before a false consensus locks in.

The guard reuses the same stance/flip primitives as the batch analyzer, so a
run that the guard flags is a run the profiler would also flag.
"""

from __future__ import annotations

from cascade_guard.runtime.guard import CascadeGuard, GuardState
from cascade_guard.runtime.interventions import (
    Intervention,
    InterventionKind,
    Signal,
    SignalKind,
)

__all__ = [
    "CascadeGuard",
    "GuardState",
    "Intervention",
    "InterventionKind",
    "Signal",
    "SignalKind",
]
