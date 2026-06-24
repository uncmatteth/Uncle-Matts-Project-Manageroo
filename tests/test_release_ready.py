import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.project import initialize_project
from manageroo.util import atomic_write_json, read_json
from manageroo.release_ready import format_release_ready, release_ready


def _install_stack_probe_shims(repo: Path) -> Path:
    tools = repo.parent / "stack-probe-tools"
    tools.mkdir(exist_ok=True)
    gbrain = tools / "gbrain"
    gbrain.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"search\" ] || { [ \"$1\" = \"call\" ] && [ \"$2\" = \"query\" ]; }; then\n"
        "  printf '%s\\n' '{\"results\":[{\"source_id\":\"fixture\",\"text\":\"readiness-probe-ok\"}]}'\n"
        "else\n"
        "  printf '%s\\n' readiness-probe-ok\n"
        "fi\n",
        encoding="utf-8",
    )
    gbrain.chmod(0o755)
    gitnexus = tools / "gitnexus"
    gitnexus.write_text("#!/bin/sh\nprintf '%s\\n' readiness-probe-ok\n", encoding="utf-8")
    gitnexus.chmod(0o755)
    return tools


def _gbrain_status_for(repo: Path) -> dict:
    return {
        "ok": True,
        "status": {
            "source_count": 1,
            "sources": [{"id": "fixture", "path": str(repo)}],
        },
    }


class ReleaseReadyTests(unittest.TestCase):
    def _which_stack(self, name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git"
        tools = getattr(self, "_stack_probe_tools", None)
        if name in {"gbrain", "gitnexus"} and tools is not None:
            return str(tools / name)
        return None

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        tools = _install_stack_probe_shims(repo)
        self._stack_probe_tools = tools
        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product brief\n\nShip the thing.\n", encoding="utf-8")
        add_check_gate(repo, gate_id="smoke", argv=["python3", "-c", "print('ok')"])
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "ready fixture"], cwd=repo, check=True)
        return repo

    def _release_patches(self, repo: Path):
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
            return_value=_gbrain_status_for(repo),
        ), patch(
            "manageroo.readiness.shutil.which",
            side_effect=self._which_stack,
        ), patch.dict(
            os.environ,
            {"PATH": f"{self._stack_probe_tools}:{os.environ.get('PATH', '')}"},
        )

    def _completed_run(self, repo: Path, *, run_id: str = "20260622T120000-complete") -> Path:
        run_root = repo / ".manageroo" / "runs" / run_id
        delivery = run_root / "delivery"
        capture_artifacts = run_root / "artifacts" / "delivery"
        delivery.mkdir(parents=True)
        capture_artifacts.mkdir(parents=True)
        patch_path = delivery / "final.patch"
        report_path = delivery / "FINAL-REPORT.md"
        capture_payload = {
            "summary": {
                "enabled": True,
                "passed": True,
                "failed_required": [],
                "failed_optional": [],
            },
            "records": [{"name": "gbrain-capture", "ok": True}],
        }
        patch_path.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")
        report_path.write_text("# Final Report\n", encoding="utf-8")
        atomic_write_json(capture_artifacts / "external-capture.json", capture_payload)
        atomic_write_json(
            delivery / "final-result.json",
            {
                "run_id": run_id,
                "status": "COMPLETE",
                "review": {"status": "approved", "findings": []},
                "external_capture": capture_payload,
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
            helper_patch, gbrain_patch, which_patch, path_patch = self._release_patches(repo)
            with helper_patch, gbrain_patch, which_patch, path_patch:
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
            self.assertIn("python3 -c print('ok')", handoff_text)
            self.assertIn("ready fixture", handoff_text)
            self.assertIn("Manageroo run", handoff_text)
            self.assertIn(run_root.name, handoff_text)
            self.assertIn("## Project Memory", handoff_text)
            memory_update = report["project_memory_update"]
            self.assertTrue(memory_update["ok"])
            self.assertIn(memory_update["path"], handoff_text)
            self.assertIn("What Has Shipped", memory_update["updated_sections"])
            self.assertIn("Current Proof", memory_update["updated_sections"])
            memory_text = (repo / ".manageroo" / "PROJECT-MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("Release-ready approved for manual production deploy", memory_text)
            self.assertIn("commit", memory_text)
            self.assertIn("release-ready passed smoke", memory_text)
            self.assertIn(run_root.name, memory_text)
            self.assertIn("Production handoff", memory_text)

            formatted = format_release_ready(report)
            self.assertIn("Production handoff:", formatted)
            self.assertIn("Project memory updated:", formatted)
            self.assertIn(str(handoff), formatted)

    def test_release_ready_blocks_without_required_capture_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            run_root = self._completed_run(repo)
            result_path = run_root / "delivery" / "final-result.json"
            data = {
                key: value
                for key, value in read_json(result_path).items()
                if key != "external_capture"
            }
            atomic_write_json(result_path, data)
            (run_root / "artifacts" / "delivery" / "external-capture.json").unlink()
            helper_patch, gbrain_patch, which_patch, path_patch = self._release_patches(repo)
            with helper_patch, gbrain_patch, which_patch, path_patch:
                report = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert the release commit and redeploy",
                    approved_by="Operator",
                )
            self.assertFalse(report["ok"])
            run_item = {item["name"]: item for item in report["items"]}["completed Manageroo run"]
            self.assertFalse(run_item["ok"])
            self.assertIn("required external capture proof", run_item["detail"])

    def test_release_ready_blocks_when_capture_artifact_failed_despite_embedded_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            run_root = self._completed_run(repo)
            atomic_write_json(
                run_root / "artifacts" / "delivery" / "external-capture.json",
                {
                    "summary": {
                        "enabled": True,
                        "passed": False,
                        "failed_required": ["gbrain-capture"],
                        "failed_optional": [],
                    },
                    "records": [{"name": "gbrain-capture", "ok": False}],
                },
            )
            helper_patch, gbrain_patch, which_patch, path_patch = self._release_patches(repo)
            with helper_patch, gbrain_patch, which_patch, path_patch:
                report = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert the release commit and redeploy",
                    approved_by="Operator",
                )
            self.assertFalse(report["ok"])
            run_item = {item["name"]: item for item in report["items"]}["completed Manageroo run"]
            self.assertFalse(run_item["ok"])
            self.assertIn("external capture artifact is failed", run_item["detail"])

    def test_release_ready_fails_without_completed_manageroo_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            helper_patch, gbrain_patch, which_patch, path_patch = self._release_patches(repo)
            with helper_patch, gbrain_patch, which_patch, path_patch:
                report = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert the release commit and redeploy",
                    approved_by="Operator",
                )
            self.assertFalse(report["ok"])
            names = {item["name"]: item for item in report["items"]}
            self.assertFalse(names["completed Manageroo run"]["ok"])
            self.assertIn("manageroo run --apply", names["completed Manageroo run"]["next"])
            self.assertEqual(report["project_memory_update"], None)

    def test_release_ready_blocks_without_release_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            helper_patch, gbrain_patch, which_patch, path_patch = self._release_patches(repo)
            with helper_patch, gbrain_patch, which_patch, path_patch:
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
