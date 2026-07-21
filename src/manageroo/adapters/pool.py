from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Iterable

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
        self._lock = threading.RLock()
        self._before_worker_launch: Callable[[AgentRequest], AgentRequest] | None = None
        self._hook_managed_workers: set[str] = set()

    @staticmethod
    def _install_worker_hook(
        adapter: Any,
        callback: Callable[[AgentRequest], AgentRequest],
        seen: set[int] | None = None,
    ) -> bool:
        seen = seen or set()
        identity = id(adapter)
        if identity in seen:
            return False
        seen.add(identity)
        setter = getattr(adapter, "set_before_worker_launch", None)
        if callable(setter):
            setter(callback)
            return True
        nested = getattr(adapter, "inner", None)
        if nested is not None:
            return WorkerPoolAdapter._install_worker_hook(nested, callback, seen)
        return False

    def set_before_worker_launch(self, callback: Callable[[AgentRequest], AgentRequest]) -> None:
        """Reserve once per actual provider process, including provider-internal retries."""
        self._before_worker_launch = callback
        managed: set[str] = set()
        for name, adapter in self.workers:
            if self._install_worker_hook(adapter, callback):
                managed.add(name)
        self._hook_managed_workers = managed

    def doctor(self, cwd: Path) -> dict:
        checks = []
        for name, adapter in self.workers:
            try:
                result = adapter.doctor(cwd)
            except Exception as exc:
                result = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
            checks.append({"name": name, **result})
        with self._lock:
            preferred = self.last_successful_worker
        return {
            "ok": any(item.get("ok") for item in checks),
            "adapter": "worker-pool",
            "preferred_worker": preferred,
            "workers": checks,
            "error": "" if checks else "No supported live coding-agent executable was found on PATH.",
        }

    def _ordered_workers(self) -> list[tuple[str, AgentAdapter]]:
        with self._lock:
            preferred_name = self.last_successful_worker
        if not preferred_name:
            return list(self.workers)
        preferred = [item for item in self.workers if item[0] == preferred_name]
        others = [item for item in self.workers if item[0] != preferred_name]
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
            # Concrete-hook-aware workers reserve inside the provider immediately before
            # each process. Generic workers have no such hook, so reserve once here.
            bounded_request = request
            if self._before_worker_launch is not None and name not in self._hook_managed_workers:
                bounded_request = self._before_worker_launch(request)
            try:
                response = adapter.run(bounded_request)
                with self._lock:
                    self.last_successful_worker = name
                response.command = [f"worker:{name}", *response.command]
                return response
            except retryable as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        raise AgentExecutionError(
            "All configured live workers failed this bounded Manageroo job:\n" + "\n".join(failures)
        )
