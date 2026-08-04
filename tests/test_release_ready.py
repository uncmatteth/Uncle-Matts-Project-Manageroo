import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manageroo.release_ready as release_ready_module
from manageroo.checks import add_check_gate
from manageroo.project import initialize_project
from manageroo.release_proof_policy import source_tree_digest
from manageroo.release_ready import format_release_ready, release_ready
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json, read_json, sha256_file


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
                "verified_source_tree_sha256": source_tree_digest(repo, CommandRunner()),
                "final_patch_sha256": sha256_file(patch_path),
            },
        )
        return run_root

    def _release_ready(self, repo: Path) -> dict:
        helper_patch, gbrain_patch = self._release_patches()
        with helper_patch, gbrain_patch:
            return release_ready(
                repo,
                target="manual production deploy",
                rollback="revert the release commit and redeploy",
                approved_by="Operator",
            )

    def test_release_ready_passes_with_clean_repo_passing_gates_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            run_root = self._completed_run(repo)
            report = self._release_ready(repo)
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

    def test_release_ready_rejects_completed_proof_from_previous_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            self._completed_run(repo)
            (repo / "README.md").write_text("fixture changed after proof\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "change after proof"], cwd=repo, check=True)

            report = self._release_ready(repo)
            self.assertFalse(report["ok"])
            run_item = {item["name"]: item for item in report["items"]}["completed Manageroo run"]
            self.assertFalse(run_item["ok"])
            self.assertIn("does not match", run_item["detail"])

    def test_release_ready_rejects_clean_commit_after_final_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            self._completed_run(repo)
            source_digest_calls = 0
            commit_attempt = None

            def commit_after_final_digest(path: Path, runner: CommandRunner) -> str:
                nonlocal source_digest_calls, commit_attempt
                digest = source_tree_digest(path, runner)
                if path.resolve() == repo.resolve():
                    source_digest_calls += 1
                    if source_digest_calls == 3:
                        (repo / "README.md").write_text(
                            "concurrent clean commit\n", encoding="utf-8"
                        )
                        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
                        commit_attempt = subprocess.run(
                            ["git", "commit", "-q", "-m", "concurrent change"],
                            cwd=repo,
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                return digest

            with patch(
                "manageroo.release_ready.source_tree_digest",
                side_effect=commit_after_final_digest,
            ):
                report = self._release_ready(repo)

            self.assertIsNotNone(commit_attempt)
            self.assertNotEqual(commit_attempt.returncode, 0)
            self.assertFalse(report["ok"], report)
            item = {value["name"]: value for value in report["items"]}[
                "source integrity after release evidence"
            ]
            self.assertFalse(item["ok"])
            self.assertIn("Git worktree changed", item["detail"])
            self.assertIn("Do not ship yet.", Path(report["handoff_path"]).read_text(encoding="utf-8"))

    def test_release_ready_binds_ship_artifact_before_post_status_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            self._completed_run(repo)
            original_git_status = release_ready_module._git_status
            status_calls = 0

            def mutate_after_status_snapshot(path: Path) -> tuple[bool, str]:
                nonlocal status_calls
                result = original_git_status(path)
                if path.resolve() == repo.resolve():
                    status_calls += 1
                    if status_calls == 3:
                        (repo / "README.md").write_text(
                            "mutation after final status snapshot\n", encoding="utf-8"
                        )
                return result

            with patch(
                "manageroo.release_ready._git_status",
                side_effect=mutate_after_status_snapshot,
            ):
                report = self._release_ready(repo)

            self.assertEqual(status_calls, 3)
            self.assertTrue(report["ok"], report)
            artifact = report["release_artifact"]
            artifact_path = Path(artifact["path"])
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(sha256_file(artifact_path), artifact["sha256"])
            with tarfile.open(artifact_path, "r") as archive:
                readme = archive.extractfile("README.md")
                self.assertIsNotNone(readme)
                self.assertEqual(readme.read(), b"fixture\n")
            self.assertEqual(
                (repo / "README.md").read_text(encoding="utf-8"),
                "mutation after final status snapshot\n",
            )
            handoff = Path(report["handoff_path"]).read_text(encoding="utf-8")
            self.assertIn("## Immutable Release Artifact", handoff)
            self.assertIn(artifact["sha256"], handoff)
            self.assertIn("Deploy this artifact, not the mutable source worktree.", handoff)

    def test_release_ready_rejects_gate_mutation_inside_disposable_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            gate_script = (
                "from pathlib import Path; import subprocess; "
                "Path('README.md').write_text('changed by gate\\n', encoding='utf-8'); "
                "subprocess.run(['git', 'add', 'README.md'], check=True); "
                "subprocess.run(['git', '-c', 'user.name=Gate', "
                "'-c', 'user.email=gate@example.invalid', 'commit', '-q', "
                "'-m', 'gate mutation'], check=True)"
            )
            add_check_gate(repo, gate_id="mutating", argv=[sys.executable, "-c", gate_script])
            subprocess.run(["git", "add", ".manageroo/config.toml"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "add mutating gate"], cwd=repo, check=True)
            self._completed_run(repo)
            original_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()

            report = self._release_ready(repo)

            self.assertFalse(report["ok"], report)
            gate_item = {item["name"]: item for item in report["items"]}[
                "verification gates pass"
            ]
            self.assertFalse(gate_item["ok"])
            self.assertIn("mutated its disposable release checkout", gate_item["detail"])
            current_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            self.assertEqual(current_head, original_head)
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), "fixture\n")
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
            self.assertEqual(status.stdout.strip(), "")

    def test_release_ready_rejects_tampered_final_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            run_root = self._completed_run(repo)
            patch_path = run_root / "delivery" / "final.patch"
            patch_path.write_text(patch_path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")

            report = self._release_ready(repo)
            self.assertFalse(report["ok"])
            run_item = {item["name"]: item for item in report["items"]}["completed Manageroo run"]
            self.assertFalse(run_item["ok"])
            self.assertIn("patch bytes", run_item["detail"])

    def test_release_ready_rejects_malformed_completed_proof_without_raising(self):
        cases = (
            ("null evidence_paths", "evidence_paths", None),
            ("null review", "review", None),
            ("non-string patch path", "evidence_paths.patch", ["final.patch"]),
            ("string applied state", "applied_to_source", "false"),
        )
        for label, field, value in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                repo = self._repo(Path(temp))
                run_root = self._completed_run(repo)
                result_path = run_root / "delivery" / "final-result.json"
                proof = read_json(result_path)
                if field == "evidence_paths.patch":
                    proof["evidence_paths"]["patch"] = value
                else:
                    proof[field] = value
                atomic_write_json(result_path, proof)

                report = self._release_ready(repo)

                self.assertFalse(report["ok"])
                run_proof = report["manageroo_run"]
                self.assertFalse(run_proof["ok"])
                self.assertIn("invalid schema", run_proof["detail"])
                self.assertIn(field, run_proof["detail"])

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

    def test_required_clawpatch_sweep_must_prove_zero_open_at_current_head(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            self._completed_run(repo)
            helper_patch, gbrain_patch = self._release_patches()
            with helper_patch, gbrain_patch:
                missing = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert and redeploy",
                    approved_by="Operator",
                    require_clawpatch=True,
                )
            item = {value["name"]: value for value in missing["items"]}["Clawpatch release sweep"]
            self.assertFalse(item["ok"])
            self.assertIn("clawpatch release-sweep", item["next"])

            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, text=True, stdout=subprocess.PIPE
            ).stdout.strip()
            atomic_write_json(
                repo / ".manageroo" / "cache" / "clawpatch-release-proof.json",
                {"status": "COMPLETE", "git_head": head, "open_findings": 0},
            )
            helper_patch, gbrain_patch = self._release_patches()
            with helper_patch, gbrain_patch:
                proven = release_ready(
                    repo,
                    target="manual production deploy",
                    rollback="revert and redeploy",
                    approved_by="Operator",
                    require_clawpatch=True,
                )
            item = {value["name"]: value for value in proven["items"]}["Clawpatch release sweep"]
            self.assertTrue(item["ok"])


if __name__ == "__main__":
    unittest.main()
