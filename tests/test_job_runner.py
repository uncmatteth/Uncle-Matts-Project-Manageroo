import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.context import ContextRequest
from manageroo.errors import AgentExecutionError, ContextBudgetError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import atomic_write_json, read_json


class FlakyAgent(AgentAdapter):
    def __init__(self):
        self.calls = 0
        self.prompt_paths: list[Path] = []

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        self.prompt_paths.append(request.prompt_path)
        if self.calls == 1:
            raise AgentExecutionError("invalid JSON from disposable worker")
        data = {
            "status": "implemented",
            "summary": "done",
            "files_changed": [],
            "commands_run": [],
            "risks": [],
            "scope_expansion_requested": [],
        }
        atomic_write_json(request.output_path, data)
        return AgentResponse(role=request.role, data=data, raw_text="", command=["flaky"])


class ExplodingAgent(AgentAdapter):
    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        raise AssertionError("completed job should have been loaded from disk")


class JobRunnerTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        return repo

    def test_failed_worker_attempt_gets_fresh_packet_and_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            agent = FlakyAgent()
            orch = Orchestrator(repo, adapter=agent)
            orch.workspace = orch.mirror.create()

            data = orch._call(
                role="implementer",
                schema="agent-result.schema.json",
                instructions="Implement the bounded task.",
                context=[ContextRequest("README.md", "fixture", required=True)],
                call_name="001-implementer",
            )

            self.assertEqual(data["status"], "implemented")
            self.assertEqual(agent.calls, 2)
            self.assertEqual([path.name for path in agent.prompt_paths], ["prompt.md", "prompt.md"])
            self.assertNotEqual(agent.prompt_paths[0].parent, agent.prompt_paths[1].parent)
            summary = orch.job_store.status_summary()
            self.assertEqual(summary["completed_jobs"], 1)
            self.assertEqual(summary["failed_attempts"], 1)

    def test_completed_job_is_loaded_without_calling_agent_again(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            agent = FlakyAgent()
            orch = Orchestrator(repo, adapter=agent)
            orch.workspace = orch.mirror.create()
            first = orch._call(
                role="implementer",
                schema="agent-result.schema.json",
                instructions="Implement the bounded task.",
                call_name="001-implementer",
            )

            orch.adapter = ExplodingAgent()
            second = orch._call(
                role="implementer",
                schema="agent-result.schema.json",
                instructions="Implement the bounded task.",
                call_name="001-implementer",
            )

            self.assertEqual(first, second)
            self.assertEqual(read_json(orch.run_root / "jobs" / "001-implementer.json")["status"], "complete")

    def test_required_context_overflow_records_blocked_job(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            (repo / "big.txt").write_text("x" * 1000, encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "big"], cwd=repo, check=True)
            orch = Orchestrator(repo, adapter=FlakyAgent())
            orch.config["context"]["max_input_tokens"] = 40
            orch.config["context"]["reserve_output_tokens"] = 10
            orch.config["context"]["max_single_file_tokens"] = 20
            orch.config["context"]["chars_per_token"] = 1.0
            orch.workspace = orch.mirror.create()

            with self.assertRaises(ContextBudgetError):
                orch._call(
                    role="implementer",
                    schema="agent-result.schema.json",
                    instructions="Implement.",
                    context=[ContextRequest("big.txt", "required", required=True)],
                    call_name="001-implementer",
                )

            job = orch.job_store.load_job("001-implementer")
            self.assertEqual(job.status, "blocked")
            self.assertEqual(orch.job_store.status_summary()["blocked_jobs"], 1)


if __name__ == "__main__":
    unittest.main()
