from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import SafetyError
from ..runner import CommandRunner
from ..util import atomic_write_json, utc_now


class TransactionalAdapter(AgentAdapter):
    """Rollback failed attempts and protect controller-owned run truth.

    Destructive rollback is permitted only after Manageroo verifies that the assigned
    repository is a pristine disposable workspace. Read-only attempts additionally
    preserve HEAD and refs, not merely the visible working-tree status.
    """

    def __init__(self, inner: AgentAdapter, runner: CommandRunner):
        self.inner = inner
        self.runner = runner

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["transactional_attempts"] = True
        result["read_only_mutation_enforced"] = True
        result["git_history_mutation_enforced"] = True
        result["pristine_workspace_required"] = True
        result["ignored_worker_state_discarded"] = True
        result["critical_controller_truth_guard"] = True
        return result

    def _head(self, cwd: Path) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=cwd, timeout_seconds=30)
        if not result.passed:
            raise SafetyError(
                "Manageroo could not capture the worker-attempt Git checkpoint: " + result.stderr
            )
        return result.stdout.strip()

    def _status(self, cwd: Path, *, include_ignored: bool = False) -> str:
        argv = ["git", "status", "--porcelain", "--untracked-files=all"]
        if include_ignored:
            argv.append("--ignored")
        result = self.runner.run(argv, cwd=cwd, timeout_seconds=30)
        if not result.passed:
            raise SafetyError(
                "Manageroo could not verify worker-attempt repository state: " + result.stderr
            )
        return result.stdout

    def _dirty(self, cwd: Path, *, include_ignored: bool = False) -> bool:
        return bool(self._status(cwd, include_ignored=include_ignored).strip())

    def _assert_pristine_disposable_workspace(self, cwd: Path) -> None:
        status = self._status(cwd, include_ignored=True)
        if status.strip():
            raise SafetyError(
                "Transactional worker execution requires a pristine disposable Git workspace. "
                "Manageroo refused to run because pre-existing tracked, untracked, or ignored state "
                "would make destructive rollback unsafe."
            )

    def _refs(self, cwd: Path) -> dict[str, str]:
        result = self.runner.run(
            ["git", "for-each-ref", "--format=%(refname)%00%(objectname)"],
            cwd=cwd,
            timeout_seconds=30,
        )
        if not result.passed:
            raise SafetyError("Manageroo could not snapshot Git refs: " + result.stderr)
        refs: dict[str, str] = {}
        for line in result.stdout.splitlines():
            name, separator, sha = line.partition("\0")
            if separator and name and sha:
                refs[name] = sha
        return refs

    def _clean_ignored(self, cwd: Path) -> None:
        clean = self.runner.run(["git", "clean", "-fdX"], cwd=cwd, timeout_seconds=120)
        if not clean.passed:
            raise SafetyError(
                "Worker-created ignored files could not be discarded safely: " + clean.stderr
            )

    def _restore_refs(self, cwd: Path, expected: dict[str, str]) -> None:
        current = self._refs(cwd)
        failures: list[str] = []
        for ref in sorted(set(current) - set(expected)):
            result = self.runner.run(["git", "update-ref", "-d", ref], cwd=cwd, timeout_seconds=30)
            if not result.passed:
                failures.append(f"delete {ref}: {result.stderr}")
        for ref, sha in expected.items():
            if current.get(ref) == sha:
                continue
            result = self.runner.run(["git", "update-ref", ref, sha], cwd=cwd, timeout_seconds=30)
            if not result.passed:
                failures.append(f"restore {ref}: {result.stderr}")
        if failures:
            raise SafetyError("Failed worker attempt changed Git refs that could not be restored: " + "; ".join(failures))

    def _rollback(self, cwd: Path, head: str, refs: dict[str, str]) -> None:
        reset = self.runner.run(["git", "reset", "--hard", head], cwd=cwd, timeout_seconds=120)
        if not reset.passed:
            raise SafetyError("Failed worker attempt could not be rolled back safely: " + reset.stderr)
        clean = self.runner.run(["git", "clean", "-fdx"], cwd=cwd, timeout_seconds=120)
        if not clean.passed:
            raise SafetyError(
                "Failed worker attempt left repository files that could not be removed: " + clean.stderr
            )
        self._restore_refs(cwd, refs)
        if self._head(cwd) != head or self._dirty(cwd, include_ignored=True):
            raise SafetyError("Failed worker attempt rollback could not be verified as pristine.")

    def _discard_failed_outputs(self, request: AgentRequest) -> None:
        candidates = [request.output_path, request.output_path.with_suffix(".validated.json")]
        for path in candidates:
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise SafetyError(
                    f"Failed worker output could not be discarded safely: {path}: {exc}"
                ) from exc

    def _rollback_failed_attempt(
        self,
        request: AgentRequest,
        head: str,
        refs: dict[str, str],
    ) -> None:
        self._rollback(request.cwd, head, refs)
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
        self._assert_pristine_disposable_workspace(request.cwd)
        head = self._head(request.cwd)
        refs = self._refs(request.cwd)
        truth_snapshot = self._snapshot_controller_truth(request)
        try:
            response = self.inner.run(request)
        except Exception as exc:
            changed_truth = self._restore_controller_truth(truth_snapshot)
            self._rollback_failed_attempt(request, head, refs)
            if changed_truth:
                raise SafetyError(
                    "Worker modified critical Manageroo controller truth; changes were restored: "
                    + ", ".join(changed_truth)
                ) from exc
            raise

        changed_truth = self._restore_controller_truth(truth_snapshot)
        if changed_truth:
            self._rollback_failed_attempt(request, head, refs)
            raise SafetyError(
                "Worker modified critical Manageroo controller truth; changes were restored: "
                + ", ".join(changed_truth)
            )

        if request.sandbox == "read-only":
            try:
                dirty = self._dirty(request.cwd, include_ignored=True)
                head_changed = self._head(request.cwd) != head
                refs_changed = self._refs(request.cwd) != refs
            except SafetyError:
                self._rollback_failed_attempt(request, head, refs)
                raise
            if dirty or head_changed or refs_changed:
                self._rollback_failed_attempt(request, head, refs)
                raise SafetyError(
                    f"Read-only worker {request.role!r} mutated repository state or Git history; changes were discarded."
                )
        elif request.sandbox == "workspace-write":
            if self._head(request.cwd) != head or self._refs(request.cwd) != refs:
                self._rollback_failed_attempt(request, head, refs)
                raise SafetyError(
                    f"Workspace-write worker {request.role!r} changed Git history; the controller owns commits and refs."
                )
            self._clean_ignored(request.cwd)
            self._mark_pending_write_validation(request, head)
        return response
