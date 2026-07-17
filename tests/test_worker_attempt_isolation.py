import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.transactional import TransactionalAdapter
from manageroo.errors import AgentExecutionError, SafetyError
from manageroo.runner import CommandRunner
from manageroo.workspace import WorkspaceMirror


class _DirtyFailure(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, request: AgentRequest):
        (request.cwd / "tracked.txt").write_text("poisoned\n", encoding="utf-8")
        (request.cwd / "untracked.txt").write_text("poisoned\n", encoding="utf-8")
        raise AgentExecutionError("worker died after editing")


class _DirtySuccess(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, request: AgentRequest):
        (request.cwd / "tracked.txt").write_text("poisoned\n", encoding="utf-8")
        return AgentResponse(
            role=request.role,
            data={"ok": True},
            raw_text='{"ok": true}',
            command=["dirty-worker"],
        )


def _git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "MANAGEROO Tests"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@local.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    return repo


def _request(repo: Path, *, sandbox: str = "workspace-write") -> AgentRequest:
    packet = repo.parent / "packet"
    packet.mkdir(exist_ok=True)
    prompt = packet / "prompt.md"
    schema = packet / "schema.json"
    output = packet / "output.json"
    prompt.write_text("job", encoding="utf-8")
    schema.write_text('{"type":"object"}', encoding="utf-8")
    return AgentRequest(
        role="implementer",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=repo,
        sandbox=sandbox,
        timeout_seconds=60,
    )


class WorkerAttemptIsolationTests(unittest.TestCase):
    def test_failed_transactional_worker_cannot_poison_next_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            adapter = TransactionalAdapter(_DirtyFailure(), CommandRunner())
            with self.assertRaises(AgentExecutionError):
                adapter.run(_request(repo))
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "clean\n")
            self.assertFalse((repo / "untracked.txt").exists())

    def test_read_only_worker_mutation_is_rolled_back_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            adapter = TransactionalAdapter(_DirtySuccess(), CommandRunner())
            with self.assertRaises(SafetyError):
                adapter.run(_request(repo, sandbox="read-only"))
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "clean\n")

    def test_resume_discards_only_uncheckpointed_workspace_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _git_repo(root)
            run_root = root / "run" / "resume-test"
            run_root.mkdir(parents=True)
            mirror = WorkspaceMirror(source, run_root, CommandRunner())
            workspace = mirror.create()

            (workspace / "verified.txt").write_text("verified\n", encoding="utf-8")
            mirror.checkpoint("verified controller checkpoint")
            (workspace / "tracked.txt").write_text("unverified\n", encoding="utf-8")
            (workspace / "junk.txt").write_text("unverified\n", encoding="utf-8")

            resumed = WorkspaceMirror(source, run_root, CommandRunner())
            resumed.load_existing()
            self.assertTrue((workspace / "verified.txt").is_file())
            self.assertEqual((workspace / "tracked.txt").read_text(encoding="utf-8"), "clean\n")
            self.assertFalse((workspace / "junk.txt").exists())


if __name__ == "__main__":
    unittest.main()
