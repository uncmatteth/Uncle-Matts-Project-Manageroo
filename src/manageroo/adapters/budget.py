from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, SafetyError
from ..util import atomic_write_json, read_json, utc_now


class BudgetedAdapter(AgentAdapter):
    """Enforce controller-owned worker-call and elapsed-runtime budgets.

    Worker-call usage can be persisted under the durable run controller directory.
    The counter is consumed before launch so a killed process cannot erase an attempt.
    Elapsed-runtime accounting remains local to the current process.
    """

    def __init__(
        self,
        inner: AgentAdapter,
        *,
        max_total_worker_calls: int = 0,
        max_runtime_minutes: float = 0,
        state_path: Path | None = None,
    ):
        self.inner = inner
        self.max_total_worker_calls = max(0, int(max_total_worker_calls))
        self.max_runtime_seconds = max(0.0, float(max_runtime_minutes) * 60.0)
        self.started_at = time.monotonic()
        self.state_path = state_path
        self.calls = self._load_calls()

    def _load_calls(self) -> int:
        if self.state_path is None or not self.state_path.is_file():
            return 0
        try:
            payload = read_json(self.state_path)
            return max(0, int(payload.get("worker_calls_consumed", 0)))
        except Exception as exc:
            raise SafetyError(
                f"Manageroo budget ledger is unreadable: {self.state_path}: {exc}"
            ) from exc

    def _persist(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.state_path,
            {
                "worker_calls_consumed": self.calls,
                "max_total_worker_calls": self.max_total_worker_calls,
                "updated_at": utc_now(),
            },
        )

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["budget"] = {
            "max_total_worker_calls": self.max_total_worker_calls,
            "worker_calls_consumed": self.calls,
            "worker_calls_remaining": (
                max(0, self.max_total_worker_calls - self.calls)
                if self.max_total_worker_calls
                else None
            ),
            "max_runtime_minutes": self.max_runtime_seconds / 60.0,
            "durable_call_ledger": str(self.state_path) if self.state_path else "",
        }
        return result

    def _remaining_runtime_seconds(self) -> float | None:
        if not self.max_runtime_seconds:
            return None
        return self.max_runtime_seconds - (time.monotonic() - self.started_at)

    def _check_budget(self) -> float | None:
        if self.max_total_worker_calls and self.calls >= self.max_total_worker_calls:
            raise AgentExecutionError(
                f"Manageroo worker-call budget exhausted at {self.calls} calls."
            )
        remaining = self._remaining_runtime_seconds()
        if remaining is not None and remaining <= 0:
            raise AgentExecutionError(
                "Manageroo runtime budget exhausted before launching another worker."
            )
        return remaining

    def run(self, request: AgentRequest) -> AgentResponse:
        remaining = self._check_budget()
        self.calls += 1
        self._persist()
        bounded_request = request
        if remaining is not None:
            bounded_request = replace(
                request,
                timeout_seconds=max(1, min(request.timeout_seconds, int(remaining))),
            )
        return self.inner.run(bounded_request)
