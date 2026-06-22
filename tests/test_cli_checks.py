import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from umsmfburasbofe.cli import main
from umsmfburasbofe.project import initialize_project


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

    def test_checks_suggest_reports_python_compile_fallback(self):
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
            self.assertEqual(payload["suggestions"][0]["id"], "python-compile")
            self.assertIn("checks add python-compile", payload["suggestions"][0]["add_command"])

    def test_checks_suggest_apply_first_writes_detected_gate(self):
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
            self.assertEqual(code, 0)
            self.assertEqual(payload["added"]["id"], "python-compile")
            config_text = (repo / ".umsmfburasbofe" / "config.toml").read_text(encoding="utf-8")
            self.assertIn('id = "python-compile"', config_text)
            self.assertIn('argv = ["python3", "-m", "compileall", "."]', config_text)


if __name__ == "__main__":
    unittest.main()
