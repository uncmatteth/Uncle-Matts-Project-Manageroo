import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.cli import main
from manageroo.project import initialize_project


class CliCheckTests(unittest.TestCase):
    def test_checks_add_accepts_repo_after_id_before_separator(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "checks",
                        "add",
                        "--json",
                        "smoke",
                        "--repo",
                        str(repo),
                        "--",
                        "python3",
                        "-m",
                        "unittest",
                        "discover",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["id"], "smoke")
            self.assertEqual(payload["argv"], ["python3", "-m", "unittest", "discover"])

    def test_checks_suggest_reports_no_compile_only_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["checks", "suggest", str(repo), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["suggestions"], [])
            self.assertIn("behavior test or demonstration", payload["note"])

    def test_checks_suggest_apply_first_refuses_compile_only_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
            initialize_project(repo, agent="mock")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["checks", "suggest", str(repo), "--apply-first", "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertNotEqual(code, 0)
            self.assertFalse(payload["ok"])
            config_text = (repo / ".manageroo" / "config.toml").read_text(encoding="utf-8")
            self.assertNotIn('id = "python-compile"', config_text)


if __name__ == "__main__":
    unittest.main()
