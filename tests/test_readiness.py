import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.project import initialize_project
from umsmfburasbofe.readiness import readiness


class ReadinessTests(unittest.TestCase):
    def test_readiness_reports_exact_next_step_for_missing_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            with patch(
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
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            checks = [item for item in report["items"] if item["name"] == "checks"][0]
            self.assertFalse(checks["ok"])
            self.assertIn("umsmfburasbofe checks add smoke", checks["next"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["required"])


if __name__ == "__main__":
    unittest.main()
