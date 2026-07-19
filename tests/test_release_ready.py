import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.project import initialize_project
from manageroo.release_ready import format_release_ready, release_ready
from manageroo.util import atomic_write_json


class ReleaseReadyTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product brief\n\nShip the thing.\n", encoding="utf-8")
        add_check_gate(repo, gate_id="smoke", argv=[sys.executable, "-c", "print('ok')"])
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "ready fixture"], cwd=repo, check=True)
        return repo

    def _release_patches(self):
        return patch(
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
        )

    def _completed_run(self, repo: Path, *, run_id: str = "20260622T120000-complete") -> Path:
        run_root = repo / ".manageroo" / "runs" / run_id
        delivery = run_root / "delivery"
        delivery.mkdir(parents=True)
        patch_path = delivery / "final.patch"
        report_path = delivery / "FINAL-REPORT.md"
        patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
        report_path.write_text("# Final Report\n", encoding="utf-8")
        atomic_write_json(
            delivery / "final-result.json",
            {
                "run_id": run_id,
                "status": "COMPLETE",
                "review": {"status": "approved", "findings": []},
                "evidence_paths": {
                    "patch": str(patch_path),
                    "run_root": str(run_root),
                },
                "applied_to_source": True,
            },
        )
        return run_root

    def test_release_ready_passes_with_clean_repo_passing_gates_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            run_root = self._completed_run(repo)
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
            run_item = {item["name"]: item for item in report["items"]}["completed Manageroo run"]
            self.assertTrue(run_item["ok"])
            self.assertIn(run_root.name, run_item["detail"])
            handoff = Path(report["handoff_path"])
            self.assertTrue(handoff.exists())
            handoff_text = handoff.read_text(encoding="utf-8")
            self.assertIn("# Production Handoff", handoff_text)
            self.assertIn("READY FOR OPERATOR RELEASE", handoff_text)
            self.assertIn("manual production deploy", handoff_text)
            self.assertIn("revert the release commit and redeploy", handoff_text)
            self.assertIn(shlex.join([sys.executable, "-c", "print('ok')"]), handoff_text)
            self.assertIn("ready fixture", handoff_text)
            self.assertIn("Manageroo run", handoff_text)
            self.assertIn(run_root.name, handoff_text)
            self.assertIn("## Project Memory", handoff_text)
            self.assertIsNone(report["project_memory_update"])
            self.assertIn("Not mutated by `release-ready`", handoff_text)

            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            self.assertEqual(status.stdout.strip(), "")

            formatted = format_release_ready(report)
            self.assertIn("Production handoff:", formatted)
            self.assertIn(str(handoff), formatted)

    def test_release_ready_fails_without_completed_manageroo_run(self):
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
            self.assertFalse(report["ok"])
            names = {item["name"]: item for item in report["items"]}
            self.assertFalse(names["completed Manageroo run"]["ok"])
            self.assertIn("manageroo run", names["completed Manageroo run"]["next"])
            self.assertIn("--repo", names["completed Manageroo run"]["next"])
            self.assertEqual(report["project_memory_update"], None)

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
            self.assertEqual(report["project_memory_update"], None)


if __name__ == "__main__":
    unittest.main()
