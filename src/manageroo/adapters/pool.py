from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, ConfigurationError, ValidationError


class WorkerPoolAdapter(AgentAdapter):
    """Try interchangeable coding-agent workers without changing controller truth.

    The controller owns the request, schema, workspace, scope, and completion rules.
    Provider fallback is limited to execution/protocol failures. Safety failures raised
    by the controller are intentionally not swallowed here.
    """

    def __init__(self, workers: Iterable[tuple[str, AgentAdapter]]):
        self.workers = list(workers)
        self.last_successful_worker = ""

    def doctor(self, cwd: Path) -> dict:
        checks = []
        for name, adapter in self.workers:
            try:
                result = adapter.doctor(cwd)
            except Exception as exc:
                result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
            checks.append({"name": name, **result})
        return {
            "ok": any(item.get("ok") for item in checks),
            "adapter": "worker-pool",
            "preferred_worker": self.last_successful_worker,
            "workers": checks,
            "error": "" if checks else "No supported live coding-agent executable was found on PATH.",
        }

    def _ordered_workers(self) -> list[tuple[str, AgentAdapter]]:
        if not self.last_successful_worker:
            return list(self.workers)
        preferred = [item for item in self.workers if item[0] == self.last_successful_worker]
        others = [item for item in self.workers if item[0] != self.last_successful_worker]
        return [*preferred, *others]

    def run(self, request: AgentRequest) -> AgentResponse:
        if not self.workers:
            raise AgentExecutionError(
                "Manageroo has no usable live coding worker. Install or configure Codex, "
                "Claude Code, Gemini, or another compatible agent preset."
            )
        failures: list[str] = []
        retryable = (AgentExecutionError, ConfigurationError, ValidationError)
        for name, adapter in self._ordered_workers():
            try:
                response = adapter.run(request)
                self.last_successful_worker = name
                response.command = [f"worker:{name}", *response.command]
                return response
            except retryable as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        raise AgentExecutionError(
            "All configured live workers failed this bounded Manageroo job:\n" + "\n".join(failures)
        )
