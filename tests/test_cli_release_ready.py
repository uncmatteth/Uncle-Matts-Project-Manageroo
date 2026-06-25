import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.artifacts import ArtifactStore
from manageroo.checks import add_check_gate
from manageroo.cli import main
from manageroo.jobs import JobStore
from manageroo.project import initialize_project
from manageroo.runner import CommandRunner
from manageroo.state import Phase
from manageroo.util import atomic_write_json, utc_now
from manageroo.workspace import WorkspaceMirror


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
    for name in ("autoreview", "clawpatch"):
        command = tools / name
        command.write_text("#!/bin/sh\nprintf '%s\\n' readiness-probe-ok\n", encoding="utf-8")
        command.chmod(0o755)
    return tools


def _gbrain_status_for(repo: Path) -> dict:
    return {
        "ok": True,
        "status": {
            "source_count": 1,
            "sources": [{"id": "fixture", "path": str(repo)}],
        },
    }


class CliReleaseReadyTests(unittest.TestCase):
    def _which_stack(self, name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git"
        tools = getattr(self, "_stack_probe_tools", None)
        if name in {"gbrain", "gitnexus", "autoreview", "clawpatch"} and tools is not None:
            return str(tools / name)
        return None

    def test_release_ready_json_reports_ready_for_operator_release(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            tools = _install_stack_probe_shims(repo)
            self._stack_probe_tools = tools
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nShip the thing.\n",
                encoding="utf-8",
            )
            add_check_gate(repo, gate_id="smoke", argv=["python3", "-c", "print('ok')"])
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "ready fixture"], cwd=repo, check=True)

            run_root = repo / ".manageroo" / "runs" / "20260622T120000-complete"
            delivery = run_root / "delivery"
            delivery.mkdir(parents=True)
            artifact_store = ArtifactStore(run_root / "artifacts")
            job_store = JobStore(run_root)
            mirror = WorkspaceMirror(repo, run_root, CommandRunner())
            workspace = mirror.create()
            (workspace / "README.md").write_text("fixture\nrelease change\n", encoding="utf-8")
            mirror.checkpoint("fixture delivery")
            patch_path = delivery / "final.patch"
            mirror.write_patch(patch_path)
            mirror.apply_patch_to_source(patch_path)
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "apply manageroo delivery"], cwd=repo, check=True)
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
            report_path.write_text("# Final Report\n", encoding="utf-8")
            artifact_store.write_json("delivery/external-capture.json", capture_payload)
            planning_artifact = artifact_store.write_json("planning/product.json", {"goal": "fixture"})
            job = job_store.create_or_load_job(
                "001-product-analyst",
                role="analyst",
                schema="product",
                instructions="Analyze fixture.",
                allowed_paths=["README.md"],
            )
            attempt = job_store.begin_attempt(job.id)
            output_path = run_root / "agent-output" / "001-product-analyst.json"
            output_path.parent.mkdir(parents=True)
            atomic_write_json(output_path, {"goal": "fixture"})
            job_store.complete_attempt(
                job.id,
                attempt.attempt_id,
                output_path=output_path,
                data={"goal": "fixture"},
                command=["mock-agent"],
            )
            job_store.complete_job(
                job.id,
                output_artifact=planning_artifact.path,
                data={"goal": "fixture"},
                artifact_path=artifact_store.root / planning_artifact.path,
            )
            atomic_write_json(
                run_root / "state.json",
                {
                    "run_id": run_root.name,
                    "phase": Phase.COMPLETE.value,
                    "history": [{"phase": Phase.COMPLETE.value, "at": utc_now(), "reason": "fixture"}],
                    "repair_cycles": 0,
                    "plan_review_cycles": 0,
                },
            )
            atomic_write_json(
                delivery / "final-result.json",
                {
                    "run_id": run_root.name,
                    "status": "COMPLETE",
                    "review": {"status": "approved", "findings": []},
                    "external_capture": capture_payload,
                    "evidence_paths": {
                        "patch": str(patch_path),
                        "run_root": str(run_root),
                        "artifact_ledger": str(artifact_store.ledger_path),
                        "state": str(run_root / "state.json"),
                    },
                    "applied_to_source": True,
                },
            )

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
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ), patch.dict(
                os.environ,
                {"PATH": f"{tools}:{os.environ.get('PATH', '')}"},
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
