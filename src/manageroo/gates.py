from __future__ import annotations

import hashlib
import os
import shutil
import stat
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

    @staticmethod
    def _checkout_identity(root: Path) -> dict[str, tuple[str, int]]:
        identity: dict[str, tuple[str, int]] = {}
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] == ".git":
                continue
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if stat.S_ISLNK(metadata.st_mode):
                payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            elif stat.S_ISREG(metadata.st_mode):
                payload = path.read_bytes()
            else:
                payload = b""
            identity[relative.as_posix()] = (
                hashlib.sha256(payload).hexdigest(),
                stat.S_IMODE(metadata.st_mode),
            )
        return identity

    def _run_disposable(self, gate: Gate, source: Path, scratch_root: Path) -> GateRun:
        if gate.timeout_seconds <= 0:
            raise GateFailure(f"Gate {gate.id} timeout_seconds must be greater than zero.")
        scratch_root.mkdir(parents=True, exist_ok=True)
        destination = scratch_root / gate.id
        suffix = 0
        while destination.exists() or destination.is_symlink():
            suffix += 1
            destination = scratch_root / f"{gate.id}-{suffix}"
        clone = self.runner.run(
            ["git", "clone", "--no-hardlinks", "--quiet", str(source), str(destination)],
            cwd=scratch_root,
            timeout_seconds=300,
        )
        if not clone.passed:
            raise GateFailure(
                f"Gate {gate.id} could not create its disposable checkout: "
                + (clone.stderr or "git clone failed")
            )
        try:
            before_tree = self._checkout_identity(destination)
            before_head = self.runner.run(
                ["git", "rev-parse", "HEAD"], cwd=destination, timeout_seconds=60
            )
            if not before_head.passed:
                raise GateFailure(f"Gate {gate.id} checkout has no readable Git HEAD.")
            self.policy.validate(gate.argv)
            result = self.runner.run(
                gate.argv,
                cwd=destination,
                timeout_seconds=gate.timeout_seconds,
                log_name=f"gate-{gate.id}",
                env={
                    # Python's default bytecode cache is a gate side effect,
                    # not product evidence. Prevent it so ordinary test gates
                    # remain genuinely read-only.
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            after_head = self.runner.run(
                ["git", "rev-parse", "HEAD"], cwd=destination, timeout_seconds=60
            )
            after_tree = self._checkout_identity(destination)
            if (
                not after_head.passed
                or after_head.stdout.strip() != before_head.stdout.strip()
                or after_tree != before_tree
            ):
                changed = sorted(
                    path
                    for path in set(before_tree) | set(after_tree)
                    if before_tree.get(path) != after_tree.get(path)
                )
                detail = ", ".join(changed[:20]) or "Git metadata/HEAD"
                raise GateFailure(
                    f"Gate {gate.id} mutated its disposable checkout: {detail}. "
                    "Verification commands must be read-only."
                )
            return GateRun(gate, result)
        finally:
            shutil.rmtree(destination, ignore_errors=True)

    def run(
        self,
        gates: Iterable[Gate],
        cwd: Path,
        *,
        scratch_root: Path,
        require_one: bool = True,
    ) -> list[GateRun]:
        selected = list(gates)
        if require_one and not selected:
            raise GateFailure(
                "No deterministic verification gates are configured. "
                "MANAGEROO will not claim completion without at least one real check."
            )
        outcomes: list[GateRun] = []
        failures: list[str] = []
        for gate in selected:
            outcome = self._run_disposable(gate, cwd, scratch_root)
            outcomes.append(outcome)
            if gate.required and not outcome.result.passed:
                failures.append(gate.id)
        if failures:
            raise GateFailure("Required gates failed: " + ", ".join(failures))
        return outcomes
