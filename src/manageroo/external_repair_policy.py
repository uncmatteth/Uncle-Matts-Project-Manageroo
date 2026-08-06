from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
from pathlib import Path
from typing import Any

from .errors import SafetyError, ValidationError
from .policy import ScopePolicy
from .util import atomic_write_json, read_json, safe_repo_relative


def _checkpoint_message(name: str, run_id: str, baseline: str) -> str:
    return f"MANAGEROO command-owned {name} repair lane run={run_id} baseline={baseline}"


def _checkpoint_manifest_path(orchestrator: Any, name: str) -> Any:
    safe_name = "".join(char if char.isalnum() or char in "-_." else "-" for char in name).strip("-")
    if not safe_name:
        raise SafetyError("External repair lane name cannot be empty.")
    return orchestrator.artifacts.root / "review" / "external-state" / f"{safe_name}-checkpoint.json"


def _actual_checkpoint_paths(orchestrator: Any, baseline: str, checkpoint: str) -> list[str]:
    assert orchestrator.workspace is not None
    result = orchestrator.runner.run(
        ["git", "diff", "--name-only", "-z", baseline, checkpoint, "--"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not result.passed:
        raise SafetyError("Could not inspect resumed command-owned checkpoint paths.")
    return sorted({safe_repo_relative(item) for item in result.stdout.split("\0") if item})


def _staged_workspace_tree(orchestrator: Any) -> str:
    """Capture the exact workspace tree that the controller approved for checkpointing."""

    assert orchestrator.workspace is not None
    staged = orchestrator.runner.run(
        ["git", "add", "-A"],
        cwd=orchestrator.workspace,
        timeout_seconds=120,
    )
    tree = orchestrator.runner.run(
        ["git", "write-tree"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not staged.passed or not tree.passed or not tree.stdout.strip():
        raise SafetyError("Could not capture the approved external repair workspace tree.")
    return tree.stdout.strip()


def _checkpoint_tree(orchestrator: Any, checkpoint: str) -> str:
    assert orchestrator.workspace is not None
    result = orchestrator.runner.run(
        ["git", "rev-parse", f"{checkpoint}^{{tree}}"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not result.passed or not result.stdout.strip():
        raise SafetyError("Could not inspect the external repair checkpoint tree.")
    return result.stdout.strip()


def _untracked_paths(orchestrator: Any, *, ignored: bool) -> set[str]:
    assert orchestrator.workspace is not None
    argv = ["git", "ls-files", "--others", "-z", "--exclude-standard"]
    if ignored:
        argv.append("--ignored")
    result = orchestrator.runner.run(
        [*argv, "--"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not result.passed:
        kind = "ignored" if ignored else "untracked"
        raise SafetyError(f"Could not inspect {kind} external repair workspace paths.")
    return {safe_repo_relative(item) for item in result.stdout.split("\0") if item}


def _ignored_entry_state(
    orchestrator: Any, path: str, *, root: Path | None = None
) -> tuple[str, int, int, int, int, str]:
    """Fingerprint an ignored entry's type, identity, mode, and content without following links."""

    assert orchestrator.workspace is not None
    entry = (root if root is not None else orchestrator.workspace) / path
    try:
        before = entry.lstat()
        if stat.S_ISLNK(before.st_mode):
            target = os.readlink(entry)
            after = entry.lstat()
            if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_mtime_ns,
            ):
                raise SafetyError(f"Ignored workspace entry changed while inspecting {path}.")
            digest = hashlib.sha256(os.fsencode(target)).hexdigest()
            kind = "symlink"
            inspected = after
        elif stat.S_ISREG(before.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(entry, flags)
            try:
                inspected = os.fstat(descriptor)
                if not stat.S_ISREG(inspected.st_mode) or (
                    inspected.st_dev,
                    inspected.st_ino,
                ) != (before.st_dev, before.st_ino):
                    raise SafetyError(f"Ignored workspace entry changed while inspecting {path}.")
                content_hash = hashlib.sha256()
                while chunk := os.read(descriptor, 1024 * 1024):
                    content_hash.update(chunk)
                after = os.fstat(descriptor)
                if (
                    inspected.st_size,
                    inspected.st_mtime_ns,
                    inspected.st_ctime_ns,
                ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SafetyError(f"Ignored workspace entry changed while inspecting {path}.")
                inspected = after
                digest = content_hash.hexdigest()
                kind = "file"
            finally:
                os.close(descriptor)
        else:
            inspected = before
            digest = ""
            kind = "other"
    except SafetyError:
        raise
    except OSError as exc:
        raise SafetyError(f"Could not inspect ignored workspace entry {path}: {exc}") from exc
    return (
        kind,
        stat.S_IMODE(inspected.st_mode),
        inspected.st_dev,
        inspected.st_ino,
        inspected.st_size,
        digest,
    )


def _ignored_state(
    orchestrator: Any, paths: set[str]
) -> dict[str, tuple[str, int, int, int, int, str]]:
    return {path: _ignored_entry_state(orchestrator, path) for path in sorted(paths)}


def _ignored_state_payload(
    state: dict[str, tuple[str, int, int, int, int, str]],
) -> dict[str, list[str | int]]:
    return {path: list(entry) for path, entry in sorted(state.items())}


def _persisted_ignored_state(
    payload: dict[str, Any], *, name: str
) -> dict[str, tuple[str, int, int, int, int, str]]:
    raw_state = payload.get("ignored_state", {})
    if not isinstance(raw_state, dict):
        raise SafetyError(f"Command-owned {name} checkpoint ignored state is invalid.")
    state: dict[str, tuple[str, int, int, int, int, str]] = {}
    for raw_path, raw_entry in raw_state.items():
        path = safe_repo_relative(str(raw_path))
        if not isinstance(raw_entry, list) or len(raw_entry) != 6:
            raise SafetyError(f"Command-owned {name} checkpoint ignored state is invalid.")
        kind, mode, device, inode, size, digest = raw_entry
        if (
            not isinstance(kind, str)
            or kind not in {"file", "symlink", "other"}
            or any(type(value) is not int for value in (mode, device, inode, size))
            or not isinstance(digest, str)
        ):
            raise SafetyError(f"Command-owned {name} checkpoint ignored state is invalid.")
        state[path] = (kind, mode, device, inode, size, digest)
    return state


def _verify_ignored_state(
    orchestrator: Any,
    *,
    name: str,
    expected: dict[str, tuple[str, int, int, int, int, str]],
) -> None:
    paths = _untracked_paths(orchestrator, ignored=True)
    if paths != set(expected) or _ignored_state(orchestrator, paths) != expected:
        raise SafetyError(f"Command-owned {name} checkpoint ignored workspace data changed.")


def _checkpoint_ignored_collisions(
    orchestrator: Any, checkpoint: str, ignored_paths: set[str]
) -> set[str]:
    if not ignored_paths:
        return set()
    assert orchestrator.workspace is not None
    result = orchestrator.runner.run(
        [
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            checkpoint,
            "--",
            *(f":(literal){path}" for path in sorted(ignored_paths)),
        ],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not result.passed:
        raise SafetyError("Could not inspect external repair checkpoint path collisions.")
    return {safe_repo_relative(item) for item in result.stdout.split("\0") if item}


def _materialize_checkpoint_workspace(
    orchestrator: Any,
    *,
    checkpoint: str,
    recovery_root: Path,
) -> Path:
    """Build a clean checkpoint workspace without changing the live workspace."""

    assert orchestrator.workspace is not None
    git_dir = orchestrator.workspace / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise SafetyError("External repair workspace Git metadata is not a safe directory.")
    staged = recovery_root / "replacement-workspace"
    staged.mkdir(mode=0o700)
    shutil.copytree(git_dir, staged / ".git", symlinks=True)
    reset = orchestrator.runner.run(
        ["git", "reset", "--hard", checkpoint],
        cwd=staged,
        timeout_seconds=120,
    )
    head = orchestrator.runner.run(
        ["git", "rev-parse", "HEAD"],
        cwd=staged,
        timeout_seconds=60,
    )
    status = orchestrator.runner.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=staged,
        timeout_seconds=60,
    )
    if (
        not reset.passed
        or not head.passed
        or head.stdout.strip() != checkpoint
        or not status.passed
        or status.stdout.strip()
    ):
        raise SafetyError("Could not materialize the external repair checkpoint safely.")
    return staged


def _replace_workspace_from_checkpoint(
    orchestrator: Any,
    *,
    name: str,
    checkpoint: str,
    preserved_ignored_state: dict[str, tuple[str, int, int, int, int, str]],
) -> Path:
    """Install a staged checkpoint and retain the displaced workspace for recovery."""

    assert orchestrator.workspace is not None
    safe_name = "".join(
        char if char.isalnum() or char in "-_." else "-" for char in name
    ).strip("-") or "external-repair"
    quarantine_root = (
        orchestrator.artifacts.root
        / "review"
        / "external-state"
        / "workspace-quarantine"
        / f"{safe_name}-{secrets.token_hex(8)}"
    )
    quarantine_root.mkdir(parents=True, mode=0o700)
    staged = _materialize_checkpoint_workspace(
        orchestrator,
        checkpoint=checkpoint,
        recovery_root=quarantine_root,
    )

    for path, expected in sorted(preserved_ignored_state.items()):
        if _ignored_entry_state(orchestrator, path) != expected:
            raise SafetyError(f"Command-owned {name} checkpoint ignored workspace data changed.")
        source = orchestrator.workspace / path
        destination = staged / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            raise SafetyError(
                f"Command-owned {name} checkpoint collides with preserved ignored workspace data."
            )
        os.replace(source, destination)
        if _ignored_entry_state(orchestrator, path, root=staged) != expected:
            raise SafetyError(f"Command-owned {name} checkpoint ignored workspace data changed.")

    previous = quarantine_root / "previous-workspace"
    try:
        os.rename(orchestrator.workspace, previous)
        if orchestrator.workspace.exists() or orchestrator.workspace.is_symlink():
            concurrent = quarantine_root / "concurrent-workspace"
            os.rename(orchestrator.workspace, concurrent)
        os.rename(staged, orchestrator.workspace)
    except OSError as exc:
        raise SafetyError(
            "External repair workspace replacement failed; recoverable state remains at "
            f"{quarantine_root}: {exc}"
        ) from exc
    return previous


def _restore_checkpoint(
    orchestrator: Any,
    *,
    name: str,
    checkpoint: str,
    preserved_ignored_state: dict[str, tuple[str, int, int, int, int, str]],
) -> None:
    assert orchestrator.workspace is not None
    status = orchestrator.runner.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not status.passed or status.stdout.strip():
        raise SafetyError(
            f"Command-owned {name} checkpoint restoration requires a clean workspace."
        )
    _verify_ignored_state(
        orchestrator,
        name=name,
        expected=preserved_ignored_state,
    )
    collisions = _checkpoint_ignored_collisions(
        orchestrator, checkpoint, set(preserved_ignored_state)
    )
    if collisions:
        raise SafetyError(
            f"Command-owned {name} checkpoint collides with preserved ignored workspace data."
        )
    _replace_workspace_from_checkpoint(
        orchestrator,
        name=name,
        checkpoint=checkpoint,
        preserved_ignored_state=preserved_ignored_state,
    )
    head = orchestrator.runner.run(
        ["git", "rev-parse", "HEAD"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    status = orchestrator.runner.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    ignored_state_matches = True
    try:
        _verify_ignored_state(
            orchestrator,
            name=name,
            expected=preserved_ignored_state,
        )
    except SafetyError:
        ignored_state_matches = False
    if (
        not head.passed
        or head.stdout.strip() != checkpoint
        or not status.passed
        or status.stdout.strip()
        or not ignored_state_matches
    ):
        raise SafetyError(f"Command-owned {name} checkpoint could not be restored exactly.")


def _existing_checkpoint(
    orchestrator: Any,
    name: str,
    *,
    baseline: str,
) -> tuple[str, list[str], dict[str, tuple[str, int, int, int, int, str]]] | None:
    """Resume only a checkpoint persisted for this exact durable run and baseline."""

    assert orchestrator.workspace is not None
    manifest_path = _checkpoint_manifest_path(orchestrator, name)
    if not manifest_path.is_file():
        return None
    try:
        payload = read_json(manifest_path)
    except Exception as exc:
        raise SafetyError(f"Command-owned {name} checkpoint manifest is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SafetyError(f"Command-owned {name} checkpoint manifest is invalid.")
    if str(payload.get("run_id") or "") != str(orchestrator.run_id):
        return None
    if str(payload.get("name") or "") != name:
        raise SafetyError(f"Command-owned {name} checkpoint manifest names another lane.")
    if str(payload.get("baseline") or "") != baseline:
        return None
    checkpoint = str(payload.get("checkpoint") or "").strip()
    if not checkpoint:
        raise SafetyError(f"Command-owned {name} checkpoint manifest has no checkpoint SHA.")
    verify = orchestrator.runner.run(
        ["git", "cat-file", "-e", f"{checkpoint}^{{commit}}"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not verify.passed:
        raise SafetyError(f"Command-owned {name} checkpoint no longer exists: {checkpoint}")
    ancestor = orchestrator.runner.run(
        ["git", "merge-base", "--is-ancestor", baseline, checkpoint],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not ancestor.passed:
        raise SafetyError(
            f"Command-owned {name} checkpoint is not descended from this run baseline."
        )
    changed_paths = _actual_checkpoint_paths(orchestrator, baseline, checkpoint)
    recorded_paths = sorted({safe_repo_relative(str(item)) for item in payload.get("changed_paths", []) or []})
    if recorded_paths != changed_paths:
        raise SafetyError(f"Command-owned {name} checkpoint manifest does not match its Git diff.")
    ignored_state = _persisted_ignored_state(payload, name=name)
    if _checkpoint_ignored_collisions(orchestrator, checkpoint, set(ignored_state)):
        raise SafetyError(
            f"Command-owned {name} checkpoint collides with preserved ignored workspace data."
        )
    return checkpoint, changed_paths, ignored_state


def _existing_checkpoint_chain(
    orchestrator: Any,
    commands: list[tuple[str, Any]],
    *,
    allowed_paths: list[str],
    input_fingerprint: str,
) -> list[dict[str, Any]]:
    """Validate and restore the contiguous same-run checkpoint prefix."""

    chain: list[dict[str, Any]] = []
    policy = ScopePolicy(tuple(allowed_paths))
    expected_baseline = ""
    missing_prefix = False
    for lane_index, (name, _argv_template) in enumerate(commands):
        manifest_path = _checkpoint_manifest_path(orchestrator, name)
        if not manifest_path.is_file():
            missing_prefix = True
            continue
        try:
            payload = read_json(manifest_path)
        except Exception as exc:
            raise SafetyError(f"Command-owned {name} checkpoint manifest is unreadable: {exc}") from exc
        if not isinstance(payload, dict):
            raise SafetyError(f"Command-owned {name} checkpoint manifest is invalid.")
        if str(payload.get("run_id") or "") != str(orchestrator.run_id):
            missing_prefix = True
            continue
        if missing_prefix:
            raise SafetyError(
                f"Command-owned {name} checkpoint chain is not contiguous in configured order."
            )
        recorded_index = payload.get("lane_index")
        if recorded_index is not None and recorded_index != lane_index:
            raise SafetyError(f"Command-owned {name} checkpoint lane order has changed.")
        recorded_fingerprint = str(payload.get("input_fingerprint") or "")
        if recorded_fingerprint and recorded_fingerprint != input_fingerprint:
            raise SafetyError(f"Command-owned {name} checkpoint inputs have changed.")
        baseline = str(payload.get("baseline") or "").strip()
        if not baseline:
            raise SafetyError(f"Command-owned {name} checkpoint manifest has no baseline SHA.")
        if expected_baseline and baseline != expected_baseline:
            raise SafetyError("Command-owned external repair checkpoint chain is invalid.")
        resumed = _existing_checkpoint(orchestrator, name, baseline=baseline)
        if resumed is None:
            raise SafetyError(f"Command-owned {name} checkpoint manifest is stale.")
        checkpoint, changed_paths, ignored_state = resumed
        policy.validate_paths(changed_paths)
        if chain and ignored_state != chain[0]["ignored_state"]:
            raise SafetyError("Command-owned external repair checkpoint ignored state changed.")
        chain.append(
            {
                "name": name,
                "baseline": baseline,
                "checkpoint": checkpoint,
                "changed_paths": changed_paths,
                "ignored_state": ignored_state,
            }
        )
        expected_baseline = checkpoint

    if not chain:
        return []
    current_head = orchestrator.mirror.head()
    boundaries = {chain[0]["baseline"]}
    boundaries.update(item["checkpoint"] for item in chain)
    if current_head not in boundaries:
        raise SafetyError(
            "Command-owned external repair workspace HEAD is outside the validated checkpoint chain."
        )
    _restore_checkpoint(
        orchestrator,
        name="interrupted external review/repair",
        checkpoint=chain[-1]["checkpoint"],
        preserved_ignored_state=chain[-1]["ignored_state"],
    )
    return chain


def _require_clean_lane_start(
    orchestrator: Any, name: str
) -> dict[str, tuple[str, int, int, int, int, str]]:
    assert orchestrator.workspace is not None
    status = orchestrator.runner.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    if not status.passed:
        raise SafetyError(f"Could not inspect workspace before {name} repair lane: {status.stderr}")
    if status.stdout.strip():
        raise SafetyError(
            f"Command-owned {name} repair lane requires a clean controller workspace before execution."
        )
    ignored_paths = _untracked_paths(orchestrator, ignored=True)
    return _ignored_state(orchestrator, ignored_paths)


def _rollback_lane(
    orchestrator: Any,
    *,
    name: str,
    baseline: str,
    preserved_ignored_state: dict[str, tuple[str, int, int, int, int, str]],
) -> None:
    """Restore the exact clean pre-command checkpoint and verify rollback before continuation."""

    assert orchestrator.workspace is not None
    _replace_workspace_from_checkpoint(
        orchestrator,
        name=name,
        checkpoint=baseline,
        preserved_ignored_state=preserved_ignored_state,
    )
    preserved_ignored_paths = set(preserved_ignored_state)
    head = orchestrator.runner.run(
        ["git", "rev-parse", "HEAD"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    status = orchestrator.runner.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=orchestrator.workspace,
        timeout_seconds=60,
    )
    remaining_unmanaged = _untracked_paths(orchestrator, ignored=False) | _untracked_paths(
        orchestrator, ignored=True
    )
    if (
        not head.passed
        or head.stdout.strip() != baseline
        or not status.passed
        or status.stdout.strip()
        or remaining_unmanaged != preserved_ignored_paths
        or _ignored_state(orchestrator, preserved_ignored_paths) != preserved_ignored_state
    ):
        raise SafetyError(
            f"Command-owned {name} repair lane failed and rollback could not be verified."
        )


def _command_config(commands: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": str(name), "argv_template": [str(item) for item in argv_template]}
        for name, argv_template in commands
    ]


def _repair_input_fingerprint(
    *,
    brief: str,
    plan: dict,
    gate_results: list[dict],
    commands: list[tuple[str, Any]],
    allowed_paths: list[str],
) -> str:
    payload = {
        "run_input": {"brief": brief, "plan": plan, "gate_results": gate_results},
        "commands": _command_config(commands),
        "allowed_paths": allowed_paths,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_persisted_report(
    orchestrator: Any,
    existing: Any,
    *,
    commands: list[tuple[str, Any]],
    allowed_paths: list[str],
    input_fingerprint: str,
) -> dict:
    if not isinstance(existing, dict):
        raise SafetyError("Persisted external review/repair report is malformed.")
    summary = existing.get("summary")
    if not isinstance(summary, dict):
        raise SafetyError("Persisted external review/repair report has no valid summary.")
    if summary.get("continuation_safe") is not True:
        raise SafetyError(
            "Persisted external review/repair state is not safe to continue. Manual inspection is required."
        )
    failed = [str(item) for item in summary.get("failed", []) or [] if str(item)]
    if failed:
        raise ValidationError(
            "Configured external review/repair lane failed previously: "
            + ", ".join(failed)
            + ". See review/external-review-repair.json."
        )

    resume = existing.get("resume")
    if not isinstance(resume, dict):
        raise SafetyError("Persisted external review/repair report has no resume identity.")
    if str(resume.get("run_id") or "") != str(orchestrator.run_id):
        raise SafetyError("Persisted external review/repair report belongs to another run.")
    if resume.get("commands") != _command_config(commands):
        raise SafetyError("Persisted external review/repair command configuration has changed.")
    if resume.get("allowed_paths") != allowed_paths:
        raise SafetyError("Persisted external review/repair allowed paths have changed.")
    if str(resume.get("input_fingerprint") or "") != input_fingerprint:
        raise SafetyError("Persisted external review/repair inputs have changed.")
    preserved_ignored_state = _persisted_ignored_state(
        resume, name="persisted external review/repair"
    )

    records = existing.get("records")
    if not isinstance(records, list) or len(records) != len(commands):
        raise SafetyError("Persisted external review/repair records do not match configured lanes.")
    expected_checkpoint = str(resume.get("initial_baseline") or "").strip()
    final_checkpoint = str(resume.get("final_checkpoint") or "").strip()
    if not expected_checkpoint or not final_checkpoint:
        raise SafetyError("Persisted external review/repair report has no checkpoint boundary.")

    policy = ScopePolicy(tuple(allowed_paths))
    for record, (name, _argv_template) in zip(records, commands, strict=True):
        if not isinstance(record, dict) or record.get("ok") is not True:
            raise SafetyError("Persisted external review/repair record is not a success.")
        if str(record.get("name") or "") != str(name):
            raise SafetyError("Persisted external review/repair lane order has changed.")
        baseline = str(record.get("baseline") or "").strip()
        if baseline != expected_checkpoint:
            raise SafetyError("Persisted external review/repair checkpoint chain is invalid.")
        changed_paths = sorted(
            {safe_repo_relative(str(item)) for item in record.get("changed_paths", []) or []}
        )
        policy.validate_paths(changed_paths)
        resumed = _existing_checkpoint(orchestrator, str(name), baseline=baseline)
        if resumed is None:
            raise SafetyError(f"Command-owned {name} checkpoint manifest is missing or stale.")
        checkpoint, actual_paths, ignored_state = resumed
        if ignored_state != preserved_ignored_state:
            raise SafetyError(f"Command-owned {name} checkpoint ignored state has changed.")
        if changed_paths:
            checkpoint_matches = str(record.get("checkpoint") or "") == checkpoint
        else:
            checkpoint_matches = not record.get("checkpoint") and checkpoint == baseline
        if not checkpoint_matches or changed_paths != actual_paths:
            raise SafetyError(f"Command-owned {name} persisted report does not match its checkpoint.")
        expected_checkpoint = checkpoint

    if expected_checkpoint != final_checkpoint:
        raise SafetyError("Persisted external review/repair final checkpoint is invalid.")
    _restore_checkpoint(
        orchestrator,
        name="persisted external review/repair",
        checkpoint=final_checkpoint,
        preserved_ignored_state=preserved_ignored_state,
    )
    return existing


def run_external_review_repair_lanes(
    self: Any,
    *,
    brief: str,
    plan: dict,
    gate_results: list[dict],
) -> dict | None:
    """Run or safely resume command-owned repair lanes with verified rollback boundaries."""

    assert self.workspace is not None
    commands = [
        (name, argv_template)
        for name, argv_template in self._external_review_repair_commands()
        if argv_template
    ]
    allowed_paths = sorted(
        {
            safe_repo_relative(path)
            for task in plan.get("tasks", [])
            for path in task.get("allowed_paths", [])
        }
    )
    input_fingerprint = _repair_input_fingerprint(
        brief=brief,
        plan=plan,
        gate_results=gate_results,
        commands=commands,
        allowed_paths=allowed_paths,
    )
    existing = self._artifact_json("review/external-review-repair.json")
    if existing is not None:
        return _validate_persisted_report(
            self,
            existing,
            commands=commands,
            allowed_paths=allowed_paths,
            input_fingerprint=input_fingerprint,
        )

    if not commands:
        return None
    if not allowed_paths:
        raise SafetyError("External review/repair lanes require at least one explicitly approved path.")

    input_payload = {
        "rule": (
            "AUTOREVIEW and Clawpatch are command-owned repair lanes. "
            "The controller must not freehand fixes from their findings."
        ),
        "allowed_paths": allowed_paths,
        "gate_results": gate_results,
        "task_plan_file": str(self.artifacts.root / "planning" / "task-plan.json"),
        "gates_file": str(self.artifacts.root / "verification" / "gates.json"),
    }
    self.artifacts.write_json("review/external-review-repair-input.json", input_payload)
    values = self._external_values(brief=brief)
    values.update(
        {
            "repo": str(self.workspace),
            "workspace": str(self.workspace),
            "source_repo": str(self.source_repo),
            "external_state_dir": str(self.artifacts.root / "review" / "external-state"),
            "task_plan_file": str(self.artifacts.root / "planning" / "task-plan.json"),
            "gates_file": str(self.artifacts.root / "verification" / "gates.json"),
            "external_review_repair_input_file": str(
                self.artifacts.root / "review" / "external-review-repair-input.json"
            ),
        }
    )
    (self.artifacts.root / "review" / "external-state").mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    failed: list[str] = []
    rollback_verified = True
    approved_ignored_state: dict[str, tuple[str, int, int, int, int, str]] | None = None
    checkpoint_chain = _existing_checkpoint_chain(
        self,
        commands,
        allowed_paths=allowed_paths,
        input_fingerprint=input_fingerprint,
    )
    for lane_index, (name, argv_template) in enumerate(commands):
        if lane_index < len(checkpoint_chain):
            resumed = checkpoint_chain[lane_index]
            approved_ignored_state = resumed["ignored_state"]
            changed_paths = resumed["changed_paths"]
            ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
            record = {
                "name": name,
                "enabled": True,
                "ok": True,
                "resumed_from_checkpoint": True,
                "baseline": resumed["baseline"],
                "command_owned_repair_lane": True,
                "ai_freehand_repair_allowed": False,
                "changed_paths": changed_paths,
            }
            if changed_paths:
                record["checkpoint"] = resumed["checkpoint"]
            records.append(record)
            continue

        baseline = self.mirror.head()
        preserved_ignored_state = _require_clean_lane_start(self, name)
        if (
            approved_ignored_state is not None
            and preserved_ignored_state != approved_ignored_state
        ):
            raise SafetyError("Command-owned external repair checkpoint ignored state changed.")
        approved_ignored_state = preserved_ignored_state
        before_command = baseline
        try:
            record = self._run_optional_external_command(
                name=name,
                argv_template=argv_template,
                values=values,
                cwd=self.workspace,
                timeout_seconds=600,
            )
            if not isinstance(record, dict):
                record = {
                    "name": name,
                    "enabled": True,
                    "ok": False,
                    "error": "External review/repair command returned a malformed result.",
                }
            else:
                record = dict(record)
                record.setdefault("name", name)
                record.setdefault("enabled", True)
            changed_paths = self.mirror.changed_paths(before_command)
            record.update(
                {
                    "command_owned_repair_lane": True,
                    "ai_freehand_repair_allowed": False,
                    "changed_paths": changed_paths,
                    "baseline": before_command,
                }
            )
            policy_error = ""
            if self.mirror.head() != before_command:
                policy_error = (
                    "External review/repair lane changed Git HEAD; the controller owns checkpoints."
                )
            try:
                ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
            except SafetyError as exc:
                policy_error = str(exc)
            if policy_error:
                record["ok"] = False
                record["policy_error"] = policy_error

            if record.get("ok"):
                _verify_ignored_state(
                    self,
                    name=name,
                    expected=preserved_ignored_state,
                )
                checkpoint = before_command
                checkpoint_paths: list[str] = []
                if changed_paths:
                    approved_tree = _staged_workspace_tree(self)
                    if _checkpoint_ignored_collisions(
                        self, approved_tree, set(preserved_ignored_state)
                    ):
                        raise SafetyError(
                            f"Command-owned {name} checkpoint collides with preserved ignored "
                            "workspace data."
                        )
                    checkpoint = self.mirror.checkpoint(
                        _checkpoint_message(name, str(self.run_id), before_command),
                        preserve_ignored=True,
                    )
                    if _checkpoint_tree(self, checkpoint) != approved_tree:
                        raise SafetyError(
                            "External review/repair lane content changed during checkpoint creation."
                        )
                    checkpoint_paths = _actual_checkpoint_paths(self, before_command, checkpoint)
                    ScopePolicy(tuple(allowed_paths)).validate_paths(checkpoint_paths)
                    if checkpoint_paths != changed_paths:
                        raise SafetyError(
                            "External review/repair lane paths changed during checkpoint creation."
                        )
                    record["checkpoint"] = checkpoint
                    record["changed_paths"] = checkpoint_paths
                _verify_ignored_state(
                    self,
                    name=name,
                    expected=preserved_ignored_state,
                )
                atomic_write_json(
                    _checkpoint_manifest_path(self, name),
                    {
                        "run_id": str(self.run_id),
                        "name": name,
                        "lane_index": lane_index,
                        "input_fingerprint": input_fingerprint,
                        "baseline": before_command,
                        "checkpoint": checkpoint,
                        "changed_paths": checkpoint_paths,
                        "ignored_state": _ignored_state_payload(preserved_ignored_state),
                    },
                )
        except Exception as exc:
            try:
                _rollback_lane(
                    self,
                    name=name,
                    baseline=before_command,
                    preserved_ignored_state=preserved_ignored_state,
                )
            except SafetyError as rollback_exc:
                raise SafetyError(
                    f"Command-owned {name} repair lane command or post-command processing failed "
                    f"({exc}) and rollback could not be verified. Workspace state is uncertain."
                ) from rollback_exc
            raise SafetyError(
                f"Command-owned {name} repair lane command or post-command processing failed; "
                f"rollback was verified: {exc}"
            ) from exc

        if not record.get("ok"):
            try:
                _rollback_lane(
                    self,
                    name=name,
                    baseline=before_command,
                    preserved_ignored_state=preserved_ignored_state,
                )
                record["rollback_verified"] = True
                record["changed_paths_after_rollback"] = []
            except SafetyError as exc:
                record["rollback_verified"] = False
                record["rollback_error"] = str(exc)
                raise SafetyError(
                    f"Command-owned {name} repair lane failed and rollback could not be verified. "
                    "Workspace state is uncertain."
                ) from exc
            failed.append(name)
        records.append(record)

    changed_total = sorted(
        {
            path
            for record in records
            if record.get("ok")
            for path in list(record.get("changed_paths", []) or [])
        }
    )
    payload = {
        "resume": {
            "run_id": str(self.run_id),
            "commands": _command_config(commands),
            "allowed_paths": allowed_paths,
            "input_fingerprint": input_fingerprint,
            "initial_baseline": str(records[0].get("baseline") or ""),
            "final_checkpoint": self.mirror.head(),
            "ignored_state": _ignored_state_payload(approved_ignored_state or {}),
        },
        "summary": {
            "enabled": [name for name, _ in commands],
            "passed": [str(item.get("name") or "unknown") for item in records if item.get("ok")],
            "failed": failed,
            "changed_paths": changed_total,
            "command_owned_repair_lanes": True,
            "ai_freehand_repair_allowed": False,
            "continuation_safe": rollback_verified,
        },
        "records": records,
        "note": (
            "AUTOREVIEW and Clawpatch findings are not fed to the AI repairer. "
            "Each configured lane is run from a clean controller checkpoint. A failed, timed-out, "
            "out-of-scope, or commit-producing lane is rolled back and verified before continuation. "
            "Successful continuation restores and verifies the exact run-scoped checkpoint."
        ),
    }
    self.artifacts.write_json("review/external-review-repair.json", payload)
    if failed:
        if not rollback_verified:
            raise SafetyError(
                "Configured external review/repair lane failed and rollback could not be verified. "
                "Manageroo refuses to continue from an uncertain workspace."
            )
        raise ValidationError(
            "Configured external review/repair lane failed and was rolled back: "
            + ", ".join(failed)
            + ". See review/external-review-repair.json."
        )
    return payload
