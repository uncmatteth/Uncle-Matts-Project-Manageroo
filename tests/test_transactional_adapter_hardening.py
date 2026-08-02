import multiprocessing
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class GitMetadataMutationWorker(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, req: AgentRequest):
        config = req.cwd / ".git" / "config"
        config.write_bytes(
            config.read_bytes()
            + b"\n[remote \"attacker\"]\n\turl = https://example.invalid\n"
        )
        hook = req.cwd / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        return AgentResponse(role=req.role, data={"ok": True}, raw_text="{}", command=["fake"])


class BlockingWriteWorker(AgentAdapter):
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, req: AgentRequest):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release the first transactional worker")
        (req.cwd / "successful-worker.txt").write_text("preserved\n", encoding="utf-8")
        return AgentResponse(role=req.role, data={"ok": True}, raw_text="{}", command=["fake"])


class FailingConcurrentWorker(AgentAdapter):
    def __init__(self, entered):
        self.entered = entered

    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, req: AgentRequest):
        self.entered.set()
        raise AgentExecutionError("concurrent worker should not reach the repository")


class LockObservedTransactionalAdapter(TransactionalAdapter):
    def __init__(self, inner: AgentAdapter, runner: CommandRunner, attempted):
        super().__init__(inner, runner)
        self.attempted = attempted

    def _repository_lock_path(self, cwd: Path) -> Path:
        lock_path = super()._repository_lock_path(cwd)
        self.attempted.set()
        return lock_path


def run_adapter_process(label: str, adapter: TransactionalAdapter, req: AgentRequest, outcomes) -> None:
    try:
        adapter.run(req)
    except BaseException as exc:
        outcomes.put((label, type(exc).__name__, str(exc)))
    else:
        outcomes.put((label, "ok", ""))


def git_metadata(repo: Path) -> dict[str, tuple[int, bytes]]:
    git_dir = repo / ".git"
    return {
        path.relative_to(git_dir).as_posix(): (path.stat().st_mode & 0o777, path.read_bytes())
        for path in git_dir.rglob("*")
        if path.is_file()
    }


class TransactionalAdapterHardeningTests(unittest.TestCase):
    def test_repository_transactions_are_serialized_across_processes(self):
        try:
            process_context = multiprocessing.get_context("fork")
        except ValueError:
            self.skipTest("coordinated repository-lock test requires fork")
        with tempfile.TemporaryDirectory() as temp:
            repo = make_repo(Path(temp))
            first_entered = process_context.Event()
            release_first = process_context.Event()
            second_lock_attempted = process_context.Event()
            second_entered = process_context.Event()
            outcomes = process_context.Queue()
            first = process_context.Process(
                target=run_adapter_process,
                args=(
                    "first",
                    TransactionalAdapter(
                        BlockingWriteWorker(first_entered, release_first), CommandRunner()
                    ),
                    request(repo, "workspace-write"),
                    outcomes,
                ),
            )
            second = process_context.Process(
                target=run_adapter_process,
                args=(
                    "second",
                    LockObservedTransactionalAdapter(
                        FailingConcurrentWorker(second_entered),
                        CommandRunner(),
                        second_lock_attempted,
                    ),
                    request(repo, "workspace-write"),
                    outcomes,
                ),
            )

            first.start()
            self.assertTrue(first_entered.wait(timeout=5))
            second.start()
            self.assertTrue(second_lock_attempted.wait(timeout=5))
            self.assertFalse(second_entered.wait(timeout=0.2))
            release_first.set()
            first.join(timeout=5)
            second.join(timeout=5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(first.exitcode, 0)
            self.assertEqual(second.exitcode, 0)
            results = {item[0]: item[1:] for item in (outcomes.get(), outcomes.get())}
            self.assertEqual(results["first"], ("ok", ""))
            self.assertEqual(results["second"][0], "SafetyError")
            self.assertIn("pristine disposable Git workspace", results["second"][1])
            self.assertFalse(second_entered.is_set())
            self.assertEqual(
                (repo / "successful-worker.txt").read_text(encoding="utf-8"),
                "preserved\n",
            )

    def test_successful_worker_git_metadata_mutation_is_rejected_and_restored(self):
        for sandbox in ("read-only", "workspace-write"):
            with self.subTest(sandbox=sandbox), tempfile.TemporaryDirectory() as temp:
                repo = make_repo(Path(temp))
                before = git_metadata(repo)
                adapter = TransactionalAdapter(GitMetadataMutationWorker(), CommandRunner())

                with self.assertRaisesRegex(SafetyError, "protected Git metadata"):
                    adapter.run(request(repo, sandbox))

                self.assertEqual(git_metadata(repo), before)
                self.assertEqual(git(repo, "status", "--porcelain", "--ignored"), "")

    def test_git_metadata_snapshot_fails_closed_at_file_and_byte_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = make_repo(Path(temp))
            adapter = TransactionalAdapter(FailingWorker(), CommandRunner())

            with mock.patch(
                "manageroo.adapters.transactional.MAX_GIT_METADATA_FILES",
                0,
            ):
                with self.assertRaisesRegex(SafetyError, "file limit"):
                    adapter._snapshot_git_metadata(repo)

            with mock.patch(
                "manageroo.adapters.transactional.MAX_GIT_METADATA_BYTES",
                0,
            ):
                with self.assertRaisesRegex(SafetyError, "byte limit"):
                    adapter._snapshot_git_metadata(repo)

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
