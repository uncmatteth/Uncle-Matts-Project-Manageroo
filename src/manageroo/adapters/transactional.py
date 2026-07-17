from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import SafetyError
from ..runner import CommandRunner
from ..util import atomic_write_json, utc_now


class TransactionalAdapter(AgentAdapter):
    """Rollback failed attempts and forbid successful read-only mutation.

    Successful write-worker edits remain available for Manageroo's controller-owned
    scope, gate, review, and checkpoint logic. A worker that crashes, violates the
    output protocol, or mutates a read-only repository cannot poison later work.
    """

    def __init__(self, inner: AgentAdapter, runner: CommandRunner):
        self.inner = inner
        self.runner = runner

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["transactional_attempts"] = True
        result["read_only_mutation_enforced"] = True
        return result

    def _head(self, cwd: Path) -> str:
        result = self.runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise SafetyError(
                "Manageroo could not capture the worker-attempt Git checkpoint: "
                + result.stderr
            )
        return result.stdout.strip()

    def _dirty(self, cwd: Path) -> bool:
        result = self.runner.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise SafetyError(
                "Manageroo could not verify worker-attempt repository state: " + result.stderr
            )
        return bool(result.stdout.strip())

    def _rollback(self, cwd: Path, head: str) -> None:
        reset = self.runner.run(
            ["git", "reset", "--hard", head],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not reset.passed:
            raise SafetyError(
                "Failed worker attempt could not be rolled back safely: " + reset.stderr
            )
        clean = self.runner.run(
            ["git", "clean", "-fd"],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not clean.passed:
            raise SafetyError(
                "Failed worker attempt left untracked repository files that could not be removed: "
                + clean.stderr
            )

    def _discard_failed_outputs(self, request: AgentRequest) -> None:
        candidates = [
            request.output_path,
            request.output_path.with_suffix(".validated.json"),
        ]
        for path in candidates:
            try:
                if path.is_file():
                    path.unlink()
            except OSError as exc:
                raise SafetyError(
                    f"Failed worker output could not be discarded safely: {path}: {exc}"
                ) from exc

    def _rollback_failed_attempt(self, request: AgentRequest, head: str) -> None:
        self._rollback(request.cwd, head)
        self._discard_failed_outputs(request)

    def _pending_validation_marker(self, request: AgentRequest) -> Path | None:
        output_parent = request.output_path.parent
        agent_output_root = output_parent.parent
        if agent_output_root.name != "agent-output":
            return None
        return agent_output_root.parent / "controller" / "pending-workspace-validation.json"

    def _mark_pending_write_validation(self, request: AgentRequest, head: str) -> None:
        marker = self._pending_validation_marker(request)
        if marker is None:
            return
        atomic_write_json(
            marker,
            {
                "job_id": request.output_path.parent.name,
                "role": request.role,
                "sandbox": request.sandbox,
                "pre_attempt_head": head,
                "output_path": str(request.output_path),
                "created_at": utc_now(),
            },
        )

    def run(self, request: AgentRequest) -> AgentResponse:
        head = self._head(request.cwd)
        try:
            response = self.inner.run(request)
        except Exception:
            self._rollback_failed_attempt(request, head)
            raise

        if request.sandbox == "read-only":
            try:
                dirty = self._dirty(request.cwd)
            except SafetyError:
                self._rollback_failed_attempt(request, head)
                raise
            if dirty:
                self._rollback_failed_attempt(request, head)
                raise SafetyError(
                    f"Read-only worker {request.role!r} mutated its repository; edits were discarded."
                )
        elif request.sandbox == "workspace-write":
            self._mark_pending_write_validation(request, head)
        return response
