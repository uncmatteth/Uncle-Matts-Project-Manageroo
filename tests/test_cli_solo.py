import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.cli import main


class CliSoloTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        return repo

    def test_solo_writes_brief_and_prints_one_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            env = {
                "UMSMFBURASBOFE_TOKEN_MODE_FILE": str(Path(temp) / "token-mode.json"),
                "UMSMFBURASBOFE_SKILLS_DIR": str(Path(temp) / "skills"),
            }
            stdout = io.StringIO()
            with patch.dict(os.environ, env), patch(
                "umsmfburasbofe.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main(
                    [
                        "solo",
                        str(repo),
                        "--agent",
                        "mock",
                        "--want",
                        "Make checkout sane",
                        "--outcome",
                        "One clear payment path",
                        "--must-not",
                        "Do not change exports",
                        "--proof",
                        "Run checkout tests",
                        "--skip-skills",
                        "--force",
                    ]
                )
            output = stdout.getvalue()
            brief = repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md"
            self.assertEqual(code, 0)
            self.assertIn("SOLO OPERATOR MODE", output)
            self.assertEqual(output.count("\nNext:"), 1, output)
            self.assertIn("Make checkout sane", brief.read_text(encoding="utf-8"))
            self.assertIn("One clear payment path", brief.read_text(encoding="utf-8"))
            memory = repo / ".umsmfburasbofe" / "PROJECT-MEMORY.md"
            memory_text = memory.read_text(encoding="utf-8")
            self.assertIn("Make checkout sane", memory_text)
            self.assertIn("Do not change exports", memory_text)
            self.assertIn("Run checkout tests", memory_text)
            intent = repo / ".umsmfburasbofe" / "intent" / "INTENT-LOCK.json"
            intent_payload = json.loads(intent.read_text(encoding="utf-8"))
            self.assertEqual(intent_payload["want"], "Make checkout sane")
            self.assertIn("One clear payment path", intent_payload["outcomes"])
            self.assertIn("Do not change exports", intent_payload["must_not"])
            self.assertIn("Run checkout tests", intent_payload["proof"])

    def test_solo_json_reports_run_command_when_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            ready = {
                "ok": True,
                "status": "READY TO RUN",
                "repo": str(repo),
                "items": [{"name": "target repo", "ok": True, "detail": str(repo), "required": True}],
                "next_commands": [],
            }
            stdout = io.StringIO()
            with patch(
                "umsmfburasbofe.cli.readiness",
                return_value=ready,
            ), redirect_stdout(stdout):
                code = main(
                    [
                        "solo",
                        str(repo),
                        "--agent",
                        "mock",
                        "--want",
                        "Repair login",
                        "--mode",
                        "repair",
                        "--json",
                        "--force",
                        "--no-apply",
                        "--skip-skills",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["next_command"], "umsmfburasbofe run --mode repair --no-apply")

    def test_solo_selected_extra_gets_visible_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            ready = {
                "ok": True,
                "status": "READY TO RUN",
                "repo": str(repo),
                "items": [{"name": "target repo", "ok": True, "detail": str(repo), "required": True}],
                "next_commands": [],
            }
            stdout = io.StringIO()

            def which(name):
                return "/usr/bin/npx" if name == "npx" else None

            with patch("umsmfburasbofe.cli.readiness", return_value=ready), patch(
                "umsmfburasbofe.cli.shutil.which",
                side_effect=which,
            ), redirect_stdout(stdout):
                code = main(
                    [
                        "solo",
                        str(repo),
                        "--agent",
                        "mock",
                        "--want",
                        "Build a tiny launch checklist",
                        "--use-loop-library",
                        "--json",
                        "--force",
                        "--skip-skills",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["integration_guidance"][0]["name"], "loop-library")
            self.assertIn("npx --yes skills add Forward-Future/loop-library", payload["next_command"])

    def test_solo_create_initializes_missing_project_before_brief(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "fresh-product"
            env = {
                "UMSMFBURASBOFE_TOKEN_MODE_FILE": str(Path(temp) / "token-mode.json"),
                "UMSMFBURASBOFE_SKILLS_DIR": str(Path(temp) / "skills"),
            }
            stdout = io.StringIO()
            with patch.dict(os.environ, env), redirect_stdout(stdout):
                code = main(
                    [
                        "solo",
                        str(repo),
                        "--create",
                        "--agent",
                        "mock",
                        "--want",
                        "Build a useful first release checklist",
                        "--outcome",
                        "The repo has a launch checklist",
                        "--skip-skills",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["created_project"]["status"], "created")
            self.assertTrue((repo / ".git").is_dir())
            self.assertIn("Build a useful first release checklist", (repo / "README.md").read_text(encoding="utf-8"))
            self.assertIn(
                "Build a useful first release checklist",
                (repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Build a useful first release checklist",
                (repo / ".umsmfburasbofe" / "PROJECT-MEMORY.md").read_text(encoding="utf-8"),
            )

    def test_solo_create_accepts_static_site_starter(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "fresh-site"
            env = {
                "UMSMFBURASBOFE_TOKEN_MODE_FILE": str(Path(temp) / "token-mode.json"),
                "UMSMFBURASBOFE_SKILLS_DIR": str(Path(temp) / "skills"),
            }
            stdout = io.StringIO()
            with patch.dict(os.environ, env), redirect_stdout(stdout):
                code = main(
                    [
                        "solo",
                        str(repo),
                        "--create",
                        "--starter",
                        "static-site",
                        "--agent",
                        "mock",
                        "--want",
                        "Build a simple product homepage",
                        "--skip-skills",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["created_project"]["starter"], "static-site")
            self.assertTrue((repo / "index.html").exists())
            self.assertTrue((repo / "tests" / "test_static_site.py").exists())
            self.assertIn("unittest", (repo / ".umsmfburasbofe" / "config.toml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
