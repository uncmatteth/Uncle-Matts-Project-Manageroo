from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError
from ..runner import CommandRunner


class TransactionalAdapter(AgentAdapter):
    """Rollback unverified repository edits when a worker attempt fails.

    Successful worker edits remain available for Manageroo's controller-owned scope,
    gate, review, and checkpoint logic. A worker that crashes or violates the output
    protocol cannot poison the next provider or retry with leftover filesystem state.
    """

    def __init__(self, inner: AgentAdapter, runner: CommandRunner):
        self.inner = inner
        self.runner = runner

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["transactional_attempts"] = True
        return result

    def _head(self, cwd: Path) -> str:
        result = self.runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise AgentExecutionError(
                "Manageroo could not capture the worker-attempt Git checkpoint: "
                + result.stderr
            )
        return result.stdout.strip()

    def _rollback(self, cwd: Path, head: str) -> None:
        reset = self.runner.run(
            ["git", "reset", "--hard", head],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not reset.passed:
            raise AgentExecutionError(
                "Failed worker attempt could not be rolled back safely: " + reset.stderr
            )
        clean = self.runner.run(
            ["git", "clean", "-fd"],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not clean.passed:
            raise AgentExecutionError(
                "Failed worker attempt left untracked repository files that could not be removed: "
                + clean.stderr
            )

    def run(self, request: AgentRequest) -> AgentResponse:
        head = self._head(request.cwd)
        try:
            return self.inner.run(request)
        except Exception:
            self._rollback(request.cwd, head)
            raise
