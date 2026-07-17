from __future__ import annotations

import time
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError


class BudgetedAdapter(AgentAdapter):
    """Enforce controller-owned worker-call and elapsed-runtime budgets."""

    def __init__(
        self,
        inner: AgentAdapter,
        *,
        max_total_worker_calls: int = 0,
        max_runtime_minutes: float = 0,
    ):
        self.inner = inner
        self.max_total_worker_calls = max(0, int(max_total_worker_calls))
        self.max_runtime_seconds = max(0.0, float(max_runtime_minutes) * 60.0)
        self.started_at = time.monotonic()
        self.calls = 0

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["budget"] = {
            "max_total_worker_calls": self.max_total_worker_calls,
            "max_runtime_minutes": self.max_runtime_seconds / 60.0,
        }
        return result

    def _check_budget(self) -> None:
        if self.max_total_worker_calls and self.calls >= self.max_total_worker_calls:
            raise AgentExecutionError(
                f"Manageroo worker-call budget exhausted at {self.calls} calls."
            )
        elapsed = time.monotonic() - self.started_at
        if self.max_runtime_seconds and elapsed >= self.max_runtime_seconds:
            raise AgentExecutionError(
                "Manageroo runtime budget exhausted before launching another worker."
            )

    def run(self, request: AgentRequest) -> AgentResponse:
        self._check_budget()
        self.calls += 1
        return self.inner.run(request)
