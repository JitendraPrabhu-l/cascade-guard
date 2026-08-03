"""Signals the guard emits and the interventions it recommends.

Cascade Guard never mutates a caller's run. It emits a :class:`Signal`
describing what it saw and a recommended :class:`Intervention`; acting on it
is the harness's decision. This keeps the guard safe to enable in production
(observe-only by default) and keeps the blocking decision where the operator
can reason about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from cascade_guard.schema import TraceEvent


class SignalKind(str, Enum):
    """What the guard detected."""

    #: An agent adopted the majority position with no new evidence.
    UNSUPPORTED_FLIP = "unsupported_flip"
    #: An agent flipped, but new evidence had entered the run (informational).
    SUPPORTED_FLIP = "supported_flip"
    #: Every agent now holds the same stance after at least one unsupported
    #: flip — the false consensus has closed.
    CONSENSUS_LOCKED = "consensus_locked"
    #: Cumulative cascade risk crossed the configured threshold.
    RISK_THRESHOLD = "risk_threshold"
    #: A single turn produced far more output tokens than the run's norm.
    TOKEN_SPIKE = "token_spike"


class InterventionKind(str, Enum):
    """What the harness is advised to do about it."""

    #: Record it; keep going. Used for informational signals.
    NONE = "none"
    #: Surface the finding to an operator/log, but do not alter the run.
    WARN = "warn"
    #: Ask the flipping agent to justify the change with evidence.
    REQUIRE_EVIDENCE = "require_evidence"
    #: Inject a devil's-advocate prompt to reopen the collapsed debate.
    INJECT_DISSENT = "inject_dissent"
    #: Stop the run; a human should look before it continues.
    HALT = "halt"


#: Default prompts the harness can feed back into its agents. Operators can
#: override these per policy — see cascade_guard.policy.
DEFAULT_PROMPTS: dict[InterventionKind, str] = {
    InterventionKind.REQUIRE_EVIDENCE: (
        "You just changed your position to match the other agents. Before we "
        "continue, state the specific new evidence that changed your mind. If "
        "there is none, restore your previous position and explain your "
        "reasoning."
    ),
    InterventionKind.INJECT_DISSENT: (
        "All agents now agree. Before this conclusion is accepted, argue the "
        "strongest case AGAINST it. Identify what evidence would have to be "
        "true for the current consensus to be wrong, and check whether that "
        "evidence exists."
    ),
}


@dataclass(frozen=True)
class Intervention:
    """A recommended action, ready to hand back to the agent harness."""

    kind: InterventionKind
    #: Prompt text to inject, when the intervention calls for one.
    prompt: str | None = None
    #: Which agent the intervention is aimed at, when it is agent-specific.
    target_agent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "prompt": self.prompt,
            "target_agent": self.target_agent,
        }


@dataclass(frozen=True)
class Signal:
    """One detection emitted by the runtime guard."""

    kind: SignalKind
    severity: str  # "high" | "medium" | "low" | "info"
    message: str
    event: TraceEvent
    #: Cumulative cascade risk (0-100) at the moment of detection.
    risk: float
    intervention: Intervention
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def actionable(self) -> bool:
        """True when the guard recommends doing something beyond logging."""
        return self.intervention.kind not in (InterventionKind.NONE, InterventionKind.WARN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity,
            "message": self.message,
            "turn": self.event.turn,
            "agent": self.event.agent,
            "risk": round(self.risk, 1),
            "intervention": self.intervention.to_dict(),
            "details": self.details,
        }
