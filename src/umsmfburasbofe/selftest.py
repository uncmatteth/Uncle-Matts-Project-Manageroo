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
    with tempfile.TemporaryDirectory(prefix="umsmfburasbofe-self-test-") as temp:
        repo = Path(temp) / "fixture"
        repo.mkdir()
        runner = CommandRunner()
        for argv in (
            ["git", "init", "-b", "main"],
            ["git", "config", "user.name", "UMSMFBURASBOFE Self Test"],
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
            "        self.assertEqual(Path('umsmfburasbofe_fixture.txt').read_text(), "
            "'UMSMFBURASBOFE deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        for argv in (["git", "add", "-A"], ["git", "commit", "-m", "fixture"]):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr)

        initialize_project(repo, agent="mock")
        config_path = repo / ".umsmfburasbofe" / "config.toml"
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

        brief = repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md"
        brief.write_text(
            "# Product request\n\n"
            "Create `umsmfburasbofe_fixture.txt` with the deterministic fixture text.\n",
            encoding="utf-8",
        )
        result = Orchestrator(repo, adapter=MockAdapter()).run(
            brief_path=brief,
            mode="build",
            apply_on_success=True,
        )
        target = repo / "umsmfburasbofe_fixture.txt"
        return {
            "ok": result["status"] == "COMPLETE" and target.exists(),
            "status": result["status"],
            "run_id": result["run_id"],
            "target_exists": target.exists(),
            "target_contents": target.read_text(encoding="utf-8") if target.exists() else None,
        }
