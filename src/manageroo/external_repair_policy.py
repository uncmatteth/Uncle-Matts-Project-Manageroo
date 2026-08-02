from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import SafetyError, ValidationError
from .internal_clawpatch import run_internal_clawpatch
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


def _restore_checkpoint(orchestrator: Any, *, name: str, checkpoint: str) -> None:
    assert orchestrator.workspace is not None
    reset = orchestrator.runner.run(
        ["git", "reset", "--hard", checkpoint],
        cwd=orchestrator.workspace,
        timeout_seconds=120,
    )
    clean = orchestrator.runner.run(
        ["git", "clean", "-fdx"],
        cwd=orchestrator.workspace,
        timeout_seconds=120,
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
    if (
        not reset.passed
        or not clean.passed
        or not head.passed
        or head.stdout.strip() != checkpoint
        or not status.passed
        or status.stdout.strip()
    ):
        raise SafetyError(f"Command-owned {name} checkpoint could not be restored exactly.")


def _existing_checkpoint(
    orchestrator: Any,
    name: str,
    *,
    baseline: str,
) -> tuple[str, list[str]] | None:
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
    if recorded_paths and recorded_paths != changed_paths:
        raise SafetyError(f"Command-owned {name} checkpoint manifest does not match its Git diff.")
    return checkpoint, changed_paths


def _require_clean_lane_start(orchestrator: Any, name: str) -> None:
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


def _rollback_lane(orchestrator: Any, *, name: str, baseline: str) -> None:
    """Restore the exact clean pre-command checkpoint and verify rollback before continuation."""

    assert orchestrator.workspace is not None
    reset = orchestrator.runner.run(
        ["git", "reset", "--hard", baseline],
        cwd=orchestrator.workspace,
        timeout_seconds=120,
    )
    clean = orchestrator.runner.run(
        ["git", "clean", "-fdx"],
        cwd=orchestrator.workspace,
        timeout_seconds=120,
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
    if (
        not reset.passed
        or not clean.passed
        or not head.passed
        or head.stdout.strip() != baseline
        or not status.passed
        or status.stdout.strip()
    ):
        raise SafetyError(
            f"Command-owned {name} repair lane failed and rollback could not be verified."
        )


def _validate_persisted_report(existing: Any) -> dict:
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
    return existing


def _uses_internal_clawpatch(name: str, argv_template: list[str]) -> bool:
    if name != "clawpatch" or len(argv_template) != 1:
        return False
    executable = Path(argv_template[0]).name.lower()
    return executable in {"clawpatch", "clawpatch.exe", "clawpatch.cmd", "clawpatch.bat"}


def _preserve_and_rollback_clawpatch_attempt(
    orchestrator: Any,
    *,
    finding_id: str,
    reason: str,
    baseline: str,
) -> dict:
    assert orchestrator.workspace is not None
    paths = orchestrator.mirror.changed_paths(baseline)
    preservation = {"created": False, "ref": "", "sha": "", "paths": paths, "reason": reason}
    current_head = orchestrator.mirror.head()
    if paths and current_head != baseline:
        preservation.update(
            {
                "created": True,
                "ref": current_head,
                "sha": current_head,
                "kind": "controller-checkpoint",
            }
        )
    elif paths:
        stash = orchestrator.runner.run(
            [
                "git",
                "stash",
                "push",
                "--include-untracked",
                "--message",
                f"manageroo internal clawpatch unresolved {finding_id}",
                "--",
                *paths,
            ],
            cwd=orchestrator.workspace,
            timeout_seconds=300,
        )
        if not stash.passed:
            raise SafetyError(f"Could not preserve unresolved Clawpatch attempt {finding_id}.")
        identity = orchestrator.runner.run(
            ["git", "stash", "list", "-1", "--format=%gd|%H"],
            cwd=orchestrator.workspace,
            timeout_seconds=60,
        )
        ref, separator, sha = identity.stdout.strip().partition("|")
        if not identity.passed or not separator or not ref or not sha:
            raise SafetyError(f"Could not verify preserved Clawpatch attempt {finding_id}.")
        preservation.update({"created": True, "ref": ref, "sha": sha, "kind": "git-stash"})
    _restore_checkpoint(orchestrator, name="clawpatch", checkpoint=baseline)
    return preservation


def _run_internal_clawpatch_record(
    orchestrator: Any,
    *,
    executable: str,
    allowed_paths: list[str],
    baseline: str,
) -> dict:
    assert orchestrator.workspace is not None
    state_dir = orchestrator.artifacts.root / "review" / "external-state" / "clawpatch"
    try:
        lifecycle = run_internal_clawpatch(
            runner=orchestrator.runner,
            workspace=orchestrator.workspace,
            executable=executable,
            state_dir=state_dir,
            since_ref=orchestrator.mirror.baseline_commit,
            allowed_paths=allowed_paths,
            head=orchestrator.mirror.head,
            changed_paths=orchestrator.mirror.changed_paths,
            checkpoint=orchestrator.mirror.checkpoint,
            run_gates=lambda: orchestrator._run_gates(
                list(orchestrator._gate_catalog().values()), orchestrator.workspace
            ),
            preserve_and_rollback=lambda **kwargs: _preserve_and_rollback_clawpatch_attempt(
                orchestrator, **kwargs
            ),
        )
    except Exception as exc:
        return {
            "name": "clawpatch",
            "enabled": True,
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "sequential_clawpatch_lifecycle": True,
            "clawpatch_owns_repairs": True,
            "baseline": baseline,
        }
    changed = orchestrator.mirror.changed_paths(baseline)
    record = {
        "name": "clawpatch",
        "enabled": True,
        "ok": bool(lifecycle.get("ok")),
        "command_owned_repair_lane": True,
        "ai_freehand_repair_allowed": False,
        "baseline": baseline,
        "checkpoint": orchestrator.mirror.head(),
        "changed_paths": changed,
        **lifecycle,
    }
    atomic_write_json(
        _checkpoint_manifest_path(orchestrator, "clawpatch"),
        {
            "run_id": str(orchestrator.run_id),
            "name": "clawpatch",
            "baseline": baseline,
            "checkpoint": orchestrator.mirror.head(),
            "changed_paths": changed,
        },
    )
    return record


def run_external_review_repair_lanes(
    self: Any,
    *,
    brief: str,
    plan: dict,
    gate_results: list[dict],
) -> dict | None:
    """Run or safely resume command-owned repair lanes with verified rollback boundaries."""

    assert self.workspace is not None
    existing = self._artifact_json("review/external-review-repair.json")
    if existing is not None:
        return _validate_persisted_report(existing)

    commands = [
        (name, argv_template)
        for name, argv_template in self._external_review_repair_commands()
        if argv_template
    ]
    if not commands:
        return None

    allowed_paths = sorted(
        {
            safe_repo_relative(path)
            for task in plan.get("tasks", [])
            for path in task.get("allowed_paths", [])
        }
    )
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
    for name, argv_template in commands:
        baseline = self.mirror.head()
        resumed = _existing_checkpoint(self, name, baseline=baseline)
        if resumed is not None:
            checkpoint, changed_paths = resumed
            ScopePolicy(tuple(allowed_paths)).validate_paths(changed_paths)
            _restore_checkpoint(self, name=name, checkpoint=checkpoint)
            records.append(
                {
                    "name": name,
                    "enabled": True,
                    "ok": True,
                    "resumed_from_checkpoint": True,
                    "checkpoint": checkpoint,
                    "baseline": baseline,
                    "command_owned_repair_lane": True,
                    "ai_freehand_repair_allowed": False,
                    "changed_paths": changed_paths,
                }
            )
            continue

        _require_clean_lane_start(self, name)
        before_command = baseline
        if _uses_internal_clawpatch(name, argv_template):
            record = _run_internal_clawpatch_record(
                self,
                executable=argv_template[0].format(**values),
                allowed_paths=allowed_paths,
                baseline=before_command,
            )
            if not record.get("ok"):
                try:
                    _rollback_lane(self, name=name, baseline=before_command)
                    record["rollback_verified"] = True
                    record["changed_paths_after_rollback"] = []
                except SafetyError as exc:
                    rollback_verified = False
                    record["rollback_verified"] = False
                    record["rollback_error"] = str(exc)
                failed.append(name)
            records.append(record)
            continue
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
        try:
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

            if record.get("ok") and changed_paths:
                checkpoint = self.mirror.checkpoint(
                    _checkpoint_message(name, str(self.run_id), before_command)
                )
                record["checkpoint"] = checkpoint
                atomic_write_json(
                    _checkpoint_manifest_path(self, name),
                    {
                        "run_id": str(self.run_id),
                        "name": name,
                        "baseline": before_command,
                        "checkpoint": checkpoint,
                        "changed_paths": _actual_checkpoint_paths(
                            self, before_command, checkpoint
                        ),
                    },
                )
        except Exception as exc:
            try:
                _rollback_lane(self, name=name, baseline=before_command)
            except SafetyError as rollback_exc:
                raise SafetyError(
                    f"Command-owned {name} repair lane post-command processing failed "
                    f"({exc}) and rollback could not be verified. Workspace state is uncertain."
                ) from rollback_exc
            raise SafetyError(
                f"Command-owned {name} repair lane post-command processing failed; "
                f"rollback was verified: {exc}"
            ) from exc

        if not record.get("ok"):
            try:
                _rollback_lane(self, name=name, baseline=before_command)
                record["rollback_verified"] = True
                record["changed_paths_after_rollback"] = []
            except SafetyError as exc:
                rollback_verified = False
                record["rollback_verified"] = False
                record["rollback_error"] = str(exc)
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
            "Each configured lane is run from a clean controller checkpoint. The exact "
            "clawpatch executable activates a durable one-finding supervisor: timed-out and "
            "validation-failing attempts are reconciled and retried by Clawpatch instead of "
            "becoming AI repair prompts. A hard lane failure is rolled back and verified. "
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
