import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.runner import CommandRunner
from manageroo.workspace import WorkspaceMirror


class WorkspaceTests(unittest.TestCase):
    def test_mirror_and_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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

            mirror = WorkspaceMirror(repo, root / "run", runner)
            workspace = mirror.create()
            (workspace / "a.txt").write_text("after\n", encoding="utf-8")
            mirror.checkpoint("controller")
            patch = mirror.write_patch(root / "final.patch")
            self.assertIn("+after", patch.read_text(encoding="utf-8"))
            mirror.apply_patch_to_source(patch)
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "after\n")

    def test_empty_patch_still_requires_source_to_match_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
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

            mirror = WorkspaceMirror(repo, root / "run", runner)
            mirror.create()
            patch = mirror.write_patch(root / "empty.patch")
            self.assertEqual(patch.read_text(encoding="utf-8"), "")
            self.assertTrue(mirror.delivery_patch_already_applied_cleanly(patch))

            (repo / "outside.txt").write_text("outside edit\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyError, "Source tree does not match approved delivery patch"):
                mirror.delivery_patch_already_applied_cleanly(patch)


if __name__ == "__main__":
    unittest.main()
