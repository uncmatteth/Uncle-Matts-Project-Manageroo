import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.checks import add_check_gate
from umsmfburasbofe.project import initialize_project
from umsmfburasbofe.release_ready import format_release_ready, release_ready


class ReleaseReadyTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        brief = repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product brief\n\nShip the thing.\n", encoding="utf-8")
        add_check_gate(repo, gate_id="smoke", argv=["python3", "-c", "print('ok')"])
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "ready fixture"], cwd=repo, check=True)
        return repo

    def _release_patches(self):
        return patch(
            "umsmfburasbofe.readiness.helper_skill_items",
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
            "umsmfburasbofe.readiness.gbrain_setup_status",
            return_value={"ok": False, "status": {"source_count": 0}},
        )

    def test_release_ready_passes_with_clean_repo_passing_gates_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            helper_patch, gbrain_patch = self._release_patches()
            with helper_patch, gbrain_patch:
                report = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert the release commit and redeploy",
                    approved_by="Operator",
                )
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["status"], "READY FOR OPERATOR RELEASE")
            self.assertEqual(report["next_commands"], [])
            handoff = Path(report["handoff_path"])
            self.assertTrue(handoff.exists())
            handoff_text = handoff.read_text(encoding="utf-8")
            self.assertIn("# Production Handoff", handoff_text)
            self.assertIn("READY FOR OPERATOR RELEASE", handoff_text)
            self.assertIn("manual production deploy", handoff_text)
            self.assertIn("revert the release commit and redeploy", handoff_text)
            self.assertIn("python3 -c print('ok')", handoff_text)
            self.assertIn("ready fixture", handoff_text)

            formatted = format_release_ready(report)
            self.assertIn("Production handoff:", formatted)
            self.assertIn(str(handoff), formatted)

    def test_release_ready_blocks_without_release_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            helper_patch, gbrain_patch = self._release_patches()
            with helper_patch, gbrain_patch:
                report = release_ready(repo)
            self.assertFalse(report["ok"])
            names = {item["name"]: item for item in report["items"]}
            self.assertFalse(names["deployment target"]["ok"])
            self.assertFalse(names["rollback notes"]["ok"])
            self.assertFalse(names["human approval"]["ok"])
            self.assertTrue(any("release-ready" in command for command in report["next_commands"]))
            self.assertIn("Do not ship yet.", Path(report["handoff_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
