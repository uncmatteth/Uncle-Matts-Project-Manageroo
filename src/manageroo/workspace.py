from __future__ import annotations

import os
import shutil
import tempfile
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

    def _visible_file_records(self, repo: Path, *, label: str) -> dict[str, SourceFile]:
        records: dict[str, SourceFile] = {}
        for relative in git_visible_files(repo, self.runner):
            path = repo / relative
            if not path.exists():
                continue
            if not path.is_file() or path.is_symlink():
                raise SafetyError(f"{label} contains a visible non-regular file: {relative}")
            records[relative] = SourceFile(
                path=relative,
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
                mode=0o755 if os.access(path, os.X_OK) else 0o644,
            )
        return records

    def _expected_records_after_patch(self, patch: Path) -> dict[str, SourceFile]:
        if not self.baseline_commit:
            raise SafetyError("Run workspace baseline commit is missing.")
        self.run_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="expected-source-", dir=self.run_root) as temp:
            expected_repo = Path(temp) / "repo"
            clone = self.runner.run(
                ["git", "clone", "--no-hardlinks", "--quiet", str(self.workspace), str(expected_repo)],
                cwd=self.run_root,
                timeout_seconds=300,
            )
            if not clone.passed:
                raise SafetyError("Could not create expected source verifier clone:\n" + clone.stderr)
            checkout = self.runner.run(
                ["git", "checkout", "--quiet", self.baseline_commit],
                cwd=expected_repo,
                timeout_seconds=300,
            )
            if not checkout.passed:
                raise SafetyError("Could not check out source snapshot baseline:\n" + checkout.stderr)
            if patch.exists() and patch.stat().st_size > 0:
                check = self.runner.run(
                    ["git", "apply", "--check", "--binary", str(patch)],
                    cwd=expected_repo,
                    timeout_seconds=300,
                )
                if not check.passed:
                    raise SafetyError("Final patch cannot build approved source state:\n" + check.stderr)
                applied = self.runner.run(
                    ["git", "apply", "--binary", str(patch)],
                    cwd=expected_repo,
                    timeout_seconds=300,
                )
                if not applied.passed:
                    raise SafetyError("Failed to build approved source state:\n" + applied.stderr)
            return self._visible_file_records(expected_repo, label="Approved delivery state")

    def assert_source_matches_snapshot_plus_patch(self, patch: Path) -> None:
        expected = self._expected_records_after_patch(patch)
        current = self._visible_file_records(self.source_repo, label="Source tree")
        if set(current) != set(expected):
            missing = sorted(set(expected) - set(current))
            extra = sorted(set(current) - set(expected))
            raise SafetyError(
                "Source tree does not match approved delivery patch. "
                f"Missing={missing}; extra={extra}"
            )
        changed = sorted(
            relative
            for relative, expected_record in expected.items()
            if current[relative].sha256 != expected_record.sha256
            or current[relative].mode != expected_record.mode
        )
        if changed:
            raise SafetyError(
                "Source tree does not match approved delivery patch: " + ", ".join(changed)
            )

    def delivery_patch_already_applied_cleanly(self, patch: Path) -> bool:
        try:
            self.assert_source_matches_snapshot_plus_patch(patch)
            return True
        except SafetyError as delivery_error:
            try:
                self.assert_source_unchanged()
            except SafetyError:
                raise delivery_error
            return False

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
        self.assert_source_matches_snapshot_plus_patch(patch)

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
