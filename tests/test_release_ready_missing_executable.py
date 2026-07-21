import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.project import initialize_project
from manageroo.release_proof_policy import source_tree_digest
from manageroo.release_ready import release_ready
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json, sha256_file


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


class ReleaseReadyMissingExecutableTests(unittest.TestCase):
    def test_missing_verification_executable_becomes_failed_gate_not_uncaught_oserror(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.name", "Manageroo Tests")
            git(repo, "config", "user.email", "tests@local.invalid")
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nShip safely.\n",
                encoding="utf-8",
            )
            missing = "manageroo-command-that-does-not-exist-9b1e8a"
            config_path = repo / ".manageroo" / "config.toml"
            config_text = config_path.read_text(encoding="utf-8")
            marker = "allowed_programs = ["
            self.assertIn(marker, config_text)
            config_path.write_text(
                config_text.replace(marker, f'allowed_programs = ["{missing}", ', 1),
                encoding="utf-8",
            )
            add_check_gate(repo, gate_id="missing-tool", argv=[missing, "--check"])
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "fixture")

            run_root = repo / ".manageroo" / "runs" / "completed-run"
            delivery = run_root / "delivery"
            delivery.mkdir(parents=True)
            patch_path = delivery / "final.patch"
            patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
            report_path = delivery / "FINAL-REPORT.md"
            report_path.write_text("# Final Report\n", encoding="utf-8")
            atomic_write_json(
                delivery / "final-result.json",
                {
                    "run_id": "completed-run",
                    "status": "COMPLETE",
                    "review": {"status": "approved", "findings": []},
                    "evidence_paths": {"patch": str(patch_path), "run_root": str(run_root)},
                    "applied_to_source": True,
                    "verified_source_tree_sha256": source_tree_digest(repo, CommandRunner()),
                    "final_patch_sha256": sha256_file(patch_path),
                },
            )

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[
                    {"name": "helper:test", "ok": True, "detail": "mock", "next": "", "required": True}
                ],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ):
                result = release_ready(
                    repo,
                    target="manual deploy",
                    rollback="revert commit",
                    approved_by="Operator",
                )

            self.assertFalse(result["ok"])
            verification = {item["name"]: item for item in result["items"]}["verification gates"]
            self.assertFalse(verification["ok"])
            self.assertIn("missing-tool", verification["detail"])


if __name__ == "__main__":
    unittest.main()
