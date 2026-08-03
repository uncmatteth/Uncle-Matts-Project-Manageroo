from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import SafetyError
from ..runner import CommandRunner
from ..util import atomic_write_json, sha256_file, utc_now


MAX_GIT_METADATA_FILES = 50_000
MAX_GIT_METADATA_ENTRIES = 100_000
MAX_GIT_METADATA_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class _ControllerTruthSnapshot:
    run_root: Path | None
    run_root_identity: tuple[int, int] | None
    directories: dict[Path, bool]
    files: dict[Path, bytes | None]


class TransactionalAdapter(AgentAdapter):
    """Rollback failed attempts and protect controller-owned run truth."""

    def __init__(self, inner: AgentAdapter, runner: CommandRunner):
        self.inner = inner
        self.runner = runner

    @property
    def requires_host_capability_catalog(self) -> bool:
        return self.inner.requires_host_capability_catalog

    def doctor(self, cwd: Path) -> dict:
        result = dict(self.inner.doctor(cwd))
        result["transactional_attempts"] = True
        result["read_only_mutation_enforced"] = True
        result["git_history_mutation_enforced"] = True
        result["git_metadata_mutation_enforced"] = True
        result["pristine_workspace_required"] = True
        result["ignored_worker_state_discarded"] = True
        result["critical_controller_truth_guard"] = True
        return result

    def _head(self, cwd: Path) -> str:
        result = self.runner.run(["git", "rev-parse", "HEAD"], cwd=cwd, timeout_seconds=30)
        if not result.passed:
            raise SafetyError("Manageroo could not capture the worker-attempt Git checkpoint: " + result.stderr)
        return result.stdout.strip()

    def _head_state(self, cwd: Path) -> tuple[str, str]:
        head = self._head(cwd)
        symbolic = self.runner.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=cwd, timeout_seconds=30)
        return ("symbolic", symbolic.stdout.strip()) if symbolic.passed and symbolic.stdout.strip() else ("detached", head)

    def _status(self, cwd: Path, *, include_ignored: bool = False) -> str:
        argv = ["git", "status", "--porcelain", "--untracked-files=all"]
        if include_ignored:
            argv.append("--ignored")
        result = self.runner.run(argv, cwd=cwd, timeout_seconds=30)
        if not result.passed:
            raise SafetyError("Manageroo could not verify worker-attempt repository state: " + result.stderr)
        return result.stdout

    def _dirty(self, cwd: Path, *, include_ignored: bool = False) -> bool:
        return bool(self._status(cwd, include_ignored=include_ignored).strip())

    def _assert_pristine_disposable_workspace(self, cwd: Path) -> None:
        status = self._status(cwd, include_ignored=True)
        if status.strip():
            raise SafetyError(
                "Transactional worker execution requires a pristine disposable Git workspace. "
                "Manageroo refused to run because pre-existing tracked, untracked, or ignored state would make destructive rollback unsafe."
            )

    def _refs(self, cwd: Path) -> dict[str, str]:
        result = self.runner.run(
            ["git", "for-each-ref", "--format=%(refname)%00%(objectname)"], cwd=cwd, timeout_seconds=30
        )
        if not result.passed:
            raise SafetyError("Manageroo could not snapshot Git refs: " + result.stderr)
        refs: dict[str, str] = {}
        for line in result.stdout.splitlines():
            name, separator, sha = line.partition("\0")
            if separator and name and sha:
                refs[name] = sha
        return refs

    def _git_directory(self, cwd: Path) -> Path:
        result = self.runner.run(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, timeout_seconds=30
        )
        if not result.passed or not result.stdout.strip():
            raise SafetyError(
                "Manageroo could not locate the worker-attempt Git directory: " + result.stderr
            )
        git_dir = Path(result.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = cwd / git_dir
        git_dir = git_dir.resolve()
        expected_git_dir = cwd.resolve() / ".git"
        if git_dir != expected_git_dir or not git_dir.is_dir() or git_dir.is_symlink():
            raise SafetyError(
                "Transactional worker execution requires a repository-local .git directory: "
                f"{git_dir}"
            )
        return git_dir

    def _git_common_directory(self, cwd: Path) -> Path:
        result = self.runner.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=cwd, timeout_seconds=30
        )
        if not result.passed or not result.stdout.strip():
            raise SafetyError(
                "Manageroo could not locate the worker-attempt Git common directory: "
                + result.stderr
            )
        git_common_dir = Path(result.stdout.strip())
        if not git_common_dir.is_absolute():
            git_common_dir = cwd / git_common_dir
        try:
            git_common_dir = git_common_dir.resolve(strict=True)
        except OSError as exc:
            raise SafetyError(
                "Manageroo could not resolve the worker-attempt Git common directory: "
                f"{git_common_dir}: {exc}"
            ) from exc
        if not git_common_dir.is_dir():
            raise SafetyError(
                "Worker-attempt Git common directory is not a directory: "
                f"{git_common_dir}"
            )
        return git_common_dir

    def _repository_lock_path(self, cwd: Path) -> Path:
        git_common_dir = self._git_common_directory(cwd)
        owner = str(os.getuid()) if hasattr(os, "getuid") else "local"
        lock_root = Path(tempfile.gettempdir()) / f"manageroo-transaction-locks-{owner}"
        try:
            lock_root.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise SafetyError(
                "Manageroo could not create the repository transaction lock directory: "
                f"{lock_root}: {exc}"
            ) from exc
        if lock_root.is_symlink() or not lock_root.is_dir():
            raise SafetyError(
                f"Manageroo repository transaction lock path is unsafe: {lock_root}"
            )
        identity = hashlib.sha256(os.fsencode(str(git_common_dir))).hexdigest()
        return lock_root / f"{identity}.lock"

    @staticmethod
    def _try_lock_file(descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_file(descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    @contextmanager
    def _repository_transaction_lock(
        self, cwd: Path, *, timeout_seconds: float = 30.0
    ) -> Iterator[None]:
        lock_path = self._repository_lock_path(cwd)
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise SafetyError(
                f"Manageroo could not open the repository transaction lock: {lock_path}: {exc}"
            ) from exc
        acquired = False
        try:
            lock_state = os.fstat(descriptor)
            if not stat.S_ISREG(lock_state.st_mode):
                raise SafetyError(
                    f"Manageroo repository transaction lock is not a regular file: {lock_path}"
                )
            if lock_state.st_size == 0:
                os.write(descriptor, b"\0")
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    self._try_lock_file(descriptor)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise SafetyError(
                            "Manageroo could not acquire the repository transaction lock: "
                            f"{lock_path}: {exc}"
                        ) from exc
                    if time.monotonic() >= deadline:
                        raise SafetyError(
                            f"Timed out waiting for repository transaction lock: {lock_path}"
                        ) from exc
                    time.sleep(0.05)
            yield
        finally:
            try:
                if acquired:
                    self._unlock_file(descriptor)
            except OSError as exc:
                raise SafetyError(
                    f"Manageroo could not release the repository transaction lock: {lock_path}: {exc}"
                ) from exc
            finally:
                os.close(descriptor)

    def _git_metadata_state(self, git_dir: Path) -> dict[str, tuple[str, int, bytes]]:
        state: dict[str, tuple[str, int, bytes]] = {}
        if not git_dir.exists() or git_dir.is_symlink() or not git_dir.is_dir():
            return state
        file_count = 0
        entry_count = 0
        total_bytes = 0

        def record(path: Path) -> bool:
            nonlocal entry_count, file_count, total_bytes
            relative = "." if path == git_dir else path.relative_to(git_dir).as_posix()
            metadata = path.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if path != git_dir:
                entry_count += 1
                if entry_count > MAX_GIT_METADATA_ENTRIES:
                    raise SafetyError(
                        "Git metadata exceeds the transactional entry limit of "
                        f"{MAX_GIT_METADATA_ENTRIES}."
                    )
            if stat.S_ISDIR(metadata.st_mode):
                state[relative] = ("directory", mode, b"")
                return True
            elif stat.S_ISREG(metadata.st_mode):
                file_count += 1
                if file_count > MAX_GIT_METADATA_FILES:
                    raise SafetyError(
                        "Git metadata exceeds the transactional file limit of "
                        f"{MAX_GIT_METADATA_FILES}."
                    )
                if metadata.st_size < 0 or total_bytes + metadata.st_size > MAX_GIT_METADATA_BYTES:
                    raise SafetyError(
                        "Git metadata exceeds the transactional byte limit of "
                        f"{MAX_GIT_METADATA_BYTES}."
                    )
                chunks: list[bytes] = []
                with path.open("rb") as handle:
                    while True:
                        chunk = handle.read(65_536)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > MAX_GIT_METADATA_BYTES:
                            raise SafetyError(
                                "Git metadata exceeds the transactional byte limit of "
                                f"{MAX_GIT_METADATA_BYTES}."
                            )
                        chunks.append(chunk)
                state[relative] = ("file", mode, b"".join(chunks))
                return False
            else:
                state[relative] = ("unsupported", mode, b"")
                return False

        record(git_dir)
        pending = [git_dir]
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if record(path):
                        pending.append(path)
        return state

    def _snapshot_git_metadata(
        self, cwd: Path
    ) -> tuple[Path, dict[str, tuple[str, int, bytes]]]:
        git_dir = self._git_directory(cwd)
        snapshot = self._git_metadata_state(git_dir)
        unsupported = [path for path, entry in snapshot.items() if entry[0] == "unsupported"]
        if unsupported:
            raise SafetyError(
                "Transactional worker execution does not support symlinks or special files "
                "in the Git directory: "
                + ", ".join(unsupported)
            )
        return git_dir, snapshot

    @staticmethod
    def _make_removable(function, path: str, _exc_info) -> None:
        os.chmod(path, stat.S_IRWXU)
        function(path)

    def _restore_git_metadata(
        self, snapshot: tuple[Path, dict[str, tuple[str, int, bytes]]]
    ) -> bool:
        git_dir, expected = snapshot
        try:
            current = self._git_metadata_state(git_dir)
        except (OSError, SafetyError):
            current = {}
        if current == expected:
            return False
        changed_paths = {
            path
            for path in set(current) | set(expected)
            if current.get(path) != expected.get(path)
        }
        protected_metadata_changed = bool(changed_paths - {"index"})
        try:
            if git_dir.is_dir() and not git_dir.is_symlink():
                shutil.rmtree(git_dir, onerror=self._make_removable)
            elif git_dir.exists() or git_dir.is_symlink():
                git_dir.unlink()

            git_dir.mkdir(parents=True, mode=0o700)
            directories = [
                (relative, entry)
                for relative, entry in expected.items()
                if relative != "." and entry[0] == "directory"
            ]
            for relative, _entry in sorted(directories, key=lambda item: item[0].count("/")):
                (git_dir / relative).mkdir(mode=0o700)
            for relative, (kind, mode, content) in expected.items():
                if kind != "file":
                    continue
                path = git_dir / relative
                path.write_bytes(content)
                path.chmod(mode)
            for relative, (_kind, mode, _content) in sorted(
                directories, key=lambda item: item[0].count("/"), reverse=True
            ):
                (git_dir / relative).chmod(mode)
            git_dir.chmod(expected["."][1])
        except OSError as exc:
            raise SafetyError(
                f"Worker changed protected Git metadata and it could not be restored: {git_dir}: {exc}"
            ) from exc
        if self._git_metadata_state(git_dir) != expected:
            raise SafetyError("Worker changed protected Git metadata and restoration could not be verified.")
        return protected_metadata_changed

    def _clean_ignored(self, cwd: Path) -> None:
        clean = self.runner.run(["git", "clean", "-fdX"], cwd=cwd, timeout_seconds=120)
        if not clean.passed:
            raise SafetyError("Worker-created ignored files could not be discarded safely: " + clean.stderr)

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

    def _restore_head_state(self, cwd: Path, head_state: tuple[str, str]) -> None:
        mode, value = head_state
        if mode == "symbolic":
            result = self.runner.run(["git", "symbolic-ref", "HEAD", value], cwd=cwd, timeout_seconds=30)
            if not result.passed:
                raise SafetyError("Failed worker attempt could not restore symbolic HEAD: " + result.stderr)
        elif self._head(cwd) != value:
            result = self.runner.run(["git", "checkout", "--detach", value], cwd=cwd, timeout_seconds=30)
            if not result.passed:
                raise SafetyError("Failed worker attempt could not restore detached HEAD: " + result.stderr)

    def _rollback(self, cwd: Path, head: str, refs: dict[str, str], head_state: tuple[str, str]) -> None:
        reset = self.runner.run(["git", "reset", "--hard", head], cwd=cwd, timeout_seconds=120)
        if not reset.passed:
            raise SafetyError("Failed worker attempt could not be rolled back safely: " + reset.stderr)
        clean = self.runner.run(["git", "clean", "-fdx"], cwd=cwd, timeout_seconds=120)
        if not clean.passed:
            raise SafetyError("Failed worker attempt left repository files that could not be removed: " + clean.stderr)
        self._restore_refs(cwd, refs)
        self._restore_head_state(cwd, head_state)
        if self._head(cwd) != head or self._head_state(cwd) != head_state or self._refs(cwd) != refs or self._dirty(cwd, include_ignored=True):
            raise SafetyError("Failed worker attempt rollback could not be verified as pristine.")

    def _discard_failed_outputs(self, request: AgentRequest) -> None:
        for path in [request.output_path, request.output_path.with_suffix(".validated.json")]:
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise SafetyError(f"Failed worker output could not be discarded safely: {path}: {exc}") from exc

    def _rollback_failed_attempt(
        self,
        request: AgentRequest,
        head: str,
        refs: dict[str, str],
        head_state: tuple[str, str],
        git_snapshot: tuple[Path, dict[str, tuple[str, int, bytes]]],
    ) -> None:
        self._restore_git_metadata(git_snapshot)
        self._rollback(request.cwd, head, refs, head_state)
        self._restore_git_metadata(git_snapshot)
        self._discard_failed_outputs(request)

    def _run_location(self, request: AgentRequest) -> tuple[Path, str, str] | None:
        output_parent = request.output_path.parent
        agent_output_root = output_parent.parent
        if agent_output_root.name != "agent-output":
            return None
        return agent_output_root.parent, output_parent.name, request.output_path.stem

    def _pending_validation_marker(self, request: AgentRequest) -> Path | None:
        location = self._run_location(request)
        return None if location is None else location[0] / "controller" / "pending-workspace-validation.json"

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
            run_root / "controller" / "budget.json",
            run_root / "jobs" / f"{job_id}.json",
            run_root / "worker-attempts" / job_id / f"{attempt_id}.json",
        ]

    def _snapshot_controller_truth(self, request: AgentRequest) -> _ControllerTruthSnapshot:
        location = self._run_location(request)
        protected_paths = self._protected_controller_paths(request)
        if location is None or not protected_paths:
            return _ControllerTruthSnapshot(None, None, {}, {})
        lexical_run_root = location[0]
        try:
            root_state = lexical_run_root.lstat()
            if stat.S_ISLNK(root_state.st_mode) or not stat.S_ISDIR(root_state.st_mode):
                raise SafetyError(
                    f"Controller truth run root must be a real directory: {lexical_run_root}"
                )
            run_root = lexical_run_root.resolve(strict=True)
            root_state = run_root.lstat()
        except OSError as exc:
            raise SafetyError(
                f"Manageroo could not anchor controller truth to the run root: {lexical_run_root}: {exc}"
            ) from exc

        files = {
            run_root / path.relative_to(lexical_run_root): None for path in protected_paths
        }
        directory_paths: set[Path] = set()
        for path in files:
            current = path.parent
            while current != run_root:
                directory_paths.add(current)
                current = current.parent

        directories: dict[Path, bool] = {}
        for path in sorted(directory_paths, key=lambda item: len(item.relative_to(run_root).parts)):
            try:
                path_state = path.lstat()
            except FileNotFoundError:
                directories[path] = False
                continue
            except OSError as exc:
                raise SafetyError(
                    f"Controller truth directory topology is unreadable: {path}: {exc}"
                ) from exc
            if stat.S_ISLNK(path_state.st_mode) or not stat.S_ISDIR(path_state.st_mode):
                raise SafetyError(f"Controller truth path component must be a real directory: {path}")
            directories[path] = True

        for path in files:
            try:
                path_state = path.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SafetyError(f"Controller truth path is unreadable: {path}: {exc}") from exc
            if stat.S_ISLNK(path_state.st_mode):
                raise SafetyError(f"Controller truth path must not be a symlink: {path}")
            if stat.S_ISREG(path_state.st_mode):
                files[path] = path.read_bytes()
        return _ControllerTruthSnapshot(
            run_root=run_root,
            run_root_identity=(root_state.st_dev, root_state.st_ino),
            directories=directories,
            files=files,
        )

    def _restore_controller_truth(self, snapshot: _ControllerTruthSnapshot) -> list[str]:
        if snapshot.run_root is None or snapshot.run_root_identity is None:
            return []
        changed: list[str] = []
        try:
            root_state = snapshot.run_root.lstat()
        except OSError as exc:
            raise SafetyError(
                f"Critical controller truth run root changed and cannot be restored safely: {snapshot.run_root}: {exc}"
            ) from exc
        if (
            stat.S_ISLNK(root_state.st_mode)
            or not stat.S_ISDIR(root_state.st_mode)
            or (root_state.st_dev, root_state.st_ino) != snapshot.run_root_identity
        ):
            raise SafetyError(
                f"Critical controller truth run root changed and cannot be restored safely: {snapshot.run_root}"
            )

        for path, expected_directory in sorted(
            snapshot.directories.items(),
            key=lambda item: len(item[0].relative_to(snapshot.run_root).parts),
        ):
            try:
                path_state = path.lstat()
            except FileNotFoundError:
                path_state = None
            except OSError as exc:
                raise SafetyError(
                    f"Critical controller truth directory is unreadable: {path}: {exc}"
                ) from exc
            current_directory = bool(
                path_state is not None
                and stat.S_ISDIR(path_state.st_mode)
                and not stat.S_ISLNK(path_state.st_mode)
            )
            if (expected_directory and current_directory) or (
                not expected_directory and path_state is None
            ):
                continue
            changed.append(str(path))
            try:
                if path_state is not None and stat.S_ISDIR(path_state.st_mode):
                    shutil.rmtree(path)
                elif path_state is not None:
                    path.unlink()
                if expected_directory:
                    path.mkdir()
            except OSError as exc:
                raise SafetyError(
                    f"Critical controller truth directory changed and could not be restored: {path}: {exc}"
                ) from exc

        for path, expected in snapshot.files.items():
            try:
                path_state = path.lstat()
            except FileNotFoundError:
                path_state = None
            except OSError as exc:
                raise SafetyError(f"Critical controller truth is unreadable: {path}: {exc}") from exc
            current = path.read_bytes() if path_state is not None and stat.S_ISREG(path_state.st_mode) else None
            current_exists = path_state is not None
            if expected is None and not current_exists:
                continue
            if expected is not None and current == expected:
                continue
            changed.append(str(path))
            try:
                if path_state is not None:
                    if stat.S_ISDIR(path_state.st_mode):
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                if expected is not None:
                    path.write_bytes(expected)
            except OSError as exc:
                raise SafetyError(f"Critical controller truth changed and could not be restored: {path}: {exc}") from exc
        return changed

    def _workspace_state_digest(self, cwd: Path, head: str) -> str:
        digest = hashlib.sha256()
        diff = self.runner.run(["git", "diff", "--binary", head, "--"], cwd=cwd, timeout_seconds=120)
        if not diff.passed:
            raise SafetyError("Could not bind pending workspace changes: " + diff.stderr)
        digest.update(diff.stdout.encode("utf-8", errors="surrogateescape"))
        untracked = self.runner.run(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=cwd, timeout_seconds=60)
        if not untracked.passed:
            raise SafetyError("Could not enumerate pending untracked workspace files: " + untracked.stderr)
        for relative in sorted(item for item in untracked.stdout.split("\0") if item):
            path = cwd / relative
            if path.is_symlink():
                raise SafetyError(f"Pending workspace contains unsupported symlink: {relative}")
            if path.is_file():
                digest.update(relative.encode("utf-8", errors="surrogateescape"))
                digest.update(b"\0")
                digest.update(sha256_file(path).encode("ascii"))
                digest.update(b"\0")
        return digest.hexdigest()

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
                "workspace_state_sha256": self._workspace_state_digest(request.cwd, head),
                "output_path": str(request.output_path),
                "created_at": utc_now(),
            },
        )

    def run(self, request: AgentRequest) -> AgentResponse:
        with self._repository_transaction_lock(request.cwd):
            return self._run_locked(request)

    def _run_locked(self, request: AgentRequest) -> AgentResponse:
        self._assert_pristine_disposable_workspace(request.cwd)
        head = self._head(request.cwd)
        head_state = self._head_state(request.cwd)
        refs = self._refs(request.cwd)
        git_snapshot = self._snapshot_git_metadata(request.cwd)
        truth_snapshot = self._snapshot_controller_truth(request)
        try:
            response = self.inner.run(request)
        except Exception as exc:
            changed_git_metadata = self._restore_git_metadata(git_snapshot)
            changed_truth = self._restore_controller_truth(truth_snapshot)
            self._rollback_failed_attempt(request, head, refs, head_state, git_snapshot)
            if changed_git_metadata:
                raise SafetyError("Worker modified protected Git metadata; changes were restored.") from exc
            if changed_truth:
                raise SafetyError(
                    "Worker modified critical Manageroo controller truth; changes were restored: " + ", ".join(changed_truth)
                ) from exc
            raise

        changed_git_metadata = self._restore_git_metadata(git_snapshot)
        changed_truth = self._restore_controller_truth(truth_snapshot)
        if changed_git_metadata:
            self._rollback_failed_attempt(request, head, refs, head_state, git_snapshot)
            if request.sandbox == "read-only":
                raise SafetyError(
                    f"Read-only worker {request.role!r} mutated repository state or Git history, "
                    "including protected Git metadata; changes were restored."
                )
            raise SafetyError("Worker modified protected Git metadata; changes were restored.")
        if changed_truth:
            self._rollback_failed_attempt(request, head, refs, head_state, git_snapshot)
            raise SafetyError(
                "Worker modified critical Manageroo controller truth; changes were restored: " + ", ".join(changed_truth)
            )

        try:
            if request.sandbox == "read-only":
                if (
                    self._dirty(request.cwd, include_ignored=True)
                    or self._head(request.cwd) != head
                    or self._head_state(request.cwd) != head_state
                    or self._refs(request.cwd) != refs
                ):
                    raise SafetyError(
                        f"Read-only worker {request.role!r} mutated repository state or Git history."
                    )
            elif request.sandbox == "workspace-write":
                if self._head(request.cwd) != head or self._head_state(request.cwd) != head_state or self._refs(request.cwd) != refs:
                    raise SafetyError(
                        f"Workspace-write worker {request.role!r} changed Git history; the controller owns commits and refs."
                    )
                self._clean_ignored(request.cwd)
                self._mark_pending_write_validation(request, head)
        except Exception as exc:
            try:
                self._restore_controller_truth(truth_snapshot)
                self._rollback_failed_attempt(request, head, refs, head_state, git_snapshot)
            except Exception as rollback_exc:
                raise SafetyError(
                    "Worker finalization failed and the workspace could not be rolled back safely: " + str(rollback_exc)
                ) from rollback_exc
            raise exc
        self._restore_git_metadata(git_snapshot)
        return response
