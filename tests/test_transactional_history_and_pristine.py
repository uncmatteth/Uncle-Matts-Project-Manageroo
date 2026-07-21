import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.transactional import TransactionalAdapter
from manageroo.errors import SafetyError
from manageroo.runner import CommandRunner


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def repo_fixture(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Manageroo Tests")
    git(repo, "config", "user.email", "tests@local.invalid")
    git(repo, "config", "commit.gpgSign", "false")
    git(repo, "config", "tag.gpgSign", "false")
    git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / ".gitignore").write_text("ignored-cache/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")
    return repo


def request(repo: Path, *, sandbox: str = "read-only") -> AgentRequest:
    packet = repo.parent / "packet"
    packet.mkdir(exist_ok=True)
    prompt = packet / "prompt.md"
    schema = packet / "schema.json"
    output = packet / "output.json"
    prompt.write_text("bounded job", encoding="utf-8")
    schema.write_text('{"type":"object"}', encoding="utf-8")
    return AgentRequest(
        role="test",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=repo,
        sandbox=sandbox,
        timeout_seconds=30,
    )


class _CommitWorker(AgentAdapter):
    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        (request.cwd / "tracked.txt").write_text("worker commit\n", encoding="utf-8")
        git(request.cwd, "add", "tracked.txt")
        git(request.cwd, "commit", "-q", "-m", "worker must not own this commit")
        return AgentResponse(request.role, {"ok": True}, '{"ok":true}', ["worker"])


class _NeverRunWorker(AgentAdapter):
    def __init__(self):
        self.called = False

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        self.called = True
        raise AssertionError("dirty workspace should be rejected before worker launch")


class TransactionalHistoryAndPristineTests(unittest.TestCase):
    def test_read_only_worker_commit_is_rejected_and_original_head_and_branch_ref_are_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = repo_fixture(Path(temp))
            original_head = git(repo, "rev-parse", "HEAD")
            adapter = TransactionalAdapter(_CommitWorker(), CommandRunner())
            with self.assertRaisesRegex(SafetyError, "mutated repository state or Git history"):
                adapter.run(request(repo, sandbox="read-only"))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), original_head)
            self.assertEqual(git(repo, "rev-parse", "refs/heads/main"), original_head)
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "baseline\n")
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored"), "")

    def test_preexisting_dirty_tracked_untracked_and_ignored_state_is_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = repo_fixture(Path(temp))
            (repo / "tracked.txt").write_text("operator edit\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("operator untracked\n", encoding="utf-8")
            ignored = repo / "ignored-cache" / "operator.txt"
            ignored.parent.mkdir()
            ignored.write_text("operator ignored\n", encoding="utf-8")
            before_status = git(repo, "status", "--porcelain", "--ignored")
            before = {
                "tracked": (repo / "tracked.txt").read_bytes(),
                "untracked": (repo / "untracked.txt").read_bytes(),
                "ignored": ignored.read_bytes(),
            }
            worker = _NeverRunWorker()
            adapter = TransactionalAdapter(worker, CommandRunner())
            with self.assertRaisesRegex(SafetyError, "pristine disposable Git workspace"):
                adapter.run(request(repo, sandbox="workspace-write"))
            self.assertFalse(worker.called)
            self.assertEqual((repo / "tracked.txt").read_bytes(), before["tracked"])
            self.assertEqual((repo / "untracked.txt").read_bytes(), before["untracked"])
            self.assertEqual(ignored.read_bytes(), before["ignored"])
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored"), before_status)


if __name__ == "__main__":
    unittest.main()
