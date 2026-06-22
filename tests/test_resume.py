import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.adapters.mock import MockAdapter
from manageroo.cli import main
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json


def _toml_array(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class CountingAdapter(MockAdapter):
    def __init__(
        self,
        *,
        crash_role: str | None = None,
        crash_exception: type[BaseException] = KeyboardInterrupt,
    ):
        self.crash_role = crash_role
        self.crash_exception = crash_exception
        self.calls: list[str] = []

    def run(self, request):
        self.calls.append(request.role)
        if request.role == self.crash_role:
            raise self.crash_exception(f"simulated controller kill during {request.role}")
        return super().run(request)


class ResumeTests(unittest.TestCase):
    def _fixture_repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Product\n", encoding="utf-8")
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
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text = text.replace("parallel_mapping = true", "parallel_mapping = false")
        text = text.replace("parallel_review = true", "parallel_review = false")
        text += (
            "\n[[verification.gates]]\n"
            'id = "fixture-check"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            f"argv = {_toml_array([sys.executable, '-m', 'unittest', 'discover'])}\n"
        )
        config.write_text(text, encoding="utf-8")
        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product request\n\nCreate the deterministic fixture file.\n", encoding="utf-8")
        return repo

    def test_resume_continues_saved_run_without_recalling_finished_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            first_adapter = CountingAdapter(crash_role="implementer")
            first = Orchestrator(repo, adapter=first_adapter)

            with self.assertRaises(KeyboardInterrupt):
                first.run(brief_path=brief, mode="build", apply_on_success=True)

            state = read_json(first.run_root / "state.json")
            self.assertEqual(state["phase"], "IMPLEMENTING")
            self.assertIn("product-analyst", first_adapter.calls)
            self.assertIn("plan-reviewer", first_adapter.calls)

            resume_adapter = CountingAdapter()
            resumed = Orchestrator(repo, run_id=first.run_id, adapter=resume_adapter, resume=True)
            result = resumed.run(brief_path=brief, mode="build", apply_on_success=True)

            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(
                (repo / "manageroo_fixture.txt").read_text(encoding="utf-8"),
                "MANAGEROO deterministic fixture completed\n",
            )
            self.assertNotIn("product-analyst", resume_adapter.calls)
            self.assertNotIn("reuse-researcher", resume_adapter.calls)
            self.assertNotIn("repository-mapper", resume_adapter.calls)
            self.assertNotIn("map-reducer", resume_adapter.calls)
            self.assertNotIn("plan-compiler", resume_adapter.calls)
            self.assertNotIn("plan-reviewer", resume_adapter.calls)
            self.assertIn("implementer", resume_adapter.calls)

    def test_cli_resume_reopens_blocked_run_from_saved_input(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            first_adapter = CountingAdapter(
                crash_role="implementer",
                crash_exception=RuntimeError,
            )
            first = Orchestrator(repo, adapter=first_adapter)

            with self.assertRaises(RuntimeError):
                first.run(brief_path=brief, mode="build", apply_on_success=True)

            state = read_json(first.run_root / "state.json")
            self.assertEqual(state["phase"], "BLOCKED")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["resume", first.run_id, "--repo", str(repo)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "COMPLETE")
            self.assertEqual(
                (repo / "manageroo_fixture.txt").read_text(encoding="utf-8"),
                "MANAGEROO deterministic fixture completed\n",
            )


if __name__ == "__main__":
    unittest.main()
