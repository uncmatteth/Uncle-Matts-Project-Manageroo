import os
import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.runner import CommandRunner
from manageroo.workspace import WorkspaceMirror


class WorkspaceTests(unittest.TestCase):
    def _repo(self, root: Path) -> tuple[Path, CommandRunner]:
        repo = root / "repo"
        repo.mkdir()
        runner = CommandRunner()
        commands = [
            ["git", "init", "-b", "main"],
            ["git", "config", "user.name", "Test"],
            ["git", "config", "user.email", "test@example.invalid"],
        ]
        for command in commands:
            self.assertTrue(runner.run(command, cwd=repo).passed)
        (repo / "a.txt").write_text("before\n", encoding="utf-8")
        self.assertTrue(runner.run(["git", "add", "-A"], cwd=repo).passed)
        self.assertTrue(runner.run(["git", "commit", "-m", "base"], cwd=repo).passed)
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

            existing_inside = mirror.run_root / "review-existing"
            existing_inside.mkdir()
            inside_sentinel = existing_inside / "sentinel.txt"
            inside_sentinel.write_text("keep\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                mirror.clone_for_review(existing_inside)
            self.assertEqual(inside_sentinel.read_text(encoding="utf-8"), "keep\n")

            clone = mirror.clone_for_review(mirror.run_root / "review-fresh")
            self.assertTrue((clone / ".git").is_dir())

    def test_mode_only_source_change_is_detected(self):
        if os.name == "nt":
            self.skipTest("POSIX mode bits are not portable on Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, runner = self._repo(root)
            source = repo / "a.txt"
            source.chmod(0o644)
            mirror = WorkspaceMirror(repo, root / "run", runner)
            mirror.create()
            source.chmod(0o755)
            with self.assertRaises(SafetyError):
                mirror.assert_source_unchanged()


if __name__ == "__main__":
    unittest.main()
