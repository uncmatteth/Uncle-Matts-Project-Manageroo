import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from manageroo.errors import GateFailure
from manageroo.gates import Gate, GateRunner
from manageroo.policy import CommandPolicy
from manageroo.runner import CommandRunner


class GateRunnerTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Gate Test"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "gate@example.invalid"], cwd=repo, check=True
        )
        (repo / "fixture.txt").write_text("original\n", encoding="utf-8")
        subprocess.run(["git", "add", "fixture.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True)
        return repo

    def test_gate_runs_in_disposable_checkout_without_touching_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            runner = GateRunner(
                CommandRunner(root / "logs"),
                CommandPolicy((sys.executable,)),
                root / "logs",
            )
            outcomes = runner.run(
                [Gate("read-only", "test", [sys.executable, "-c", "print('ok')"])],
                repo,
                scratch_root=root / "scratch",
            )
            self.assertTrue(outcomes[0].result.passed)
            self.assertEqual((repo / "fixture.txt").read_text(encoding="utf-8"), "original\n")

    def test_gate_sees_current_git_visible_working_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            (repo / "staged.txt").write_text("committed\n", encoding="utf-8")
            (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.txt", "deleted.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "more fixtures"], cwd=repo, check=True)

            (repo / "fixture.txt").write_text("unstaged\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "add", "staged.txt"], cwd=repo, check=True)
            (repo / "deleted.txt").unlink()
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            runner = GateRunner(
                CommandRunner(root / "logs"),
                CommandPolicy((sys.executable,)),
                root / "logs",
            )
            command = (
                "from pathlib import Path; "
                "current = ("
                "Path('fixture.txt').read_text() == 'unstaged\\n' and "
                "Path('staged.txt').read_text() == 'staged\\n' and "
                "not Path('deleted.txt').exists() and "
                "Path('untracked.txt').read_text() == 'untracked\\n'"
                "); raise SystemExit(1 if current else 0)"
            )

            with self.assertRaisesRegex(GateFailure, "Required gates failed: current-tree"):
                runner.run(
                    [Gate("current-tree", "test", [sys.executable, "-c", command])],
                    repo,
                    scratch_root=root / "scratch",
                )

    def test_gate_mutation_is_rejected_and_discarded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            runner = GateRunner(
                CommandRunner(root / "logs"),
                CommandPolicy((sys.executable,)),
                root / "logs",
            )
            command = (
                "from pathlib import Path; "
                "Path('unauthorized_from_gate.py').write_text('bad\\n', encoding='utf-8')"
            )
            with self.assertRaisesRegex(GateFailure, "mutated its disposable checkout"):
                runner.run(
                    [Gate("mutating", "test", [sys.executable, "-c", command])],
                    repo,
                    scratch_root=root / "scratch",
                )
            self.assertFalse((repo / "unauthorized_from_gate.py").exists())

    def test_nonpositive_gate_timeout_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            runner = GateRunner(
                CommandRunner(root / "logs"),
                CommandPolicy((sys.executable,)),
                root / "logs",
            )
            with self.assertRaisesRegex(GateFailure, "greater than zero"):
                runner.run(
                    [Gate("bad-timeout", "test", [sys.executable, "-c", "print('bad')"], timeout_seconds=-1)],
                    repo,
                    scratch_root=root / "scratch",
                )


if __name__ == "__main__":
    unittest.main()
