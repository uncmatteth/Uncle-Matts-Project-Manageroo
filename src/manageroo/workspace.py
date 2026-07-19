from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import SafetyError
from .inventory import git_visible_files
from .runner import CommandRunner
from .util import atomic_write_json, copy_file_preserving_mode, safe_repo_relative, sha256_file


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
        self.pending_validation_path = (
            self.run_root / "controller" / "pending-workspace-validation.json"
        )
        self.baseline_commit = ""

    def capture_source(self) -> list[SourceFile]:
        records: list[SourceFile] = []
        for relative in git_visible_files(self.source_repo, self.runner):
            path = self.source_repo / relative
            if not path.is_file() or path.is_symlink():
                continue
            stat = path.stat()
            records.append(
                SourceFile(
                    path=relative,
                    sha256=sha256_file(path),
                    bytes=stat.st_size,
                    mode=stat.st_mode & 0o777,
                )
            )
        atomic_write_json(self.snapshot_path, {"files": [asdict(item) for item in records]})
        return records

    def create(self) -> Path:
        if self.workspace.exists() or self.snapshot_path.exists():
            raise SafetyError(
                "Run workspace or source snapshot already exists; creation is immutable for an existing run."
            )
        self.run_root.mkdir(parents=True, exist_ok=True)
        records = self.capture_source()
        self.workspace.mkdir(parents=True)
        for record in records:
            source = self.source_repo / record.path
            destination = self.workspace / safe_repo_relative(record.path)
            copy_file_preserving_mode(source, destination)

        self._git(["init", "-b", "manageroo-internal"])
        self._git(["config", "user.name", "MANAGEROO Controller"])
        self._git(["config", "user.email", "manageroo@local.invalid"])
        self._git(["add", "-A"])
        self._git(["commit", "-m", "MANAGEROO isolated baseline"], hooks=False)
        self.baseline_commit = self.head()

        hook = self.workspace / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            "#!/bin/sh\n"
            "echo 'Agent commits are forbidden. The MANAGEROO controller owns checkpoints.' >&2\n"
            "exit 73\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
        return self.workspace

    def _clear_pending_validation_marker(self) -> None:
        try:
            if self.pending_validation_path.is_file():
                self.pending_validation_path.unlink()
        except OSError as exc:
            raise SafetyError(
                "Manageroo could not clear the pending workspace-validation marker: "
                + str(exc)
            ) from exc

    def _discard_ignored_state(self) -> None:
        self._git(["clean", "-fdX"])

    def _discard_uncheckpointed_state(self) -> None:
        self._discard_ignored_state()
        status = self._git(["status", "--porcelain"])
        if status.stdout.strip():
            self._git(["reset", "--hard", "HEAD"])
            self._git(["clean", "-fdx"])
            remaining = self._git(["status", "--porcelain", "--ignored"])
            if remaining.stdout.strip():
                raise SafetyError(
                    "Run workspace contains unverified changes that could not be discarded safely."
                )
        self._clear_pending_validation_marker()

    def _completed_write_job_owns_pending_state(self) -> bool:
        if not self.pending_validation_path.is_file():
            return False
        try:
            marker = json.loads(self.pending_validation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyError(
                "Pending workspace-validation state is unreadable: "
                f"{self.pending_validation_path}: {exc}"
            ) from exc
        if not isinstance(marker, dict) or marker.get("sandbox") != "workspace-write":
            raise SafetyError("Pending workspace-validation marker is invalid.")
        job_id = str(marker.get("job_id") or "").strip()
        if not job_id:
            raise SafetyError("Pending workspace-validation marker has no job id.")
        job_path = self.run_root / "jobs" / f"{job_id}.json"
        if not job_path.is_file():
            return False
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyError(f"Run job state is unreadable during resume: {job_path}: {exc}") from exc
        return bool(
            isinstance(job, dict)
            and job.get("status") == "complete"
            and job.get("sandbox") == "workspace-write"
        )

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
            argv.extend(["-c", "core.hooksPath=/dev/null"])
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

    def checkpoint(self, message: str) -> str:
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

    def apply_patch_to_source(self, patch: Path) -> None:
        self.assert_source_unchanged()
        if not patch.exists() or patch.stat().st_size == 0:
            return
        check = self.runner.run(
            ["git", "apply", "--check", "--binary", str(patch)],
            cwd=self.source_repo,
            timeout_seconds=300,
        )
        if not check.passed:
            raise SafetyError("Final patch no longer applies cleanly to the source tree:\n" + check.stderr)
        applied = self.runner.run(
            ["git", "apply", "--binary", str(patch)],
            cwd=self.source_repo,
            timeout_seconds=300,
        )
        if not applied.passed:
            raise SafetyError("Failed to apply validated patch:\n" + applied.stderr)

    def patch_already_applied_to_source(self, patch: Path) -> bool:
        if not patch.exists() or patch.stat().st_size == 0:
            return True
        reverse_check = self.runner.run(
            ["git", "apply", "--reverse", "--check", "--binary", str(patch)],
            cwd=self.source_repo,
            timeout_seconds=300,
        )
        return reverse_check.passed

    def clone_for_review(self, destination: Path) -> Path:
        destination = destination.expanduser().resolve()
        try:
            relative = destination.relative_to(self.run_root)
        except ValueError as exc:
            raise SafetyError("Reviewer clone destination must stay inside the run root.") from exc
        if not relative.parts or destination in {self.run_root, self.workspace, self.source_repo}:
            raise SafetyError("Reviewer clone destination is not an approved scratch path.")
        if destination.exists():
            raise SafetyError(
                f"Reviewer clone destination already exists; refusing destructive replacement: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner.run(
            ["git", "clone", "--no-hardlinks", "--quiet", str(self.workspace), str(destination)],
            cwd=self.run_root,
            timeout_seconds=300,
        )
        if not result.passed:
            raise SafetyError(result.stderr or "Could not create reviewer clone.")
        return destination
