import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.project import initialize_project
from manageroo.readiness import format_readiness, readiness


class ReadinessTests(unittest.TestCase):
    def _ready_repo(self, root: Path, brief: str) -> Path:
        repo = root
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            + "\n[[verification.gates]]\n"
            + 'id = "smoke"\n'
            + 'kind = "test"\n'
            + "required = true\n"
            + "timeout_seconds = 60\n"
            + 'argv = ["python3", "-m", "compileall", "."]\n',
            encoding="utf-8",
        )
        (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(brief, encoding="utf-8")
        return repo

    def test_readiness_reports_exact_next_step_for_missing_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
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
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            checks = [item for item in report["items"] if item["name"] == "checks"][0]
            self.assertFalse(checks["ok"])
            self.assertEqual(checks["next"], "manageroo checks suggest --apply-first")
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["required"])

    def test_readiness_reports_missing_project_memory_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PROJECT-MEMORY.md").unlink()
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
            ):
                report = readiness(repo)
            memory = [item for item in report["items"] if item["name"] == "project memory"][0]
            self.assertFalse(memory["ok"])
            self.assertIn("manageroo memory init", memory["next"])

    def test_explicit_document_request_blocks_when_document_lane_is_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(
                Path(temp),
                "# Product brief\n\nClean up this PDF transcript and preserve exact wording.\n",
            )
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            lane = [item for item in report["items"] if item["name"] == "document/prose lane"][0]
            self.assertFalse(lane["ok"])
            self.assertTrue(lane["required"])
            self.assertIn("document_analysis_command", lane["detail"])
            self.assertIn("document_analysis_command", lane["next"])
            self.assertIn("ACTION document/prose lane", format_readiness(report))

    def test_repo_media_without_explicit_request_warns_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake the app work.\n")
            media = repo / "assets" / "screenshot.png"
            media.parent.mkdir()
            media.write_bytes(b"\x89PNG\r\n\x1a\n")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ):
                report = readiness(repo)
            self.assertTrue(report["ok"])
            lane = [item for item in report["items"] if item["name"] == "document/prose lane"][0]
            self.assertFalse(lane["ok"])
            self.assertFalse(lane["required"])
            self.assertEqual(lane["severity"], "warning")
            self.assertIn("repo contains", lane["detail"])
            self.assertIn("WARN document/prose lane", format_readiness(report))

    def test_memory_request_requires_gbrain_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(
                Path(temp),
                "# Product brief\n\nUse GBrain memory and prior decisions before changing this.\n",
            )
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["ok"])
            self.assertTrue(gbrain["required"])
            self.assertIn("brief asks for memory", gbrain["detail"])


if __name__ == "__main__":
    unittest.main()
