import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from manageroo.artifacts import ArtifactStore
from manageroo.external_repair_policy import _existing_checkpoint
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json


class _Fixture:
    def __init__(self, workspace: Path, run_root: Path, run_id: str):
        self.workspace = workspace
        self.runner = CommandRunner()
        self.run_id = run_id
        self.artifacts = ArtifactStore(run_root / "artifacts")


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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


class ExternalRepairResumeTests(unittest.TestCase):
    def test_existing_run_scoped_checkpoint_reconstructs_changed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = _repo(root)
            baseline = _git(repo, "rev-parse", "HEAD")
            (repo / "tracked.txt").write_text("repaired\n", encoding="utf-8")
            (repo / "new.txt").write_text("added\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "repair"], cwd=repo, check=True)
            checkpoint = _git(repo, "rev-parse", "HEAD")

            run_root = root / "run"
            fixture = _Fixture(repo, run_root, "run-123")
            state = run_root / "artifacts" / "review" / "external-state"
            state.mkdir(parents=True)
            atomic_write_json(
                state / "autoreview-checkpoint.json",
                {
                    "run_id": "run-123",
                    "name": "autoreview",
                    "baseline": baseline,
                    "checkpoint": checkpoint,
                    "changed_paths": ["new.txt", "tracked.txt"],
                },
            )

            resumed = _existing_checkpoint(fixture, "autoreview", baseline=baseline)
            self.assertIsNotNone(resumed)
            commit, paths = resumed
            self.assertEqual(commit, checkpoint)
            self.assertEqual(paths, ["new.txt", "tracked.txt"])

    def test_missing_checkpoint_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = _repo(root)
            baseline = _git(repo, "rev-parse", "HEAD")
            fixture = _Fixture(repo, root / "run", "run-123")
            self.assertIsNone(_existing_checkpoint(fixture, "clawpatch", baseline=baseline))


if __name__ == "__main__":
    unittest.main()
