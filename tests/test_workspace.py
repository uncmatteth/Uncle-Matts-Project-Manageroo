import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.errors import SafetyError
from manageroo.runner import CommandRunner
from manageroo.util import copy_file_preserving_mode
from manageroo.workspace import WorkspaceMirror


class WorkspaceTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, CommandRunner]:
        repo = root / "repo"
        repo.mkdir()
        runner = CommandRunner()
        commands = [
            ["git", "init", "--template=", "-b", "main"],
            ["git", "config", "user.name", "Test"],
            ["git", "config", "user.email", "test@example.invalid"],
            ["git", "config", "commit.gpgSign", "false"],
            ["git", "config", "tag.gpgSign", "false"],
            ["git", "config", "core.hooksPath", "/dev/null"],
        ]
        for command in commands:
            self.assertTrue(runner.run(command, cwd=repo).passed)
        (repo / "a.txt").write_text("before\n", encoding="utf-8")
        self.assertTrue(runner.run(["git", "add", "-A"], cwd=repo).passed)
        self.assertTrue(
            runner.run(
                ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", "base"],
                cwd=repo,
            ).passed
        )
        return repo, runner

    def test_mirror_and_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            workspace = mirror.create()
            (workspace / "a.txt").write_text("after\n", encoding="utf-8")
            mirror.checkpoint("controller")
            patch = mirror.write_patch(root / "final.patch")
            self.assertIn("+after", patch.read_text(encoding="utf-8"))
            mirror.apply_patch_to_source(patch)
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "after\n")

    def test_second_create_does_not_replace_original_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            mirror.create()
            original = mirror.snapshot_path.read_bytes()
            (repo / "a.txt").write_text("source changed\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                mirror.create()
            self.assertEqual(mirror.snapshot_path.read_bytes(), original)

    def test_create_rejects_file_changed_only_while_copying_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)

            def copy_temporary_source(source: Path, destination: Path) -> None:
                source.write_text("temporary concurrent edit\n", encoding="utf-8")
                try:
                    copy_file_preserving_mode(source, destination)
                finally:
                    source.write_text("before\n", encoding="utf-8")

            with patch(
                "manageroo.workspace.copy_file_preserving_mode",
                side_effect=copy_temporary_source,
            ):
                with self.assertRaisesRegex(SafetyError, "does not match source snapshot: a.txt"):
                    mirror.create()

            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "before\n")
            self.assertFalse((mirror.workspace / ".git").exists())

    def test_capture_source_revalidates_inventory_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)

            with patch(
                "manageroo.workspace.git_visible_files",
                return_value=["a.txt", "nested\\file.txt"],
            ):
                with self.assertRaisesRegex(SafetyError, "Unsafe repository-relative path"):
                    mirror.capture_source()

            self.assertFalse(mirror.snapshot_path.exists())

    @unittest.skipIf(os.name == "nt", "literal backslash filenames are not distinct on Windows")
    def test_create_rejects_distinct_paths_that_backslash_normalization_would_collapse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            (repo / "nested").mkdir()
            (repo / "nested" / "file.txt").write_text("slash path\n", encoding="utf-8")
            (repo / "nested\\file.txt").write_text("backslash path\n", encoding="utf-8")
            self.assertTrue(runner.run(["git", "add", "-A"], cwd=repo).passed)
            self.assertTrue(
                runner.run(
                    [
                        "git",
                        "-c",
                        "commit.gpgSign=false",
                        "-c",
                        "core.hooksPath=/dev/null",
                        "commit",
                        "-m",
                        "add distinct paths",
                    ],
                    cwd=repo,
                ).passed
            )

            mirror = WorkspaceMirror(repo, root / "run", runner)
            with self.assertRaisesRegex(SafetyError, "Unsafe repository-relative path"):
                mirror.create()

            self.assertFalse(mirror.snapshot_path.exists())
            self.assertFalse(mirror.workspace.exists())

    def test_clone_for_review_refuses_existing_or_external_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            mirror.create()

            outside = root / "unrelated"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                mirror.clone_for_review(outside)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

            fresh_outside = root / "fresh-unrelated"
            self.assertFalse(fresh_outside.exists())
            with self.assertRaises(SafetyError):
                mirror.clone_for_review(fresh_outside)
            self.assertFalse(fresh_outside.exists())

            existing_inside = mirror.run_root / "review-existing"
            existing_inside.mkdir()
            inside_sentinel = existing_inside / "sentinel.txt"
            inside_sentinel.write_text("keep\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                mirror.clone_for_review(existing_inside)
            self.assertEqual(inside_sentinel.read_text(encoding="utf-8"), "keep\n")

            clone = mirror.clone_for_review(mirror.run_root / "review-fresh")
            self.assertTrue((clone / ".git").is_dir())

    def test_clone_for_review_rejects_symlinked_parent_escape(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            mirror.create()
            outside = root / "outside-review"
            outside.mkdir()
            linked_parent = mirror.run_root / "review-link"
            linked_parent.symlink_to(outside, target_is_directory=True)
            destination = linked_parent / "fresh"
            with self.assertRaises(SafetyError):
                mirror.clone_for_review(destination)
            self.assertFalse((outside / "fresh").exists())

    def test_tracked_symlink_is_rejected_explicitly_during_create(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = repo / "linked.txt"
            link.symlink_to(outside)
            self.assertTrue(runner.run(["git", "add", "linked.txt"], cwd=repo).passed)
            self.assertTrue(
                runner.run(
                    ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "-m", "add link"],
                    cwd=repo,
                ).passed
            )
            mirror = WorkspaceMirror(repo, root / "run", runner)
            with self.assertRaisesRegex(SafetyError, "symlink"):
                mirror.create()
            self.assertFalse(mirror.snapshot_path.exists())

    @unittest.skipIf(os.name == "nt", "executable mode is platform-dependent on Windows")
    def test_pending_state_rejects_untracked_executable_mode_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            workspace = mirror.create()
            script = workspace / "script.sh"
            script.write_text("#!/bin/sh\n", encoding="utf-8")
            script.chmod(0o644)

            head = mirror.head()
            original_digest = mirror._workspace_state_digest(head)
            job_id = "write-job"
            job_path = mirror.run_root / "jobs" / f"{job_id}.json"
            job_path.parent.mkdir(parents=True)
            job_path.write_text(
                json.dumps({"status": "complete", "sandbox": "workspace-write"}),
                encoding="utf-8",
            )
            mirror.pending_validation_path.parent.mkdir(parents=True)
            mirror.pending_validation_path.write_text(
                json.dumps(
                    {
                        "sandbox": "workspace-write",
                        "job_id": job_id,
                        "workspace_state_sha256": original_digest,
                        "pre_attempt_head": head,
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(mirror._completed_write_job_owns_pending_state())

            script.chmod(0o755)

            self.assertNotEqual(mirror._workspace_state_digest(head), original_digest)
            self.assertFalse(mirror._completed_write_job_owns_pending_state())


if __name__ == "__main__":
    unittest.main()
