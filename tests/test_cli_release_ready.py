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
from manageroo.util import atomic_write_json


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
            run_root = repo / ".manageroo" / "runs" / "20260622T120000-complete"
            delivery = run_root / "delivery"
            delivery.mkdir(parents=True)
            patch_path = delivery / "final.patch"
            report_path = delivery / "FINAL-REPORT.md"
            patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
            report_path.write_text("# Final Report\n", encoding="utf-8")
            atomic_write_json(
                delivery / "final-result.json",
                {
                    "run_id": run_root.name,
                    "status": "COMPLETE",
                    "review": {"status": "approved", "findings": []},
                    "evidence_paths": {
                        "patch": str(patch_path),
                        "run_root": str(run_root),
                    },
                    "applied_to_source": True,
                },
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
            self.assertIn(run_root.name, payload["handoff_markdown"])
            self.assertTrue(payload["project_memory_update"]["ok"])
            memory_text = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("Release-ready approved for manual production deploy", memory_text)
            self.assertIn(run_root.name, memory_text)


if __name__ == "__main__":
    unittest.main()
