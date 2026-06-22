import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.checks import add_check_gate
from umsmfburasbofe.cli import main
from umsmfburasbofe.project import initialize_project


class CliNextTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        return repo

    def test_uninitialized_git_repo_points_to_solo_front_door(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            stdout = io.StringIO()
            with patch(
                "umsmfburasbofe.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main(["next", str(repo)])
            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("NEXT ACTION", output)
            self.assertIn("Stage: needs-setup", output)
            self.assertEqual(output.count("\nCommand:"), 1, output)
            self.assertIn(f"umsmfburasbofe solo {repo}", output)
            self.assertIn('--want "Describe the first useful version"', output)

    def test_initialized_repo_without_checks_points_to_checks_suggest(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            initialize_project(repo, agent="mock")
            (repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nBuild the useful thing.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with patch(
                "umsmfburasbofe.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main(["next", str(repo)])
            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Stage: needs-checks", output)
            self.assertIn("umsmfburasbofe checks suggest --apply-first", output)

    def test_ready_repo_json_points_to_run_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            initialize_project(repo, agent="mock")
            (repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nRepair the login flow.\n",
                encoding="utf-8",
            )
            add_check_gate(
                repo,
                gate_id="smoke",
                argv=["python3", "-m", "compileall", "."],
            )
            stdout = io.StringIO()
            with patch(
                "umsmfburasbofe.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main(["next", str(repo), "--mode", "repair", "--no-apply", "--json"])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["stage"], "ready-to-run")
            self.assertEqual(
                payload["command"],
                f"umsmfburasbofe run --repo {repo} --mode repair --no-apply",
            )


if __name__ == "__main__":
    unittest.main()
