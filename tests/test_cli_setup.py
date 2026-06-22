import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.cli import main


class CliSetupTests(unittest.TestCase):
    def test_setup_text_output_ends_with_one_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            env = {
                "MANAGEROO_TOKEN_MODE_FILE": str(Path(temp) / "token-mode.json"),
                "MANAGEROO_SKILLS_DIR": str(Path(temp) / "skills"),
            }
            stdout = io.StringIO()
            with patch.dict(os.environ, env), patch(
                "sys.stdin.isatty",
                return_value=False,
            ), patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[
                    {
                        "name": "helper:test",
                        "ok": True,
                        "detail": "mock",
                        "next": "",
                        "required": True,
                    }
                ],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main(["setup", str(repo), "--agent", "mock", "--skip-skills"])
            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertEqual(output.count("\nNext:"), 1, output)


if __name__ == "__main__":
    unittest.main()
