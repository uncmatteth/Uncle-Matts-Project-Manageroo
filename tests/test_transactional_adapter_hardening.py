import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.transactional import TransactionalAdapter
from manageroo.errors import AgentExecutionError, SafetyError
from manageroo.runner import CommandRunner


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


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Manageroo Tests")
    git(repo, "config", "user.email", "tests@local.invalid")
    git(repo, "config", "commit.gpgSign", "false")
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def request(repo: Path, sandbox: str) -> AgentRequest:
    packet = repo.parent / "packet"
    packet.mkdir(exist_ok=True)
    prompt = packet / "prompt.md"
    schema = packet / "schema.json"
    output = packet / "output.json"
    prompt.write_text("job\n", encoding="utf-8")
    schema.write_text('{"type":"object"}\n', encoding="utf-8")
    return AgentRequest(
        role="tester",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=repo,
        sandbox=sandbox,
        timeout_seconds=60,
    )


class CommitMutationWorker(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, req: AgentRequest):
        (req.cwd / "tracked.txt").write_text("committed mutation\n", encoding="utf-8")
        git(req.cwd, "add", "tracked.txt")
        git(req.cwd, "commit", "-q", "-m", "worker-owned commit")
        return AgentResponse(role=req.role, data={"ok": True}, raw_text="{}", command=["fake"])


class FailingWorker(AgentAdapter):
    def __init__(self):
        self.called = False

    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, req: AgentRequest):
        self.called = True
        raise AgentExecutionError("should never run on a dirty non-disposable workspace")


class TransactionalAdapterHardeningTests(unittest.TestCase):
    def test_read_only_committed_mutation_is_rejected_and_head_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_repo(Path(temp))
            original_head = git(repo, "rev-parse", "HEAD")
            adapter = TransactionalAdapter(CommitMutationWorker(), CommandRunner())
            with self.assertRaises(SafetyError):
                adapter.run(request(repo, "read-only"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), original_head)
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "clean\n")
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored"), "")
            self.assertNotIn("worker-owned commit", git(repo, "log", "--oneline", "--all"))

    def test_dirty_preexisting_state_is_preserved_by_refusing_worker_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_repo(Path(temp))
            (repo / "tracked.txt").write_text("preexisting tracked edit\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("preexisting untracked\n", encoding="utf-8")
            ignored = repo / "ignored" / "state.txt"
            ignored.parent.mkdir()
            ignored.write_text("preexisting ignored\n", encoding="utf-8")
            before_status = git(repo, "status", "--porcelain", "--ignored")
            worker = FailingWorker()
            adapter = TransactionalAdapter(worker, CommandRunner())

            with self.assertRaises(SafetyError):
                adapter.run(request(repo, "workspace-write"))

            self.assertFalse(worker.called)
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "preexisting tracked edit\n")
            self.assertEqual((repo / "untracked.txt").read_text(encoding="utf-8"), "preexisting untracked\n")
            self.assertEqual(ignored.read_text(encoding="utf-8"), "preexisting ignored\n")
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored"), before_status)


if __name__ == "__main__":
    unittest.main()
