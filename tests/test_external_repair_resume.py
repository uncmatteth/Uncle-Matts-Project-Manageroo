import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.external_repair_policy import _existing_checkpoint, _checkpoint_message
from manageroo.runner import CommandRunner


class _Fixture:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.runner = CommandRunner()


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Manageroo Tests"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@local.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    return repo


class ExternalRepairResumeTests(unittest.TestCase):
    def test_existing_unique_checkpoint_reconstructs_changed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _repo(Path(temp))
            (repo / "tracked.txt").write_text("repaired\n", encoding="utf-8")
            (repo / "new.txt").write_text("added\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", _checkpoint_message("autoreview")],
                cwd=repo,
                check=True,
            )

            checkpoint = _existing_checkpoint(_Fixture(repo), "autoreview")
            self.assertIsNotNone(checkpoint)
            commit, paths = checkpoint
            self.assertEqual(len(commit), 40)
            self.assertEqual(paths, ["new.txt", "tracked.txt"])

    def test_missing_checkpoint_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _repo(Path(temp))
            self.assertIsNone(_existing_checkpoint(_Fixture(repo), "clawpatch"))


if __name__ == "__main__":
    unittest.main()
