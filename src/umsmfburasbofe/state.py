from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from .errors import StateTransitionError
from .util import atomic_write_json, read_json, utc_now


class Phase(str, Enum):
    CREATED = "CREATED"
    INTAKE = "INTAKE"
    DISCOVERY = "DISCOVERY"
    DECISIONS = "DECISIONS"
    REUSE_RESEARCH = "REUSE_RESEARCH"
    SYSTEM_MAPPING = "SYSTEM_MAPPING"
    PLAN_COMPILE = "PLAN_COMPILE"
    PLAN_REVIEW = "PLAN_REVIEW"
    CONTRACT_LOCKED = "CONTRACT_LOCKED"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    REPAIRING = "REPAIRING"
    DEMONSTRATING = "DEMONSTRATING"
    DELIVERING = "DELIVERING"
    WAITING_FOR_PRODUCT_DECISION = "WAITING_FOR_PRODUCT_DECISION"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


_ALLOWED: dict[Phase, set[Phase]] = {
    Phase.CREATED: {Phase.INTAKE, Phase.BLOCKED},
    Phase.INTAKE: {Phase.DISCOVERY, Phase.BLOCKED},
    Phase.DISCOVERY: {Phase.DECISIONS, Phase.BLOCKED},
    Phase.DECISIONS: {
        Phase.REUSE_RESEARCH,
        Phase.WAITING_FOR_PRODUCT_DECISION,
        Phase.BLOCKED,
    },
    Phase.WAITING_FOR_PRODUCT_DECISION: {Phase.DECISIONS, Phase.BLOCKED},
    Phase.REUSE_RESEARCH: {Phase.SYSTEM_MAPPING, Phase.BLOCKED},
    Phase.SYSTEM_MAPPING: {Phase.PLAN_COMPILE, Phase.BLOCKED},
    Phase.PLAN_COMPILE: {Phase.PLAN_REVIEW, Phase.BLOCKED},
    Phase.PLAN_REVIEW: {Phase.PLAN_COMPILE, Phase.CONTRACT_LOCKED, Phase.BLOCKED},
    Phase.CONTRACT_LOCKED: {Phase.IMPLEMENTING, Phase.BLOCKED},
    Phase.IMPLEMENTING: {Phase.VERIFYING, Phase.BLOCKED},
    Phase.VERIFYING: {Phase.REVIEWING, Phase.REPAIRING, Phase.BLOCKED},
    Phase.REVIEWING: {Phase.REPAIRING, Phase.DEMONSTRATING, Phase.BLOCKED},
    Phase.REPAIRING: {Phase.VERIFYING, Phase.BLOCKED},
    Phase.DEMONSTRATING: {Phase.REPAIRING, Phase.DELIVERING, Phase.BLOCKED},
    Phase.DELIVERING: {Phase.COMPLETE, Phase.BLOCKED},
    Phase.BLOCKED: set(),
    Phase.COMPLETE: set(),
}


@dataclass
class StateEvent:
    phase: str
    at: str
    reason: str


@dataclass
class RunState:
    run_id: str
    phase: str = Phase.CREATED.value
    history: list[StateEvent] = field(default_factory=list)
    repair_cycles: int = 0
    plan_review_cycles: int = 0

    @classmethod
    def create(cls, run_id: str) -> "RunState":
        state = cls(run_id=run_id)
        state.history.append(StateEvent(Phase.CREATED.value, utc_now(), "Run created"))
        return state

    @classmethod
    def load(cls, path: Path) -> "RunState":
        raw = read_json(path)
        return cls(
            run_id=raw["run_id"],
            phase=raw["phase"],
            history=[StateEvent(**event) for event in raw.get("history", [])],
            repair_cycles=int(raw.get("repair_cycles", 0)),
            plan_review_cycles=int(raw.get("plan_review_cycles", 0)),
        )

    def save(self, path: Path) -> None:
        atomic_write_json(path, asdict(self))

    def transition(self, next_phase: Phase, reason: str) -> None:
        current = Phase(self.phase)
        if next_phase not in _ALLOWED[current]:
            raise StateTransitionError(f"Invalid transition {current.value} -> {next_phase.value}")
        self.phase = next_phase.value
        self.history.append(StateEvent(next_phase.value, utc_now(), reason))
