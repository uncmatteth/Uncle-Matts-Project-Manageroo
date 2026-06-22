import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.mock import MockAdapter
from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.cli import main, parser
from manageroo.errors import AgentExecutionError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class OrchestratorJobCliTests(unittest.TestCase):
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
        (repo / "test_fixture.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('manageroo_fixture.txt').read_text(), "
            "'MANAGEROO deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text += (
            "\n[[verification.gates]]\n"
            'id = "fixture-check"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            f"argv = {_toml_array([sys.executable, '-m', 'unittest', 'discover'])}\n"
        )
        config.write_text(text, encoding="utf-8")
        (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
            "# Product request\n\nCreate the fixture file.\n",
            encoding="utf-8",
        )
        return repo

    def test_mock_run_creates_job_records_and_status_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            run_root = Path(result["evidence_paths"]["run_root"])
            self.assertTrue((run_root / "controller" / "truth.json").is_file())
            self.assertTrue((run_root / "controller" / "phase-journal.jsonl").is_file())
            self.assertTrue(list((run_root / "jobs").glob("*.json")))
            self.assertTrue(list((run_root / "worker-attempts").glob("*/*.json")))

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["status", result["run_id"], "--repo", str(repo)])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "COMPLETE")
            self.assertGreater(payload["jobs"]["completed_jobs"], 0)
            self.assertEqual(payload["jobs"]["failed_attempts"], 0)

    def test_run_continue_uses_continue_id_without_resume_command(self):
        help_stdout = io.StringIO()
        with redirect_stdout(help_stdout), self.assertRaises(SystemExit):
            parser().parse_args(["run", "--help"])
        commands = help_stdout.getvalue()
        self.assertIn("--continue", commands)
        self.assertNotIn("resume", commands.lower())

        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            calls: dict[str, object] = {}

            class FakeOrchestrator:
                def __init__(self, repo, *, run_id=None, continue_existing=False):
                    self.repo = repo
                    self.run_id = run_id
                    self.continuing = continue_existing
                    self.run_root = Path(repo) / ".manageroo" / "runs" / str(run_id)

                def run(self, *, brief_path, mode, apply_on_success=None):
                    calls["run_id"] = self.run_id
                    calls["continuing"] = self.continuing
                    return {
                        "run_id": self.run_id,
                        "status": "COMPLETE",
                        "evidence_paths": {"run_root": str(self.run_root)},
                    }

            with patch("manageroo.cli.Orchestrator", FakeOrchestrator):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main([
                        "run",
                        "--repo",
                        str(repo),
                        "--continue",
                        "manageroo-existing-run",
                    ])

            self.assertEqual(code, 0)
            self.assertEqual(calls["run_id"], "manageroo-existing-run")
            self.assertTrue(calls["continuing"])

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                parser().parse_args(["resume"])

    def test_continue_completed_run_returns_saved_result(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("completed run should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(continued["run_id"], result["run_id"])
            self.assertEqual(continued["status"], "COMPLETE")

    def test_continue_blocked_worker_run_retries_from_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_worker_attempts = 2",
                    "max_worker_attempts = 1",
                ),
                encoding="utf-8",
            )

            class FailingProductAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        raise AgentExecutionError("simulated dead disposable worker")
                    return super().run(request)

            failed = Orchestrator(repo, adapter=FailingProductAdapter())
            with self.assertRaises(AgentExecutionError):
                failed.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )
            run_id = failed.run_id
            failed_attempts = list(
                (repo / ".manageroo" / "runs" / run_id / "worker-attempts").glob("*/*.json")
            )
            self.assertEqual(len(failed_attempts), 1)

            result = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=run_id,
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            product_attempts = sorted(
                (repo / ".manageroo" / "runs" / run_id / "worker-attempts" / "001-product-analyst").glob("*.json")
            )
            self.assertEqual([path.stem for path in product_attempts], ["001", "002"])


if __name__ == "__main__":
    unittest.main()
