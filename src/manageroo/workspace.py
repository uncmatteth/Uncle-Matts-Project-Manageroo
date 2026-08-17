from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import SafetyError
from .inventory import git_visible_files
from .runner import CommandRunner
from .util import (
    atomic_write_json,
    copy_file_preserving_mode,
    safe_repo_relative,
    sha256_file,
    utc_now,
)


@dataclass(frozen=True)
class SourceFile:
    path: str
    sha256: str
    bytes: int
    mode: int


class WorkspaceMirror:
    """Creates an isolated Git repository from the source tree's visible files."""

    def __init__(self, source_repo: Path, run_root: Path, runner: CommandRunner):
        self.source_repo = source_repo.resolve()
        self.run_root = run_root.resolve()
        self.runner = runner
        self.workspace = self.run_root / "workspace"
        self.snapshot_path = self.run_root / "source-snapshot.json"
        self.pending_validation_path = self.run_root / "controller" / "pending-workspace-validation.json"
        self.baseline_commit = ""

    def capture_source(self) -> list[SourceFile]:
        records: list[SourceFile] = []
        for raw_relative in git_visible_files(self.source_repo, self.runner):
            relative = safe_repo_relative(raw_relative)
            path = self.source_repo / relative
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise SafetyError(f"Visible source path is unreadable: {relative}: {exc}") from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise SafetyError(f"Tracked or visible symlinks are not supported by the isolated workspace policy: {relative}")
            if not stat.S_ISREG(metadata.st_mode):
                raise SafetyError(f"Visible source path is non-regular and unsupported: {relative}")
            records.append(SourceFile(path=relative, sha256=sha256_file(path), bytes=metadata.st_size, mode=metadata.st_mode & 0o777))
        atomic_write_json(self.snapshot_path, {"files": [asdict(item) for item in records]})
        return records

    def _preflight_free_space(
        self, records: list[SourceFile], *, minimum_free_bytes: int
    ) -> None:
        if minimum_free_bytes < 0:
            raise SafetyError("Workspace minimum free-space reserve cannot be negative.")
        available = shutil.disk_usage(self.run_root).free
        copy_bytes = sum(record.bytes for record in records)
        if available - copy_bytes < minimum_free_bytes:
            raise SafetyError(
                "Manageroo stopped before copying the repository because the workspace "
                f"would breach the free-space reserve. Available={available} "
                f"copy_bytes={copy_bytes} reserve={minimum_free_bytes}."
            )

    def _materialize_workspace(self, records: list[SourceFile]) -> Path:
        self.workspace.mkdir(parents=True)
        for record in records:
            destination = self.workspace / record.path
            copy_file_preserving_mode(self.source_repo / record.path, destination)
            copied_stat = destination.stat()
            if (
                copied_stat.st_size != record.bytes
                or (copied_stat.st_mode & 0o777) != record.mode
                or sha256_file(destination) != record.sha256
            ):
                raise SafetyError(
                    f"Copied workspace file does not match source snapshot: {record.path}"
                )
        self._git(["init", "-b", "manageroo-internal"])
        self._git(["config", "user.name", "MANAGEROO Controller"])
        self._git(["config", "user.email", "manageroo@local.invalid"])
        self._git(["add", "-A"])
        self._git(["commit", "-m", "MANAGEROO isolated baseline"], hooks=False)
        self.baseline_commit = self.head()
        hook = self.workspace / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho 'Agent commits are forbidden. The MANAGEROO controller owns checkpoints.' >&2\nexit 73\n", encoding="utf-8")
        hook.chmod(0o755)
        return self.workspace

    def create(self, *, minimum_free_bytes: int = 0) -> Path:
        if self.workspace.exists() or self.snapshot_path.exists():
            raise SafetyError("Run workspace or source snapshot already exists; creation is immutable for an existing run.")
        self.run_root.mkdir(parents=True, exist_ok=True)
        snapshot_created = False
        workspace_created = False
        try:
            records = self.capture_source()
            snapshot_created = True
            self._preflight_free_space(
                records, minimum_free_bytes=minimum_free_bytes
            )
            workspace_created = True
            return self._materialize_workspace(records)
        except BaseException as exc:
            self.baseline_commit = ""
            cleanup_errors: list[str] = []
            if workspace_created:
                try:
                    shutil.rmtree(self.workspace)
                except OSError as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            if snapshot_created:
                try:
                    self.snapshot_path.unlink()
                except OSError as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            if cleanup_errors:
                exc.add_note(
                    "Manageroo could not fully remove its failed workspace creation: "
                    + "; ".join(cleanup_errors)
                )
            raise

    def _snapshot_records(self) -> list[SourceFile]:
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            raw_records = payload["files"]
            if not isinstance(raw_records, list):
                raise TypeError("files is not a list")
            records = [
                SourceFile(
                    path=safe_repo_relative(str(item["path"])),
                    sha256=str(item["sha256"]),
                    bytes=int(item["bytes"]),
                    mode=int(item["mode"]),
                )
                for item in raw_records
                if isinstance(item, dict)
            ]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SafetyError(f"Run source snapshot is invalid: {self.snapshot_path}: {exc}") from exc
        if len(records) != len(raw_records):
            raise SafetyError(f"Run source snapshot contains invalid records: {self.snapshot_path}")
        return records

    def rebuild_cleaned_workspace(self, *, minimum_free_bytes: int = 0) -> Path:
        if self.workspace.exists():
            raise SafetyError("Cleaned workspace rebuild requires an absent workspace path.")
        if not self.snapshot_path.is_file():
            raise SafetyError(f"Run source snapshot is missing: {self.snapshot_path}")
        self.assert_source_unchanged()
        records = self._snapshot_records()
        self._preflight_free_space(records, minimum_free_bytes=minimum_free_bytes)
        try:
            self._materialize_workspace(records)
            lifecycle_path = self.run_root / "controller" / "workspace-lifecycle.json"
            lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
            recovery_value = str(lifecycle.get("recovery_patch") or "")
            recovery_patch = Path(recovery_value) if recovery_value else None
            allowed = {
                self.run_root / "controller" / "workspace-checkpoint.patch",
                self.run_root / "delivery" / "final.patch",
            }
            if recovery_patch is None or recovery_patch not in allowed or not recovery_patch.is_file():
                raise SafetyError("Cleaned workspace has no valid bounded recovery patch.")
            expected_digest = str(lifecycle.get("recovery_patch_sha256") or "")
            if not expected_digest or sha256_file(recovery_patch) != expected_digest:
                raise SafetyError("Cleaned workspace recovery patch changed.")
            if recovery_patch.stat().st_size:
                applied = self._git(["apply", "--binary", str(recovery_patch)])
                if not applied.passed:
                    raise SafetyError("Could not restore the cleaned workspace checkpoint.")
                self.checkpoint("MANAGEROO restored bounded workspace checkpoint")
            return self.workspace
        except BaseException:
            self.baseline_commit = ""
            if self.workspace.is_dir():
                shutil.rmtree(self.workspace)
            raise

    def resume_or_create(self, *, minimum_free_bytes: int = 0) -> Path:
        if self.workspace.is_dir():
            return self.load_existing()
        if self.snapshot_path.is_file():
            return self.rebuild_cleaned_workspace(
                minimum_free_bytes=minimum_free_bytes
            )
        return self.create(minimum_free_bytes=minimum_free_bytes)

    def _clear_pending_validation_marker(self) -> None:
        try:
            if self.pending_validation_path.is_file():
                self.pending_validation_path.unlink()
        except OSError as exc:
            raise SafetyError("Manageroo could not clear the pending workspace-validation marker: " + str(exc)) from exc

    def _discard_ignored_state(self) -> None:
        # The workspace is Manageroo-owned and disposable. The second force is required
        # for ignored nested Git repositories, which ordinary `git clean -fdX` preserves.
        self._git(["clean", "-ffdX"])
        remaining = self._git(["status", "--porcelain", "--ignored"])
        ignored = [line for line in remaining.stdout.splitlines() if line.startswith("!! ")]
        if ignored:
            raise SafetyError(
                "Run workspace contains ignored state that could not be discarded safely: "
                + ", ".join(line[3:] for line in ignored)
            )

    def discard_ignored_integration_state(self) -> None:
        """Remove disposable discovery indexes before workers run."""
        # GitNexus creates this path even when the target repository does not
        # ignore it. ``git clean`` never removes tracked files, so a repository-
        # owned .gitnexus path remains protected and the later pristine check
        # detects any mutation.
        self._git(["clean", "-ffdx", "--", ".gitnexus"])
        self._discard_ignored_state()

    def _discard_uncheckpointed_state(self) -> None:
        self._discard_ignored_state()
        status = self._git(["status", "--porcelain"])
        if status.stdout.strip():
            self._git(["reset", "--hard", "HEAD"])
            self._git(["clean", "-fdx"])
            remaining = self._git(["status", "--porcelain", "--ignored"])
            if remaining.stdout.strip():
                raise SafetyError("Run workspace contains unverified changes that could not be discarded safely.")
        self._clear_pending_validation_marker()

    def _assert_workspace_paths_regular(self) -> None:
        def traversal_error(exc: OSError) -> None:
            raise SafetyError(f"Pending workspace traversal failed: {exc}") from exc

        for current, directories, files in os.walk(
            self.workspace,
            topdown=True,
            onerror=traversal_error,
            followlinks=False,
        ):
            current_path = Path(current)
            if current_path == self.workspace and ".git" in directories:
                directories.remove(".git")
            for name in [*directories, *files]:
                path = current_path / name
                relative = path.relative_to(self.workspace).as_posix()
                try:
                    metadata = path.lstat()
                except OSError as exc:
                    raise SafetyError(f"Pending workspace path is unreadable: {relative}: {exc}") from exc
                if name in directories and stat.S_ISDIR(metadata.st_mode):
                    continue
                if name in files and stat.S_ISREG(metadata.st_mode):
                    continue
                raise SafetyError(f"Pending workspace contains unsupported non-regular path: {relative}")

    def _workspace_state_digest(self, head: str) -> str:
        self._assert_workspace_paths_regular()
        digest = hashlib.sha256()
        diff = self._git(["diff", "--binary", head, "--"])
        digest.update(b"manageroo-workspace-state-v2\0")

        def update_field(value: bytes) -> None:
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)

        digest.update(b"tracked-diff\0")
        update_field(diff.stdout.encode("utf-8", errors="surrogateescape"))
        untracked = self._git(["ls-files", "-z", "--others", "--exclude-standard"])
        for relative in sorted(item for item in untracked.stdout.split("\0") if item):
            path = self.workspace / relative
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise SafetyError(f"Pending workspace contains unsupported symlink: {relative}")
            if stat.S_ISREG(metadata.st_mode):
                digest.update(b"untracked-file\0")
                update_field(relative.encode("utf-8", errors="surrogateescape"))
                update_field(stat.S_IFMT(metadata.st_mode).to_bytes(4, "big"))
                update_field(stat.S_IMODE(metadata.st_mode).to_bytes(4, "big"))
                update_field(bytes.fromhex(sha256_file(path)))
            else:
                raise SafetyError(f"Pending workspace contains unsupported non-regular path: {relative}")
        return digest.hexdigest()

    def _completed_write_job_owns_pending_state(self) -> bool:
        if not self.pending_validation_path.is_file():
            return False
        try:
            marker = json.loads(self.pending_validation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyError(f"Pending workspace-validation state is unreadable: {self.pending_validation_path}: {exc}") from exc
        if not isinstance(marker, dict) or marker.get("sandbox") != "workspace-write":
            raise SafetyError("Pending workspace-validation marker is invalid.")
        job_id = str(marker.get("job_id") or "").strip()
        expected_digest = str(marker.get("workspace_state_sha256") or "").strip()
        pre_attempt_head = str(marker.get("pre_attempt_head") or "").strip()
        if not job_id or not expected_digest or not pre_attempt_head:
            raise SafetyError("Pending workspace-validation marker is incomplete.")
        job_path = self.run_root / "jobs" / f"{job_id}.json"
        if not job_path.is_file():
            return False
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyError(f"Run job state is unreadable during resume: {job_path}: {exc}") from exc
        if not (
            isinstance(job, dict)
            and job.get("status") == "complete"
            and job.get("sandbox") == "workspace-write"
        ):
            return False
        return self._workspace_state_digest(pre_attempt_head) == expected_digest

    def load_existing(self) -> Path:
        if not self.workspace.is_dir() or not (self.workspace / ".git").is_dir():
            raise SafetyError(f"Run workspace is missing or not a Git repository: {self.workspace}")
        if not self.snapshot_path.is_file():
            raise SafetyError(f"Run source snapshot is missing: {self.snapshot_path}")
        roots = self._git(["rev-list", "--max-parents=0", "HEAD"]).stdout.splitlines()
        if not roots:
            raise SafetyError("Run workspace has no baseline commit.")
        self.baseline_commit = roots[0].strip()
        self._discard_ignored_state()
        status = self._git(["status", "--porcelain"])
        if not status.stdout.strip():
            self._clear_pending_validation_marker()
        elif not self._completed_write_job_owns_pending_state():
            self._discard_uncheckpointed_state()
        return self.workspace

    def _git(self, args: list[str], *, hooks: bool = True):
        argv = ["git"]
        if not hooks:
            # Controller-owned commits must be deterministic and must not inherit user-level
            # signing or hook configuration. This keeps isolated workspaces usable on hosts
            # that globally require GPG/SSH signatures or define custom hook/template paths.
            argv.extend(
                [
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgSign=false",
                    "-c",
                    "tag.gpgSign=false",
                ]
            )
        argv.extend(args)
        result = self.runner.run(argv, cwd=self.workspace, timeout_seconds=300)
        if not result.passed:
            raise SafetyError(result.stderr or f"Git command failed: {argv}")
        return result

    def head(self) -> str:
        return self._git(["rev-parse", "HEAD"]).stdout.strip()

    def changed_paths(self, since: str) -> list[str]:
        result = self._git(["diff", "--name-only", "-z", since, "--"])
        changed = {item for item in result.stdout.split("\0") if item}
        untracked = self._git(["ls-files", "-z", "--others", "--exclude-standard"])
        changed.update(item for item in untracked.stdout.split("\0") if item)
        return sorted(changed)

    def checkpoint(self, message: str, *, preserve_ignored: bool = False) -> str:
        if not preserve_ignored:
            self._discard_ignored_state()
        self._git(["add", "-A"])
        status = self._git(["status", "--porcelain"])
        if status.stdout.strip():
            self._git(["commit", "-m", message], hooks=False)
        head = self.head()
        self._clear_pending_validation_marker()
        return head

    def write_patch(self, destination: Path) -> Path:
        result = self._git(["diff", "--binary", self.baseline_commit, "HEAD", "--"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(result.stdout, encoding="utf-8", newline="\n")
        return destination

    def cleanup_terminal(self, *, status: str) -> dict[str, object]:
        """Remove full run-owned checkouts while retaining bounded patch evidence."""

        lifecycle_path = self.run_root / "controller" / "workspace-lifecycle.json"
        errors: list[str] = []
        recovery_patch = self.run_root / "delivery" / "final.patch"
        if status != "COMPLETE" and self.workspace.is_dir() and (self.workspace / ".git").is_dir():
            recovery_patch = self.run_root / "controller" / "workspace-checkpoint.patch"
            try:
                self.load_existing()
                self.write_patch(recovery_patch)
            except Exception as exc:
                errors.append(f"Could not preserve workspace checkpoint: {type(exc).__name__}: {exc}")

        removed: list[str] = []
        if not errors:
            for path in (
                self.workspace,
                self.run_root / "review-workspaces",
                self.run_root / "gate-workspaces",
            ):
                try:
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                        removed.append(str(path))
                    elif path.is_dir():
                        shutil.rmtree(path)
                        removed.append(str(path))
                except OSError as exc:
                    errors.append(f"Could not remove {path}: {exc}")

        report: dict[str, object] = {
            "schema_version": 1,
            "status": status,
            "cleaned_at": utc_now(),
            "workspace_removed": not self.workspace.exists(),
            "removed": removed,
            "recovery_patch": str(recovery_patch) if recovery_patch.is_file() else "",
            "recovery_patch_sha256": (
                sha256_file(recovery_patch) if recovery_patch.is_file() else ""
            ),
            "errors": errors,
        }
        atomic_write_json(lifecycle_path, report)
        return report

    def assert_source_unchanged(self) -> None:
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        expected = {item["path"]: item for item in snapshot["files"]}
        current_paths = set(git_visible_files(self.source_repo, self.runner))
        if current_paths != set(expected):
            missing = sorted(set(expected) - current_paths)
            extra = sorted(current_paths - set(expected))
            raise SafetyError(f"Source tree changed during run. Missing={missing}; extra={extra}")
        changed: list[str] = []
        for relative, record in expected.items():
            path = self.source_repo / relative
            if not path.is_file() or path.is_symlink():
                changed.append(relative)
                continue
            stat = path.stat()
            current_mode = stat.st_mode & 0o777
            if sha256_file(path) != record["sha256"] or current_mode != int(record.get("mode", current_mode)):
                changed.append(relative)
        if changed:
            raise SafetyError("Source tree changed during run: " + ", ".join(changed))

    def _visible_tree_identity(self, root: Path) -> dict[str, tuple[str, int]]:
        identities: dict[str, tuple[str, int]] = {}
        for raw_relative in git_visible_files(root, self.runner):
            relative = safe_repo_relative(raw_relative)
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise SafetyError(f"Repository tree contains an unsupported path: {relative}")
            file_stat = path.stat()
            identities[relative] = (sha256_file(path), file_stat.st_mode & 0o777)
        return identities

    def _capture_source_states(
        self,
        expected_source: dict[str, tuple[str, int]],
    ) -> dict[str, tuple[bytes, int] | None]:
        source_identity = self._visible_tree_identity(self.source_repo)
        states: dict[str, tuple[bytes, int] | None] = {}
        for relative in sorted(set(source_identity) | set(expected_source)):
            if source_identity.get(relative) == expected_source.get(relative):
                continue
            identity = source_identity.get(relative)
            if identity is None:
                states[relative] = None
                continue
            path = self.source_repo / relative
            try:
                contents = path.read_bytes()
                mode = path.stat().st_mode & 0o777
            except OSError as exc:
                raise SafetyError(
                    f"Source path changed while preparing transactional patch apply: {relative}"
                ) from exc
            if hashlib.sha256(contents).hexdigest() != identity[0] or mode != identity[1]:
                raise SafetyError(
                    f"Source path changed while preparing transactional patch apply: {relative}"
                )
            states[relative] = (contents, mode)
        return states

    def _source_path_identity(self, relative: str) -> tuple[str, int] | None:
        path = self.source_repo / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode):
            raise SafetyError(f"Repository tree contains an unsupported path: {relative}")
        return sha256_file(path), metadata.st_mode & 0o777

    def _restore_preserved_path(self, preserved: Path, path: Path) -> bool:
        try:
            os.link(preserved, path, follow_symlinks=False)
            preserved.unlink()
        except OSError:
            return False
        return True

    def _preserved_path_identity(self, preserved: Path) -> tuple[str, int] | None:
        metadata = preserved.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return None
        return sha256_file(preserved), metadata.st_mode & 0o777

    def _retain_preserved_path(self, preserved: Path, path: Path) -> Path | None:
        recovery_directory = Path(
            tempfile.mkdtemp(prefix="source-rollback-recovery-", dir=self.run_root)
        )
        recovery = recovery_directory / path.name
        try:
            os.link(preserved, recovery, follow_symlinks=False)
        except OSError:
            try:
                recovery_directory.rmdir()
            except OSError:
                pass
            return None
        return recovery

    def _restore_unchanged_source_paths(
        self,
        expected_source: dict[str, tuple[str, int]],
        source_states: dict[str, tuple[bytes, int] | None],
    ) -> list[str]:
        unrestored: list[str] = []
        for relative, original in source_states.items():
            path = self.source_repo / relative
            original_identity = None
            if original is not None:
                original_identity = (hashlib.sha256(original[0]).hexdigest(), original[1])
            try:
                current_identity = self._source_path_identity(relative)
                if current_identity == original_identity:
                    continue
                if current_identity != expected_source.get(relative):
                    unrestored.append(relative)
                    continue
                if original is None:
                    descriptor, preserved_name = tempfile.mkstemp(
                        prefix=f".{path.name}.manageroo-preserved-",
                        dir=path.parent,
                    )
                    os.close(descriptor)
                    preserved = Path(preserved_name)
                    try:
                        os.replace(path, preserved)
                    except OSError:
                        preserved.unlink(missing_ok=True)
                        raise
                    preserved_identity = self._preserved_path_identity(preserved)
                    if preserved_identity != current_identity:
                        self._restore_preserved_path(preserved, path)
                        unrestored.append(relative)
                        continue
                    recovery = self._retain_preserved_path(preserved, path)
                    if recovery is None:
                        self._restore_preserved_path(preserved, path)
                        unrestored.append(relative)
                        continue
                    if self._preserved_path_identity(recovery) != current_identity:
                        self._restore_preserved_path(preserved, path)
                        unrestored.append(relative)
                        continue
                    preserved.unlink()
                    if self._preserved_path_identity(recovery) != current_identity:
                        self._restore_preserved_path(recovery, path)
                        unrestored.append(relative)
                elif current_identity is None:
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, original[1])
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(original[0])
                    path.chmod(original[1])
                else:
                    descriptor, temporary_name = tempfile.mkstemp(
                        prefix=f".{path.name}.manageroo-rollback-",
                        dir=path.parent,
                    )
                    temporary = Path(temporary_name)
                    try:
                        with os.fdopen(descriptor, "wb") as handle:
                            handle.write(original[0])
                        temporary.chmod(original[1])
                        preserved_descriptor, preserved_name = tempfile.mkstemp(
                            prefix=f".{path.name}.manageroo-preserved-",
                            dir=path.parent,
                        )
                        os.close(preserved_descriptor)
                        preserved = Path(preserved_name)
                        try:
                            os.replace(path, preserved)
                        except OSError:
                            preserved.unlink(missing_ok=True)
                            raise
                        preserved_identity = self._preserved_path_identity(preserved)
                        if preserved_identity != current_identity:
                            self._restore_preserved_path(preserved, path)
                            unrestored.append(relative)
                            continue
                        recovery = self._retain_preserved_path(preserved, path)
                        if recovery is None:
                            self._restore_preserved_path(preserved, path)
                            unrestored.append(relative)
                            continue
                        if self._preserved_path_identity(recovery) != current_identity:
                            self._restore_preserved_path(preserved, path)
                            unrestored.append(relative)
                            continue
                        try:
                            os.link(temporary, path, follow_symlinks=False)
                        except OSError:
                            self._restore_preserved_path(preserved, path)
                            unrestored.append(relative)
                            continue
                        preserved.unlink()
                        if self._preserved_path_identity(recovery) != current_identity:
                            os.replace(recovery, path)
                            unrestored.append(relative)
                    finally:
                        if temporary.exists():
                            temporary.unlink()
                if self._source_path_identity(relative) != original_identity:
                    unrestored.append(relative)
            except (OSError, SafetyError):
                unrestored.append(relative)
        return sorted(set(unrestored))

    def apply_patch_to_source(self, patch: Path) -> None:
        self.assert_source_unchanged()
        if not patch.exists() or patch.stat().st_size == 0:
            return
        expected_source = self._visible_tree_identity(self.workspace)
        check = self.runner.run(["git", "apply", "--check", "--binary", str(patch)], cwd=self.source_repo, timeout_seconds=300)
        if not check.passed:
            raise SafetyError("Final patch no longer applies cleanly to the source tree:\n" + check.stderr)
        self.assert_source_unchanged()
        source_states = self._capture_source_states(expected_source)
        applied = self.runner.run(["git", "apply", "--binary", str(patch)], cwd=self.source_repo, timeout_seconds=300)
        if not applied.passed:
            raise SafetyError("Failed to apply validated patch:\n" + applied.stderr)
        try:
            actual_source = self._visible_tree_identity(self.source_repo)
        except SafetyError as exc:
            mismatch = str(exc)
        else:
            changed = sorted(
                path
                for path in set(expected_source) | set(actual_source)
                if expected_source.get(path) != actual_source.get(path)
            )
            mismatch = ", ".join(changed)
        if mismatch:
            reverse_check = self.runner.run(
                ["git", "apply", "--reverse", "--check", "--binary", str(patch)],
                cwd=self.source_repo,
                timeout_seconds=300,
            )
            if not reverse_check.passed:
                unrestored = self._restore_unchanged_source_paths(expected_source, source_states)
                preserved = ", ".join(unrestored)
                raise SafetyError(
                    "Source tree changed during patch application, and Manageroo could not "
                    "safely reverse its complete patch. Manageroo restored every unchanged "
                    "patched path from its pre-apply state; concurrently changed paths were "
                    f"preserved: {preserved}\n" + reverse_check.stderr
                )
            reversed_patch = self.runner.run(
                ["git", "apply", "--reverse", "--binary", str(patch)],
                cwd=self.source_repo,
                timeout_seconds=300,
            )
            if not reversed_patch.passed:
                unrestored = self._restore_unchanged_source_paths(expected_source, source_states)
                preserved = ", ".join(unrestored)
                raise SafetyError(
                    "Source tree changed during patch application, and Manageroo failed to "
                    "reverse its validated patch. Manageroo restored every unchanged patched "
                    "path from its pre-apply state; concurrently changed paths were preserved: "
                    f"{preserved}\n" + reversed_patch.stderr
                )
            raise SafetyError(
                "Source tree changed during patch application. Manageroo reversed only its "
                f"validated patch; concurrent source changes were preserved: {mismatch}"
            )

    def patch_already_applied_to_source(self, patch: Path) -> bool:
        if not patch.exists() or patch.stat().st_size == 0:
            return True
        return self.runner.run(["git", "apply", "--reverse", "--check", "--binary", str(patch)], cwd=self.source_repo, timeout_seconds=300).passed

    def rollback_patch_from_source(self, patch: Path) -> None:
        """Reverse only Manageroo's exact patch after a late delivery failure."""
        if not patch.exists() or patch.stat().st_size == 0:
            self.assert_source_unchanged()
            return
        check = self.runner.run(
            ["git", "apply", "--reverse", "--check", "--binary", str(patch)],
            cwd=self.source_repo,
            timeout_seconds=300,
        )
        if not check.passed:
            raise SafetyError(
                "Manageroo could not prove that only its exact delivery patch remains applied; "
                "automatic rollback stopped.\n" + check.stderr
            )
        reverted = self.runner.run(
            ["git", "apply", "--reverse", "--binary", str(patch)],
            cwd=self.source_repo,
            timeout_seconds=300,
        )
        if not reverted.passed:
            raise SafetyError("Manageroo could not reverse its delivery patch.\n" + reverted.stderr)
        self.assert_source_unchanged()

    def clone_for_review(self, destination: Path) -> Path:
        lexical = destination.expanduser()
        if lexical.exists() or lexical.is_symlink():
            raise SafetyError(f"Reviewer clone destination already exists; refusing destructive replacement: {lexical}")
        unresolved = lexical if lexical.is_absolute() else (Path.cwd() / lexical)
        nearest = unresolved.parent
        while not nearest.exists() and nearest != nearest.parent:
            nearest = nearest.parent
        try:
            nearest.resolve(strict=True).relative_to(self.run_root)
        except (OSError, ValueError) as exc:
            raise SafetyError("Reviewer clone destination must stay inside the run root.") from exc
        lexical.parent.mkdir(parents=True, exist_ok=True)
        destination = lexical.resolve(strict=False)
        try:
            relative = destination.relative_to(self.run_root)
        except ValueError as exc:
            raise SafetyError("Reviewer clone destination must stay inside the run root.") from exc
        if not relative.parts or destination in {self.run_root, self.workspace, self.source_repo}:
            raise SafetyError("Reviewer clone destination is not an approved scratch path.")
        try:
            destination.parent.resolve(strict=True).relative_to(self.run_root)
        except (OSError, ValueError) as exc:
            raise SafetyError("Reviewer clone destination resolves outside the run root.") from exc
        result = self.runner.run(
            ["git", "clone", "--no-hardlinks", "--quiet", str(self.workspace), str(destination)],
            cwd=self.run_root,
            timeout_seconds=300,
        )
        if not result.passed:
            raise SafetyError(result.stderr or "Could not create reviewer clone.")
        return destination
