import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError, ValidationError
from manageroo.external_repair_policy import (
    _git_metadata_snapshot,
    _ignored_state,
    _materialize_checkpoint_workspace,
    _replace_workspace_from_checkpoint,
    run_external_review_repair_lanes,
)
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json, read_json
from manageroo.workspace import WorkspaceMirror


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


def source_repo(root: Path) -> Path:
    repo = root / "source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Manageroo Tests")
    git(repo, "config", "user.email", "tests@local.invalid")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")
    return repo


def fake_orchestrator(root: Path, source: Path, run_id: str, command):
    run_root = root / run_id
    run_root.mkdir(parents=True)
    runner = CommandRunner()
    mirror = WorkspaceMirror(source, run_root, runner)
    workspace = mirror.create()
    artifacts = ArtifactStore(run_root / "artifacts")
    fake = SimpleNamespace(
        workspace=workspace,
        source_repo=source,
        artifacts=artifacts,
        mirror=mirror,
        runner=runner,
        run_id=run_id,
    )
    fake._artifact_json = lambda relative: None
    fake._external_review_repair_commands = lambda: [("clawpatch", ["fake"])]
    fake._external_values = lambda **_kwargs: {}
    fake._run_optional_external_command = command
    return fake, run_root


class ExternalRepairPolicyTests(unittest.TestCase):
    def test_command_git_metadata_mutation_is_rejected_restored_and_rolled_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                config = workspace / ".git" / "config"
                config.write_bytes(config.read_bytes() + b"\n# external mutation\n")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()
            config = fake.workspace / ".git" / "config"
            expected_config = config.read_bytes()

            with self.assertRaisesRegex(SafetyError, "protected Git metadata"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(config.read_bytes(), expected_config)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_checkpoint_materialization_uses_verified_metadata_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            fake, run_root = fake_orchestrator(
                root,
                source,
                "run-one",
                lambda **_kwargs: {"name": "clawpatch", "ok": True, "exit_code": 0},
            )
            checkpoint = fake.mirror.head()
            snapshot = _git_metadata_snapshot(fake)
            live_config = fake.workspace / ".git" / "config"
            live_config.write_bytes(live_config.read_bytes() + b"\n# unverified live state\n")
            live_hook = fake.workspace / ".git" / "hooks" / "unverified-hook"
            live_hook.write_text("unverified\n", encoding="utf-8")
            recovery_root = run_root / "recovery"
            recovery_root.mkdir()

            staged = _materialize_checkpoint_workspace(
                fake,
                checkpoint=checkpoint,
                recovery_root=recovery_root,
                git_metadata_snapshot=snapshot,
            )

            self.assertNotIn(b"unverified live state", (staged / ".git" / "config").read_bytes())
            self.assertFalse((staged / ".git" / "hooks" / "unverified-hook").exists())
            self.assertIn(b"unverified live state", live_config.read_bytes())
            self.assertTrue(live_hook.is_file())

    def test_checkpoint_replace_rolls_back_multiple_ignored_entries_when_later_move_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            fake, _run_root = fake_orchestrator(
                root,
                source,
                "run-one",
                lambda **_kwargs: {"name": "clawpatch", "ok": True, "exit_code": 0},
            )
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "*.cache\n", encoding="utf-8"
            )
            first = fake.workspace / "first.cache"
            second = fake.workspace / "second.cache"
            first.write_text("first operator data\n", encoding="utf-8")
            second.write_text("second operator data\n", encoding="utf-8")
            ignored_state = _ignored_state(fake, {"first.cache", "second.cache"})
            snapshot = _git_metadata_snapshot(fake)
            real_replace = os.replace

            def fail_second_move(source_path, destination_path):
                if Path(source_path) == second and Path(destination_path).name == second.name:
                    raise OSError("second ignored move failed")
                return real_replace(source_path, destination_path)

            with patch(
                "manageroo.external_repair_policy.os.replace",
                side_effect=fail_second_move,
            ):
                with self.assertRaisesRegex(SafetyError, "workspace replacement failed"):
                    _replace_workspace_from_checkpoint(
                        fake,
                        name="clawpatch",
                        checkpoint=fake.mirror.head(),
                        preserved_ignored_state=ignored_state,
                        git_metadata_snapshot=snapshot,
                    )

            self.assertEqual(first.read_text(encoding="utf-8"), "first operator data\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "second operator data\n")

    def test_checkpoint_replace_restores_workspace_when_install_rename_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            fake, _run_root = fake_orchestrator(
                root,
                source,
                "run-one",
                lambda **_kwargs: {"name": "clawpatch", "ok": True, "exit_code": 0},
            )
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "*.cache\n", encoding="utf-8"
            )
            first = fake.workspace / "first.cache"
            second = fake.workspace / "second.cache"
            first.write_text("first operator data\n", encoding="utf-8")
            second.write_text("second operator data\n", encoding="utf-8")
            ignored_state = _ignored_state(fake, {"first.cache", "second.cache"})
            snapshot = _git_metadata_snapshot(fake)
            baseline = fake.mirror.head()
            real_rename = os.rename

            def fail_staged_install(source_path, destination_path):
                if (
                    Path(source_path).name == "replacement-workspace"
                    and Path(destination_path) == fake.workspace
                ):
                    raise OSError("staged install failed")
                return real_rename(source_path, destination_path)

            with patch(
                "manageroo.external_repair_policy.os.rename",
                side_effect=fail_staged_install,
            ):
                with self.assertRaisesRegex(SafetyError, "workspace replacement failed"):
                    _replace_workspace_from_checkpoint(
                        fake,
                        name="clawpatch",
                        checkpoint=baseline,
                        preserved_ignored_state=ignored_state,
                        git_metadata_snapshot=snapshot,
                    )

            self.assertTrue(fake.workspace.is_dir())
            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(first.read_text(encoding="utf-8"), "first operator data\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "second operator data\n")
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_incomplete_legacy_success_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)

            def command(**_kwargs):
                self.fail("legacy success report must not rerun or bypass validation")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            fake._artifact_json = lambda relative: (
                {
                    "summary": {"continuation_safe": True, "failed": []},
                    "records": [],
                }
                if relative == "review/external-review-repair.json"
                else None
            )

            with self.assertRaisesRegex(SafetyError, "no resume identity"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

    def test_persisted_success_restores_exact_final_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = {"count": 0}
            holder = {}

            def command(**_kwargs):
                calls["count"] += 1
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("repaired\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            result = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            baseline = result["records"][0]["baseline"]
            checkpoint = result["records"][0]["checkpoint"]
            report_path = run_root / "artifacts" / "review" / "external-review-repair.json"

            git(fake.workspace, "reset", "--hard", baseline)
            fake._artifact_json = lambda relative: (
                read_json(report_path) if relative == "review/external-review-repair.json" else None
            )
            resumed = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )

            self.assertEqual(calls["count"], 1)
            self.assertEqual(resumed["records"][0]["checkpoint"], checkpoint)
            self.assertEqual(fake.mirror.head(), checkpoint)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "repaired\n"
            )
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_checkpoint_restore_quarantines_concurrent_path_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "new.txt").write_text("checkpoint data\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            result = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["new.txt"]}]},
                gate_results=[],
            )
            baseline = result["records"][0]["baseline"]
            checkpoint = result["records"][0]["checkpoint"]
            report_path = run_root / "artifacts" / "review" / "external-review-repair.json"

            git(fake.workspace, "reset", "--hard", baseline)
            fake._artifact_json = lambda relative: (
                read_json(report_path) if relative == "review/external-review-repair.json" else None
            )
            real_run = fake.runner.run
            interleaved = {"done": False}

            def create_before_reset(argv, **kwargs):
                if (
                    not interleaved["done"]
                    and list(argv[:3]) == ["git", "reset", "--hard"]
                    and list(argv[3:]) == [checkpoint]
                ):
                    (fake.workspace / "new.txt").write_text(
                        "concurrent data\n", encoding="utf-8"
                    )
                    interleaved["done"] = True
                return real_run(argv, **kwargs)

            with patch.object(fake.runner, "run", side_effect=create_before_reset):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["new.txt"]}]},
                    gate_results=[],
                )

            quarantined = list(
                (
                    run_root
                    / "artifacts"
                    / "review"
                    / "external-state"
                    / "workspace-quarantine"
                ).glob("*/previous-workspace/new.txt")
            )
            self.assertTrue(interleaved["done"])
            self.assertEqual(
                (fake.workspace / "new.txt").read_text(encoding="utf-8"),
                "checkpoint data\n",
            )
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(
                quarantined[0].read_text(encoding="utf-8"), "concurrent data\n"
            )

    def test_persisted_success_with_preexisting_ignored_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = {"count": 0}
            holder = {}

            def command(**_kwargs):
                calls["count"] += 1
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("repaired\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "preexisting.cache\n", encoding="utf-8"
            )
            preexisting = fake.workspace / "preexisting.cache"
            preexisting.write_text("operator data\n", encoding="utf-8")

            result = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            baseline = result["records"][0]["baseline"]
            checkpoint = result["records"][0]["checkpoint"]
            report_path = run_root / "artifacts" / "review" / "external-review-repair.json"

            git(fake.workspace, "reset", "--hard", baseline)
            fake._artifact_json = lambda relative: (
                read_json(report_path) if relative == "review/external-review-repair.json" else None
            )
            preexisting.write_text("operator mutation\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyError, "ignored workspace data changed"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )
            self.assertEqual(fake.mirror.head(), baseline)

            preexisting.write_text("operator data\n", encoding="utf-8")
            resumed = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )

            self.assertEqual(calls["count"], 1)
            self.assertEqual(resumed["records"][0]["checkpoint"], checkpoint)
            self.assertEqual(fake.mirror.head(), checkpoint)
            self.assertEqual(preexisting.read_text(encoding="utf-8"), "operator data\n")
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_interrupted_final_report_write_resumes_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = {"count": 0}
            holder = {}

            def command(**_kwargs):
                calls["count"] += 1
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("repaired\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            write_json = fake.artifacts.write_json

            def interrupt_final_report(relative, data, **kwargs):
                if relative == "review/external-review-repair.json":
                    raise OSError("final report write interrupted")
                return write_json(relative, data, **kwargs)

            with patch.object(fake.artifacts, "write_json", side_effect=interrupt_final_report):
                with self.assertRaisesRegex(OSError, "final report write interrupted"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            manifest_path = (
                run_root
                / "artifacts"
                / "review"
                / "external-state"
                / "clawpatch-checkpoint.json"
            )
            checkpoint = read_json(manifest_path)["checkpoint"]
            self.assertEqual(fake.mirror.head(), checkpoint)

            (fake.workspace / "tracked.txt").write_text(
                "operator mutation\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(SafetyError, "requires a clean workspace"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )
            self.assertEqual(calls["count"], 1)
            self.assertEqual(fake.mirror.head(), checkpoint)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"),
                "operator mutation\n",
            )

            git(fake.workspace, "reset", "--hard", checkpoint)
            resumed = run_external_review_repair_lanes(
                fake,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )

            self.assertEqual(calls["count"], 1)
            self.assertTrue(resumed["records"][0]["resumed_from_checkpoint"])
            self.assertEqual(resumed["records"][0]["checkpoint"], checkpoint)
            self.assertEqual(fake.mirror.head(), checkpoint)

    def test_command_exception_restores_exact_clean_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                (workspace / "untracked.txt").write_text("untracked mutation\n", encoding="utf-8")
                raise RuntimeError("command crashed")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()

            with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertFalse((fake.workspace / "untracked.txt").exists())
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_rollback_quarantines_concurrent_cleanup_candidate_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "untracked.txt").write_text(
                    "lane residue\n", encoding="utf-8"
                )
                raise RuntimeError("command crashed")

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()
            real_run = fake.runner.run
            interleaved = {"done": False}

            def replace_before_reset(argv, **kwargs):
                if (
                    not interleaved["done"]
                    and list(argv[:3]) == ["git", "reset", "--hard"]
                    and list(argv[3:]) == [baseline]
                ):
                    (fake.workspace / "untracked.txt").write_text(
                        "concurrent data\n", encoding="utf-8"
                    )
                    interleaved["done"] = True
                return real_run(argv, **kwargs)

            with patch.object(fake.runner, "run", side_effect=replace_before_reset):
                with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            quarantined = list(
                (
                    run_root
                    / "artifacts"
                    / "review"
                    / "external-state"
                    / "workspace-quarantine"
                ).glob("*/previous-workspace/untracked.txt")
            )
            self.assertTrue(interleaved["done"])
            self.assertFalse((fake.workspace / "untracked.txt").exists())
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(
                quarantined[0].read_text(encoding="utf-8"), "concurrent data\n"
            )

    def test_command_exception_preserves_preexisting_ignored_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                (workspace / "created.cache").write_text("lane residue\n", encoding="utf-8")
                (workspace / "untracked.txt").write_text("lane residue\n", encoding="utf-8")
                raise RuntimeError("command crashed")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "preexisting.cache\ncreated.cache\n", encoding="utf-8"
            )
            preexisting = fake.workspace / "preexisting.cache"
            preexisting.write_text("operator data\n", encoding="utf-8")

            with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(preexisting.read_text(encoding="utf-8"), "operator data\n")
            self.assertFalse((fake.workspace / "created.cache").exists())
            self.assertFalse((fake.workspace / "untracked.txt").exists())
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_command_exception_detects_mutated_preexisting_ignored_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "preexisting.cache").write_text(
                    "corrupted operator data\n", encoding="utf-8"
                )
                raise RuntimeError("command crashed")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "preexisting.cache\n", encoding="utf-8"
            )
            preexisting = fake.workspace / "preexisting.cache"
            preexisting.write_text("operator data\n", encoding="utf-8")

            with self.assertRaisesRegex(SafetyError, "Workspace state is uncertain"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(
                preexisting.read_text(encoding="utf-8"), "corrupted operator data\n"
            )

    def test_command_exception_detects_mutated_preexisting_ignored_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                preexisting = holder["fake"].workspace / "preexisting.cache"
                preexisting.unlink()
                preexisting.symlink_to("corrupted-target")
                raise RuntimeError("command crashed")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            (fake.workspace / ".git" / "info" / "exclude").write_text(
                "preexisting.cache\n", encoding="utf-8"
            )
            preexisting = fake.workspace / "preexisting.cache"
            try:
                preexisting.symlink_to("operator-target")
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaisesRegex(SafetyError, "Workspace state is uncertain"):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(preexisting.readlink(), Path("corrupted-target"))

    def test_failed_reset_does_not_run_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                (workspace / "untracked.txt").write_text("operator data\n", encoding="utf-8")
                raise RuntimeError("command crashed")

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            real_run = fake.runner.run
            calls = []

            def fail_reset(argv, **kwargs):
                calls.append(list(argv))
                if list(argv[:3]) == ["git", "reset", "--hard"]:
                    return SimpleNamespace(passed=False, stdout="", stderr="reset failed")
                return real_run(argv, **kwargs)

            with patch.object(fake.runner, "run", side_effect=fail_reset):
                with self.assertRaisesRegex(SafetyError, "Workspace state is uncertain"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertTrue((fake.workspace / "untracked.txt").is_file())
            self.assertFalse(any(argv[:3] == ["git", "clean", "-fdx"] for argv in calls))

    def test_checkpoint_path_inspection_failure_restores_exact_clean_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()

            with patch(
                "manageroo.external_repair_policy._actual_checkpoint_paths",
                side_effect=SafetyError("checkpoint path inspection failed"),
            ):
                with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_checkpoint_race_rejects_out_of_scope_paths_and_restores_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()
            checkpoint = fake.mirror.checkpoint

            def racing_checkpoint(message, **kwargs):
                (fake.workspace / "forbidden.txt").write_text(
                    "concurrent mutation\n", encoding="utf-8"
                )
                return checkpoint(message, **kwargs)

            with patch.object(fake.mirror, "checkpoint", side_effect=racing_checkpoint):
                with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertFalse((fake.workspace / "forbidden.txt").exists())
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )
            self.assertFalse(
                (run_root / "artifacts" / "review" / "external-review-repair.json").exists()
            )
            self.assertFalse(
                (
                    run_root
                    / "artifacts"
                    / "review"
                    / "external-state"
                    / "clawpatch-checkpoint.json"
                ).exists()
            )

    def test_checkpoint_race_rejects_same_path_mutation_and_restores_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()
            checkpoint = fake.mirror.checkpoint

            def racing_checkpoint(message, **kwargs):
                (fake.workspace / "tracked.txt").write_text(
                    "concurrent mutation\n", encoding="utf-8"
                )
                return checkpoint(message, **kwargs)

            with patch.object(fake.mirror, "checkpoint", side_effect=racing_checkpoint):
                with self.assertRaisesRegex(
                    SafetyError, "content changed during checkpoint creation"
                ):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )
            self.assertFalse(
                (run_root / "artifacts" / "review" / "external-review-repair.json").exists()
            )
            self.assertFalse(
                (
                    run_root
                    / "artifacts"
                    / "review"
                    / "external-state"
                    / "clawpatch-checkpoint.json"
                ).exists()
            )

    def test_checkpoint_manifest_write_failure_restores_exact_clean_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()

            with patch(
                "manageroo.external_repair_policy.atomic_write_json",
                side_effect=OSError("manifest write failed"),
            ):
                with self.assertRaisesRegex(SafetyError, "rollback was verified"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual(
                (fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n"
            )
            self.assertEqual(
                git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), ""
            )

    def test_out_of_scope_failure_restores_exact_clean_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                (workspace / "forbidden.txt").write_text("forbidden mutation\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()

            with self.assertRaises(ValidationError):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual((fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n")
            self.assertFalse((fake.workspace / "forbidden.txt").exists())
            self.assertEqual(git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), "")
            report = __import__("json").loads(
                (run_root / "artifacts" / "review" / "external-review-repair.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["summary"]["continuation_safe"])
            self.assertTrue(report["records"][0]["rollback_verified"])

    def test_unverified_rollback_suppresses_later_repair_lanes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = []

            def command(*, name, **_kwargs):
                calls.append(name)
                return {"name": name, "ok": False, "exit_code": 1}

            fake, _run_root = fake_orchestrator(root, source, "run-one", command)
            fake._external_review_repair_commands = lambda: [
                ("first", ["fake-first"]),
                ("second", ["fake-second"]),
            ]

            with patch(
                "manageroo.external_repair_policy._rollback_lane",
                side_effect=SafetyError("rollback could not be verified"),
            ):
                with self.assertRaisesRegex(SafetyError, "Workspace state is uncertain"):
                    run_external_review_repair_lanes(
                        fake,
                        brief="repair",
                        plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                        gate_results=[],
                    )

            self.assertEqual(calls, ["first"])

    def test_checkpoint_manifest_from_other_run_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = {"count": 0}
            holder = {}

            def command(**_kwargs):
                calls["count"] += 1
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text(f"run {calls['count']}\n", encoding="utf-8")
                return {"name": "clawpatch", "ok": True, "exit_code": 0}

            first, first_root = fake_orchestrator(root, source, "first-run", command)
            holder["fake"] = first
            first_result = run_external_review_repair_lanes(
                first,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            first_checkpoint = first_result["records"][0]["checkpoint"]
            self.assertEqual(calls["count"], 1)

            second, second_root = fake_orchestrator(root, source, "second-run", command)
            holder["fake"] = second
            state = second_root / "artifacts" / "review" / "external-state"
            state.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                state / "clawpatch-checkpoint.json",
                {
                    "run_id": "first-run",
                    "name": "clawpatch",
                    "baseline": second.mirror.head(),
                    "checkpoint": first_checkpoint,
                    "changed_paths": ["tracked.txt"],
                },
            )

            result = run_external_review_repair_lanes(
                second,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            self.assertEqual(calls["count"], 2)
            self.assertFalse(result["records"][0].get("resumed_from_checkpoint", False))


if __name__ == "__main__":
    unittest.main()
