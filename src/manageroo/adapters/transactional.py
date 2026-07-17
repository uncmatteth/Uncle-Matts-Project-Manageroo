from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import SafetyError
from ..runner import CommandRunner
from ..util import atomic_write_json, utc_now


class TransactionalAdapter(AgentAdapter):
    """Rollback failed attempts and protect controller-owned run truth.

    Successful write-worker edits remain available for Manageroo's controller-owned
    scope, gate, review, and checkpoint logic. A worker that crashes, violates the
    output protocol, mutates a read-only repository, or tampers with critical run-state
    files cannot poison later work.
    """

    def __init__(self, inner: AgentAdapter, runner: CommandRunner):
        self.inner = inner
        self.runner = runner

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["transactional_attempts"] = True
        result["read_only_mutation_enforced"] = True
        result["critical_controller_truth_guard"] = True
        return result

    def _head(self, cwd: Path) -> str:
        result = self.runner.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise SafetyError(
                "Manageroo could not capture the worker-attempt Git checkpoint: "
                + result.stderr
            )
        return result.stdout.strip()

    def _dirty(self, cwd: Path) -> bool:
        result = self.runner.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise SafetyError(
                "Manageroo could not verify worker-attempt repository state: " + result.stderr
            )
        return bool(result.stdout.strip())

    def _rollback(self, cwd: Path, head: str) -> None:
        reset = self.runner.run(
            ["git", "reset", "--hard", head],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not reset.passed:
            raise SafetyError(
                "Failed worker attempt could not be rolled back safely: " + reset.stderr
            )
        clean = self.runner.run(
            ["git", "clean", "-fd"],
            cwd=cwd,
            timeout_seconds=120,
        )
        if not clean.passed:
            raise SafetyError(
                "Failed worker attempt left untracked repository files that could not be removed: "
                + clean.stderr
            )

    def _discard_failed_outputs(self, request: AgentRequest) -> None:
        candidates = [
            request.output_path,
            request.output_path.with_suffix(".validated.json"),
        ]
        for path in candidates:
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise SafetyError(
                    f"Failed worker output could not be discarded safely: {path}: {exc}"
                ) from exc

    def _rollback_failed_attempt(self, request: AgentRequest, head: str) -> None:
        self._rollback(request.cwd, head)
        self._discard_failed_outputs(request)

    def _run_location(self, request: AgentRequest) -> tuple[Path, str, str] | None:
        output_parent = request.output_path.parent
        agent_output_root = output_parent.parent
        if agent_output_root.name != "agent-output":
            return None
        return agent_output_root.parent, output_parent.name, request.output_path.stem

    def _pending_validation_marker(self, request: AgentRequest) -> Path | None:
        location = self._run_location(request)
        if location is None:
            return None
        run_root, _, _ = location
        return run_root / "controller" / "pending-workspace-validation.json"

    def _protected_controller_paths(self, request: AgentRequest) -> list[Path]:
        location = self._run_location(request)
        if location is None:
            return []
        run_root, job_id, attempt_id = location
        return [
            run_root / "state.json",
            run_root / "source-snapshot.json",
            run_root / "controller" / "truth.json",
            run_root / "controller" / "phase-journal.jsonl",
            run_root / "jobs" / f"{job_id}.json",
            run_root / "worker-attempts" / job_id / f"{attempt_id}.json",
        ]

    def _snapshot_controller_truth(self, request: AgentRequest) -> dict[Path, bytes | None]:
        snapshot: dict[Path, bytes | None] = {}
        for path in self._protected_controller_paths(request):
            if path.is_symlink():
                raise SafetyError(f"Controller truth path must not be a symlink: {path}")
            snapshot[path] = path.read_bytes() if path.is_file() else None
        return snapshot

    def _restore_controller_truth(self, snapshot: dict[Path, bytes | None]) -> list[str]:
        changed: list[str] = []
        for path, expected in snapshot.items():
            current = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            current_exists = path.exists() or path.is_symlink()
            if expected is None and not current_exists:
                continue
            if expected is not None and current == expected and not path.is_symlink():
                continue
            changed.append(str(path))
            try:
                if expected is None:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                else:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    elif path.is_symlink():
                        path.unlink()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(expected)
            except OSError as exc:
                raise SafetyError(
                    f"Critical controller truth changed and could not be restored: {path}: {exc}"
                ) from exc
        return changed

    def _mark_pending_write_validation(self, request: AgentRequest, head: str) -> None:
        marker = self._pending_validation_marker(request)
        location = self._run_location(request)
        if marker is None or location is None:
            return
        _, job_id, _ = location
        atomic_write_json(
            marker,
            {
                "job_id": job_id,
                "role": request.role,
                "sandbox": request.sandbox,
                "pre_attempt_head": head,
                "output_path": str(request.output_path),
                "created_at": utc_now(),
            },
        )

    def run(self, request: AgentRequest) -> AgentResponse:
        head = self._head(request.cwd)
        truth_snapshot = self._snapshot_controller_truth(request)
        try:
            response = self.inner.run(request)
        except Exception as exc:
            changed_truth = self._restore_controller_truth(truth_snapshot)
            self._rollback_failed_attempt(request, head)
            if changed_truth:
                raise SafetyError(
                    "Worker modified critical Manageroo controller truth; changes were restored: "
                    + ", ".join(changed_truth)
                ) from exc
            raise

        changed_truth = self._restore_controller_truth(truth_snapshot)
        if changed_truth:
            self._rollback_failed_attempt(request, head)
            raise SafetyError(
                "Worker modified critical Manageroo controller truth; changes were restored: "
                + ", ".join(changed_truth)
            )

        if request.sandbox == "read-only":
            try:
                dirty = self._dirty(request.cwd)
            except SafetyError:
                self._rollback_failed_attempt(request, head)
                raise
            if dirty:
                self._rollback_failed_attempt(request, head)
                raise SafetyError(
                    f"Read-only worker {request.role!r} mutated its repository; edits were discarded."
                )
        elif request.sandbox == "workspace-write":
            self._mark_pending_write_validation(request, head)
        return response
