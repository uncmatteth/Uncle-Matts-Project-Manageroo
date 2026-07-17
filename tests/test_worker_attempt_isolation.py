import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.transactional import TransactionalAdapter
from manageroo.errors import AgentExecutionError, SafetyError
from manageroo.jobs import JobStore
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json
from manageroo.workspace import WorkspaceMirror


class _DirtyFailure(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, request: AgentRequest):
        (request.cwd / "tracked.txt").write_text("poisoned\n", encoding="utf-8")
        (request.cwd / "untracked.txt").write_text("poisoned\n", encoding="utf-8")
        ignored = request.cwd / "ignored-cache" / "poison.txt"
        ignored.parent.mkdir()
        ignored.write_text("poisoned\n", encoding="utf-8")
        request.output_path.write_text("not valid worker output", encoding="utf-8")
        request.output_path.with_suffix(".validated.json").write_text("stale", encoding="utf-8")
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


class _IgnoredSuccess(AgentAdapter):
    def doctor(self, cwd: Path):
        return {"ok": True}

    def run(self, request: AgentRequest):
        ignored = request.cwd / "ignored-cache" / "hidden.txt"
        ignored.parent.mkdir()
        ignored.write_text("hidden mutation\n", encoding="utf-8")
        return AgentResponse(
            role=request.role,
            data={"ok": True},
            raw_text='{"ok": true}',
            command=["ignored-worker"],
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
    (repo / ".gitignore").write_text("ignored-cache/\n", encoding="utf-8")
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


def _run_request(run_root: Path, workspace: Path) -> AgentRequest:
    packet = run_root / "packets" / "001-implementer" / "001"
    packet.mkdir(parents=True, exist_ok=True)
    prompt = packet / "prompt.md"
    schema = packet / "schema.json"
    output = run_root / "agent-output" / "001-implementer" / "001.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("job", encoding="utf-8")
    schema.write_text('{"type":"object"}', encoding="utf-8")
    return AgentRequest(
        role="implementer",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=workspace,
        sandbox="workspace-write",
        timeout_seconds=60,
    )


def _record_completed_write_job(run_root: Path) -> None:
    store = JobStore(run_root)
    job = store.create_or_load_job(
        "001-implementer",
        role="implementer",
        schema="agent-result.schema.json",
        instructions="bounded write",
        sandbox="workspace-write",
    )
    attempt = store.begin_attempt(job.id)
    output = run_root / "worker-output.json"
    data = {"status": "implemented"}
    atomic_write_json(output, data)
    store.complete_attempt(
        job.id,
        attempt.attempt_id,
        output_path=output,
        data=data,
        command=["worker"],
    )
    artifact = run_root / "artifacts" / "agent" / "001-implementer.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(artifact, data)
    store.complete_job(
        job.id,
        output_artifact="agent/001-implementer.json",
        data=data,
        artifact_path=artifact,
    )
    atomic_write_json(
        run_root / "controller" / "pending-workspace-validation.json",
        {
            "job_id": job.id,
            "role": "implementer",
            "sandbox": "workspace-write",
        },
    )


class WorkerAttemptIsolationTests(unittest.TestCase):
    def test_failed_transactional_worker_cannot_poison_next_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            request = _request(repo)
            adapter = TransactionalAdapter(_DirtyFailure(), CommandRunner())
            with self.assertRaises(AgentExecutionError):
                adapter.run(request)
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "clean\n")
            self.assertFalse((repo / "untracked.txt").exists())
            self.assertFalse((repo / "ignored-cache").exists())
            self.assertFalse(request.output_path.exists())
            self.assertFalse(request.output_path.with_suffix(".validated.json").exists())

    def test_read_only_worker_mutation_is_rolled_back_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            adapter = TransactionalAdapter(_DirtySuccess(), CommandRunner())
            with self.assertRaises(SafetyError):
                adapter.run(_request(repo, sandbox="read-only"))
            self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "clean\n")

    def test_read_only_ignored_mutation_is_detected_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            adapter = TransactionalAdapter(_IgnoredSuccess(), CommandRunner())
            with self.assertRaises(SafetyError):
                adapter.run(_request(repo, sandbox="read-only"))
            self.assertFalse((repo / "ignored-cache").exists())

    def test_successful_write_discards_ignored_state_before_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_repo(Path(temp))
            adapter = TransactionalAdapter(_IgnoredSuccess(), CommandRunner())
            response = adapter.run(_request(repo, sandbox="workspace-write"))
            self.assertTrue(response.data["ok"])
            self.assertFalse((repo / "ignored-cache").exists())

    def test_successful_write_attempt_marks_pending_controller_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _git_repo(root)
            run_root = root / "run" / "marker-test"
            run_root.mkdir(parents=True)
            mirror = WorkspaceMirror(source, run_root, CommandRunner())
            workspace = mirror.create()
            request = _run_request(run_root, workspace)

            TransactionalAdapter(_DirtySuccess(), CommandRunner()).run(request)

            marker = run_root / "controller" / "pending-workspace-validation.json"
            self.assertTrue(marker.is_file())
            payload = __import__("json").loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["job_id"], "001-implementer")
            self.assertEqual(payload["sandbox"], "workspace-write")

    def test_resume_discards_unowned_uncheckpointed_workspace_changes(self):
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
            ignored = workspace / "ignored-cache" / "resume.txt"
            ignored.parent.mkdir()
            ignored.write_text("unverified\n", encoding="utf-8")

            resumed = WorkspaceMirror(source, run_root, CommandRunner())
            resumed.load_existing()
            self.assertTrue((workspace / "verified.txt").is_file())
            self.assertEqual((workspace / "tracked.txt").read_text(encoding="utf-8"), "clean\n")
            self.assertFalse((workspace / "junk.txt").exists())
            self.assertFalse((workspace / "ignored-cache").exists())

    def test_resume_preserves_completed_write_job_edits_but_removes_ignored_residue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _git_repo(root)
            run_root = root / "run" / "resume-write-window"
            run_root.mkdir(parents=True)
            mirror = WorkspaceMirror(source, run_root, CommandRunner())
            workspace = mirror.create()
            _record_completed_write_job(run_root)

            (workspace / "tracked.txt").write_text("worker-result-awaiting-validation\n", encoding="utf-8")
            (workspace / "new-result.txt").write_text("worker-result\n", encoding="utf-8")
            ignored = workspace / "ignored-cache" / "hidden.txt"
            ignored.parent.mkdir()
            ignored.write_text("hidden\n", encoding="utf-8")

            resumed = WorkspaceMirror(source, run_root, CommandRunner())
            resumed.load_existing()
            self.assertEqual(
                (workspace / "tracked.txt").read_text(encoding="utf-8"),
                "worker-result-awaiting-validation\n",
            )
            self.assertTrue((workspace / "new-result.txt").is_file())
            self.assertFalse((workspace / "ignored-cache").exists())

    def test_checkpoint_clears_pending_validation_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = _git_repo(root)
            run_root = root / "run" / "marker-clear"
            run_root.mkdir(parents=True)
            mirror = WorkspaceMirror(source, run_root, CommandRunner())
            workspace = mirror.create()
            marker = run_root / "controller" / "pending-workspace-validation.json"
            atomic_write_json(
                marker,
                {"job_id": "001-implementer", "sandbox": "workspace-write"},
            )
            (workspace / "tracked.txt").write_text("validated\n", encoding="utf-8")

            mirror.checkpoint("validated controller checkpoint")
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
