from __future__ import annotations

import os
import shutil
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
        self.baseline_commit = ""

    def capture_source(self) -> list[SourceFile]:
        records: list[SourceFile] = []
        for relative in git_visible_files(self.source_repo, self.runner):
            path = self.source_repo / relative
            if not path.is_file() or path.is_symlink():
                continue
            records.append(
                SourceFile(
                    path=relative,
                    sha256=sha256_file(path),
                    bytes=path.stat().st_size,
                    mode=path.stat().st_mode & 0o777,
                )
            )
        atomic_write_json(self.snapshot_path, {"files": [asdict(item) for item in records]})
        return records

    def create(self) -> Path:
        records = self.capture_source()
        if self.workspace.exists():
            raise SafetyError(f"Workspace already exists: {self.workspace}")
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

    def load_existing(self) -> Path:
        if not self.workspace.is_dir() or not (self.workspace / ".git").is_dir():
            raise SafetyError(f"Run workspace is missing or not a Git repository: {self.workspace}")
        if not self.snapshot_path.is_file():
            raise SafetyError(f"Run source snapshot is missing: {self.snapshot_path}")
        roots = self._git(["rev-list", "--max-parents=0", "HEAD"]).stdout.splitlines()
        if not roots:
            raise SafetyError("Run workspace has no baseline commit.")
        self.baseline_commit = roots[0].strip()
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
        self._git(["add", "-A"])
        status = self._git(["status", "--porcelain"])
        if not status.stdout.strip():
            return self.head()
        self._git(["commit", "-m", message], hooks=False)
        return self.head()

    def write_patch(self, destination: Path) -> Path:
        result = self._git(["diff", "--binary", self.baseline_commit, "HEAD", "--"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(result.stdout, encoding="utf-8", newline="\n")
        return destination

    def assert_source_unchanged(self) -> None:
        import json

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
            if not path.is_file() or sha256_file(path) != record["sha256"]:
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
        if destination.exists():
            shutil.rmtree(destination)
        result = self.runner.run(
            ["git", "clone", "--no-hardlinks", "--quiet", str(self.workspace), str(destination)],
            cwd=self.run_root,
            timeout_seconds=300,
        )
        if not result.passed:
            raise SafetyError(result.stderr or "Could not create reviewer clone.")
        return destination
