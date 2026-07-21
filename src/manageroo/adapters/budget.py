from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, SafetyError
from ..util import atomic_write_json, read_json, utc_now


class BudgetedAdapter(AgentAdapter):
    """Enforce controller-owned worker-call and elapsed-runtime budgets.

    Worker-call usage can be persisted under the durable run controller directory.
    The counter is consumed before each concrete worker launch so a killed process cannot
    erase an attempt. Worker pools install this adapter's reservation hook and therefore
    consume one budget unit for every provider process they actually try.
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
        self._lock = threading.RLock()
        self.calls = self._load_calls()
        self._pool_manages_reservations = hasattr(inner, "set_before_worker_launch")
        if self._pool_manages_reservations:
            inner.set_before_worker_launch(self._reserve_and_bound)  # type: ignore[attr-defined]

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
        with self._lock:
            calls = self.calls
        result["budget"] = {
            "max_total_worker_calls": self.max_total_worker_calls,
            "worker_calls_consumed": calls,
            "worker_calls_remaining": (
                max(0, self.max_total_worker_calls - calls)
                if self.max_total_worker_calls
                else None
            ),
            "max_runtime_minutes": self.max_runtime_seconds / 60.0,
            "durable_call_ledger": str(self.state_path) if self.state_path else "",
            "counts_concrete_pool_launches": True,
        }
        return result

    def _remaining_runtime_seconds(self) -> float | None:
        if not self.max_runtime_seconds:
            return None
        return self.max_runtime_seconds - (time.monotonic() - self.started_at)

    def _reserve_call(self) -> float | None:
        with self._lock:
            if self.max_total_worker_calls and self.calls >= self.max_total_worker_calls:
                raise AgentExecutionError(
                    f"Manageroo worker-call budget exhausted at {self.calls} calls."
                )
            remaining = self._remaining_runtime_seconds()
            if remaining is not None and remaining <= 0:
                raise AgentExecutionError(
                    "Manageroo runtime budget exhausted before launching another worker."
                )
            self.calls += 1
            self._persist()
            return remaining

    def _reserve_and_bound(self, request: AgentRequest) -> AgentRequest:
        remaining = self._reserve_call()
        if remaining is None:
            return request
        return replace(
            request,
            timeout_seconds=max(1, min(request.timeout_seconds, int(remaining))),
        )

    def run(self, request: AgentRequest) -> AgentResponse:
        if self._pool_manages_reservations:
            return self.inner.run(request)
        return self.inner.run(self._reserve_and_bound(request))