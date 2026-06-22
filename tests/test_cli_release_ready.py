import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.cli import main
from manageroo.project import initialize_project


class CliReleaseReadyTests(unittest.TestCase):
    def test_release_ready_json_reports_ready_for_operator_release(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nShip the thing.\n",
                encoding="utf-8",
            )
            add_check_gate(repo, gate_id="smoke", argv=["python3", "-c", "print('ok')"])
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "ready fixture"], cwd=repo, check=True)

            stdout = io.StringIO()
            with patch(
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
                code = main(
                    [
                        "release-ready",
                        str(repo),
                        "--target",
                        "manual production deploy",
                        "--rollback",
                        "revert and redeploy",
                        "--approved-by",
                        "Operator",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["status"], "READY FOR OPERATOR RELEASE")
            self.assertTrue(Path(payload["handoff_path"]).exists())
            self.assertIn("Production Handoff", payload["handoff_markdown"])
            self.assertTrue(payload["project_memory_update"]["ok"])
            memory_text = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("Release-ready approved for manual production deploy", memory_text)


if __name__ == "__main__":
    unittest.main()
