from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from .adapters.mock import MockAdapter
from .orchestrator import Orchestrator
from .project import initialize_project
from .runner import CommandRunner


def run_self_test() -> dict:
    with tempfile.TemporaryDirectory(prefix="manageroo-self-test-") as temp:
        repo = Path(temp) / "fixture"
        repo.mkdir()
        runner = CommandRunner()
        for argv in (
            ["git", "init", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Self Test"],
            ["git", "config", "user.email", "selftest@local.invalid"],
        ):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr)

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
        for argv in (["git", "add", "-A"], ["git", "commit", "-m", "fixture"]):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr)

        initialize_project(repo, agent="mock")
        config_path = repo / ".manageroo" / "config.toml"
        text = config_path.read_text(encoding="utf-8")
        if "[[verification.gates]]" not in text:
            text += (
                "\n[[verification.gates]]\n"
                'id = "fixture-check"\n'
                'kind = "test"\n'
                "required = true\n"
                "timeout_seconds = 60\n"
                "argv = ["
                + json.dumps(sys.executable)
                + ', "-m", "unittest", "discover"]\n'
            )
        else:
            text = text.replace('id = "unittest"', 'id = "fixture-check"')
        config_path.write_text(text, encoding="utf-8")

        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text(
            "# Product request\n\n"
            "Create `manageroo_fixture.txt` with the deterministic fixture text.\n",
            encoding="utf-8",
        )
        result = Orchestrator(repo, adapter=MockAdapter()).run(
            brief_path=brief,
            mode="build",
            apply_on_success=True,
        )
        target = repo / "manageroo_fixture.txt"
        return {
            "ok": result["status"] == "COMPLETE" and target.exists(),
            "status": result["status"],
            "run_id": result["run_id"],
            "target_exists": target.exists(),
            "target_contents": target.read_text(encoding="utf-8") if target.exists() else None,
        }
