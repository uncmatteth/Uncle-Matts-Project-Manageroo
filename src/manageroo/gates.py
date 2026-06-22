from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .errors import GateFailure
from .policy import CommandPolicy
from .runner import CommandResult, CommandRunner


@dataclass(frozen=True)
class Gate:
    id: str
    kind: str
    argv: list[str]
    required: bool = True
    timeout_seconds: int = 1800


@dataclass
class GateRun:
    gate: Gate
    result: CommandResult

    def to_dict(self) -> dict:
        return {"gate": asdict(self.gate), "result": self.result.to_dict()}


def gates_from_config(config: dict) -> list[Gate]:
    return [
        Gate(
            id=item["id"],
            kind=item.get("kind", "check"),
            argv=list(item["argv"]),
            required=bool(item.get("required", True)),
            timeout_seconds=int(item.get("timeout_seconds", 1800)),
        )
        for item in config.get("verification", {}).get("gates", [])
    ]


class GateRunner:
    def __init__(self, runner: CommandRunner, policy: CommandPolicy, log_root: Path):
        self.runner = runner
        self.policy = policy
        self.log_root = log_root

    def run(self, gates: Iterable[Gate], cwd: Path, *, require_one: bool = True) -> list[GateRun]:
        selected = list(gates)
        if require_one and not selected:
            raise GateFailure(
                "No deterministic verification gates are configured. "
                "MANAGEROO will not claim completion without at least one real check."
            )
        outcomes: list[GateRun] = []
        failures: list[str] = []
        for gate in selected:
            self.policy.validate(gate.argv)
            result = self.runner.run(
                gate.argv,
                cwd=cwd,
                timeout_seconds=gate.timeout_seconds,
                log_name=f"gate-{gate.id}",
            )
            outcomes.append(GateRun(gate, result))
            if gate.required and not result.passed:
                failures.append(gate.id)
        if failures:
            raise GateFailure("Required gates failed: " + ", ".join(failures))
        return outcomes
