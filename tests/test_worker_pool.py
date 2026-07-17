import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.pool import WorkerPoolAdapter
from manageroo.errors import AgentExecutionError, SafetyError


class _Worker(AgentAdapter):
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def doctor(self, cwd: Path):
        return {"ok": self.error is None}

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response or AgentResponse(
            role=request.role,
            data={"ok": True},
            raw_text='{"ok": true}',
            command=["worker"],
        )


def _request(root: Path) -> AgentRequest:
    prompt = root / "prompt.md"
    schema = root / "schema.json"
    output = root / "output.json"
    prompt.write_text("job", encoding="utf-8")
    schema.write_text('{"type":"object"}', encoding="utf-8")
    return AgentRequest(
        role="worker",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=root,
        sandbox="workspace-write",
        timeout_seconds=60,
    )


class WorkerPoolTests(unittest.TestCase):
    def test_provider_failure_falls_back_to_next_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            first = _Worker(error=AgentExecutionError("provider unavailable"))
            second = _Worker()
            pool = WorkerPoolAdapter([("first", first), ("second", second)])
            response = pool.run(_request(Path(temp)))
            self.assertEqual(first.calls, 1)
            self.assertEqual(second.calls, 1)
            self.assertEqual(response.command[0], "worker:second")

    def test_safety_failure_is_never_swallowed_by_provider_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            first = _Worker(error=SafetyError("scope escape"))
            second = _Worker()
            pool = WorkerPoolAdapter([("first", first), ("second", second)])
            with self.assertRaises(SafetyError):
                pool.run(_request(Path(temp)))
            self.assertEqual(second.calls, 0)

    def test_empty_pool_reports_not_ready_and_fails_cleanly_on_run(self):
        with tempfile.TemporaryDirectory() as temp:
            pool = WorkerPoolAdapter([])
            doctor = pool.doctor(Path(temp))
            self.assertFalse(doctor["ok"])
            self.assertIn("No supported live coding-agent", doctor["error"])
            with self.assertRaisesRegex(AgentExecutionError, "no usable live coding worker"):
                pool.run(_request(Path(temp)))

    def test_worker_call_budget_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = _Worker()
            budgeted = BudgetedAdapter(worker, max_total_worker_calls=1)
            request = _request(Path(temp))
            budgeted.run(request)
            with self.assertRaisesRegex(AgentExecutionError, "budget exhausted"):
                budgeted.run(request)


if __name__ == "__main__":
    unittest.main()
