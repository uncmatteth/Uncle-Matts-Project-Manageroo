import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from umsmfburasbofe.cli import main
from umsmfburasbofe.project import initialize_project


class CliMemoryTests(unittest.TestCase):
    def test_memory_show_and_add_use_project_memory_file(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("# Test Product\n\nA useful thing.\n", encoding="utf-8")
            initialize_project(repo, agent="mock")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "memory",
                        "add",
                        str(repo),
                        "--shipped",
                        "Static homepage starter shipped",
                        "--must-not",
                        "Do not remove the smoke test",
                        "--proof",
                        "python3 -m unittest discover",
                        "--note",
                        "Operator wants plain English",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"], payload)
            memory = Path(payload["path"])
            text = memory.read_text(encoding="utf-8")
            self.assertIn("Static homepage starter shipped", text)
            self.assertIn("Do not remove the smoke test", text)
            self.assertIn("python3 -m unittest discover", text)
            self.assertIn("Operator wants plain English", text)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["memory", "show", str(repo)])
            self.assertEqual(code, 0)
            self.assertIn("PROJECT MEMORY", stdout.getvalue())
            self.assertIn("Static homepage starter shipped", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
