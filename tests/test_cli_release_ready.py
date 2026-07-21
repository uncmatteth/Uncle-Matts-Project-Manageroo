import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.cli import main
from manageroo.project import initialize_project
from manageroo.release_proof_policy import source_tree_digest
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json, sha256_file


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class CliReleaseReadyTests(unittest.TestCase):
    def test_release_ready_json_reports_ready_for_operator_release(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            _git(repo, "init", "-q", "-b", "main")
            _git(repo, "config", "user.name", "Test")
            _git(repo, "config", "user.email", "test@example.invalid")
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text("# Product brief\n\nShip the thing.\n", encoding="utf-8")
            run_root = repo / ".manageroo" / "runs" / "20260622T120000-complete"
            delivery = run_root / "delivery"
            delivery.mkdir(parents=True)
            patch_path = delivery / "final.patch"
            report_path = delivery / "FINAL-REPORT.md"
            patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
            report_path.write_text("# Final Report\n", encoding="utf-8")
            add_check_gate(repo, gate_id="smoke", argv=[sys.executable, "-c", "print('ok')"])
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "ready fixture")
            atomic_write_json(
                delivery / "final-result.json",
                {
                    "run_id": run_root.name,
                    "status": "COMPLETE",
                    "review": {"status": "approved", "findings": []},
                    "evidence_paths": {"patch": str(patch_path), "run_root": str(run_root)},
                    "applied_to_source": True,
                    "verified_source_tree_sha256": source_tree_digest(repo, CommandRunner()),
                    "final_patch_sha256": sha256_file(patch_path),
                },
            )
            memory_before = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_bytes()

            stdout = io.StringIO()
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[{"name": "helper:test", "ok": True, "detail": "mock", "next": "", "required": True}],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), redirect_stdout(stdout):
                code = main([
                    "release-ready", str(repo), "--target", "manual production deploy",
                    "--rollback", "revert and redeploy", "--approved-by", "Operator", "--json",
                ])

            payload = json.loads(stdout.getvalue())
            handoff_path = Path(payload["handoff_path"])
            persisted_handoff = handoff_path.read_text(encoding="utf-8")
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["status"], "READY FOR OPERATOR RELEASE")
            self.assertTrue(payload.get("handoff_verified"))
            self.assertEqual(persisted_handoff, payload["handoff_markdown"])
            self.assertIn("Status: READY FOR OPERATOR RELEASE", persisted_handoff)
            self.assertIn("Ship when the human operator is ready.", persisted_handoff)
            self.assertIn("Production Handoff", persisted_handoff)
            self.assertIn(run_root.name, persisted_handoff)
            self.assertIsNone(payload["project_memory_update"])
            self.assertIn("Not mutated by `release-ready`", persisted_handoff)
            self.assertEqual((repo / ".manageroo" / "PROJECT-MEMORY.md").read_bytes(), memory_before)
            status = _git(repo, "status", "--porcelain", "--untracked-files=all")
            self.assertEqual(status.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
