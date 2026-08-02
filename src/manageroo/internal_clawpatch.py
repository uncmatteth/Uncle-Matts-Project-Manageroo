from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from .errors import SafetyError
from .policy import ScopePolicy
from .runner import CommandResult, CommandRunner
from .util import atomic_write_json, read_json, safe_repo_relative


CLAWPATCH_COMMAND_TIMEOUT_SECONDS = 900
CLAWPATCH_CODEX_TIMEOUT_MS = 900_000
_FINDING_ID = re.compile(r"^fnd_[A-Za-z0-9_.-]+$")


def _json_result(result: CommandResult, command: Sequence[str]) -> dict[str, Any]:
    if not result.passed:
        raise SafetyError(
            f"Clawpatch command failed ({' '.join(command)}): exit={result.exit_code}, "
            f"timed_out={result.timed_out}, stderr={result.stderr[-2000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SafetyError(
            f"Clawpatch command did not return valid JSON ({' '.join(command)})."
        ) from exc
    if not isinstance(payload, dict):
        raise SafetyError(f"Clawpatch command returned a non-object ({' '.join(command)}).")
    return payload


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SafetyError(f"Clawpatch returned a missing or malformed {field!r} value.")
    return value


def _finding(payload: dict[str, Any]) -> str | None:
    value = payload.get("finding")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SafetyError("Clawpatch next returned a malformed finding.")
    finding_id = value.get("id")
    if not isinstance(finding_id, str) or not _FINDING_ID.fullmatch(finding_id):
        raise SafetyError("Clawpatch next returned an invalid finding ID.")
    if value.get("status") != "open":
        raise SafetyError(f"Clawpatch next returned non-open finding {finding_id}.")
    if payload.get("next") != f"clawpatch show --finding {finding_id}":
        raise SafetyError(f"Clawpatch next returned the wrong next command for {finding_id}.")
    return finding_id


def _show(payload: dict[str, Any], finding_id: str, status: str) -> None:
    finding = payload.get("finding")
    if not isinstance(finding, dict) or finding.get("id") != finding_id:
        raise SafetyError(f"Clawpatch show returned the wrong finding for {finding_id}.")
    if finding.get("status") != status:
        raise SafetyError(
            f"Clawpatch show returned status {finding.get('status')!r} for {finding_id}; "
            f"expected {status!r}."
        )
    if not isinstance(payload.get("validation"), list):
        raise SafetyError(f"Clawpatch show returned malformed validation for {finding_id}.")
    if not isinstance(payload.get("patchAttempts"), list):
        raise SafetyError(f"Clawpatch show returned malformed patch attempts for {finding_id}.")


def _attempt_files(payload: dict[str, Any], finding_id: str, patch_id: str) -> list[str]:
    attempts = payload.get("patchAttempts")
    attempt = next(
        (
            item
            for item in attempts
            if isinstance(item, dict) and item.get("patchAttemptId") == patch_id
        ),
        None,
    )
    if not isinstance(attempt, dict):
        raise SafetyError(f"Clawpatch show omitted patch attempt {patch_id} for {finding_id}.")
    if finding_id not in list(attempt.get("findingIds") or []):
        raise SafetyError(f"Clawpatch patch attempt {patch_id} does not belong to {finding_id}.")
    files = attempt.get("filesChanged")
    if not isinstance(files, list) or any(not isinstance(item, str) or not item for item in files):
        raise SafetyError(f"Clawpatch patch attempt {patch_id} has malformed filesChanged.")
    return sorted({safe_repo_relative(item) for item in files})


def run_internal_clawpatch(
    *,
    runner: CommandRunner,
    workspace: Path,
    executable: str,
    state_dir: Path,
    since_ref: str,
    allowed_paths: list[str],
    head: Callable[[], str],
    changed_paths: Callable[[str], list[str]],
    checkpoint: Callable[[str], str],
    run_gates: Callable[[], list[dict]],
    preserve_and_rollback: Callable[..., dict],
    retry_wait: Callable[[float], None] = time.sleep,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    """Run Clawpatch's exact one-finding lifecycle inside a Manageroo mirror."""

    env = {
        "CLAWPATCH_STATE_DIR": str(state_dir),
        "CLAWPATCH_CODEX_TIMEOUT_MS": os.environ.get(
            "CLAWPATCH_CODEX_TIMEOUT_MS", str(CLAWPATCH_CODEX_TIMEOUT_MS)
        ),
    }
    durable_progress = progress_path or state_dir.parent / "clawpatch-progress.json"
    try:
        previous_progress = read_json(durable_progress) if durable_progress.is_file() else {}
    except Exception as exc:
        raise SafetyError(f"Manageroo Clawpatch progress is unreadable: {exc}") from exc
    commands: list[dict[str, Any]] = list(previous_progress.get("commands", []) or [])
    retries: list[dict[str, Any]] = list(previous_progress.get("retries", []) or [])
    if not since_ref.strip():
        raise SafetyError("Manageroo Clawpatch review requires a non-empty source baseline ref.")
    recorded_since = str(previous_progress.get("since_ref") or "")
    if recorded_since and recorded_since != since_ref:
        raise SafetyError("Manageroo Clawpatch progress belongs to a different source baseline.")
    progress: dict[str, Any] = {
        "phase": "starting",
        "since_ref": since_ref,
        "active": previous_progress.get("active"),
        "commands": commands,
        "retries": retries,
    }

    def save_progress() -> None:
        atomic_write_json(durable_progress, progress)

    def execute(*args: str) -> CommandResult:
        argv = [executable, *args, "--json"]
        command_env = dict(env)
        command_env["CLAWPATCH_CODEX_SANDBOX"] = (
            "workspace-write" if args and args[0] == "fix" else "read-only"
        )
        result = runner.run(
            argv,
            cwd=workspace,
            timeout_seconds=CLAWPATCH_COMMAND_TIMEOUT_SECONDS,
            env=command_env,
            kill_process_group=True,
        )
        commands.append(
            {
                "argv": result.argv,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            }
        )
        progress["last_command"] = commands[-1]
        save_progress()
        return result

    def invoke(*args: str) -> dict[str, Any]:
        argv = [executable, *args, "--json"]
        attempt = 0
        while True:
            attempt += 1
            result = execute(*args)
            if result.passed:
                return _json_result(result, argv)
            provider_command = bool(args) and args[0] in {"map", "review", "revalidate"}
            retryable = result.timed_out or (
                provider_command and result.exit_code in {1, 5, 124}
            )
            if not retryable:
                return _json_result(result, argv)
            retries.append(
                {
                    "finding_id": "N/A",
                    "reason": "timeout" if result.timed_out else f"exit-{result.exit_code}",
                    "attempt": attempt,
                    "command": list(args),
                    "preservation": {},
                }
            )
            progress["retries"] = retries
            save_progress()
            retry_wait(min(60.0, float(5 * (2 ** min(attempt - 1, 4)))))

    if not (state_dir / "config.json").is_file():
        invoke("init")

    status_before = invoke("status")
    if _required_int(status_before, "activeLocks") or _required_int(status_before, "lockFiles"):
        invoke("clean-locks")
        cleaned = invoke("status")
        if _required_int(cleaned, "activeLocks") or _required_int(cleaned, "lockFiles"):
            raise SafetyError("Clawpatch locks remained after run-owned stale-lock cleanup.")

    mapped = invoke("map")
    feature_count = _required_int(mapped, "features")
    if feature_count < 0:
        raise SafetyError("Clawpatch map returned a negative feature count.")
    review_limit = max(feature_count, 1)
    reviewed = invoke("review", "--limit", str(review_limit), "--since", since_ref)
    reviewed_count = _required_int(reviewed, "reviewed")
    if reviewed_count < 0 or reviewed_count > feature_count:
        raise SafetyError("Clawpatch review returned an impossible reviewed count.")
    completion = invoke(
        "review", "--limit", str(review_limit), "--since", since_ref, "--dry-run"
    )
    if completion.get("dryRun") is not True or _required_int(completion, "wouldReview") != 0:
        raise SafetyError("Clawpatch review did not finish every mapped feature.")

    fixed: list[dict[str, Any]] = list(previous_progress.get("fixed", []) or [])
    progress["fixed"] = fixed

    def shown_status(payload: dict[str, Any], finding_id: str) -> str:
        finding = payload.get("finding")
        if not isinstance(finding, dict) or finding.get("id") != finding_id:
            raise SafetyError(f"Clawpatch show returned the wrong finding for {finding_id}.")
        status = finding.get("status")
        if status not in {"open", "uncertain", "fixed", "false-positive"}:
            raise SafetyError(f"Clawpatch show returned an invalid status for {finding_id}.")
        return str(status)

    def reopen(finding_id: str, status: str, note: str) -> None:
        if status == "open":
            return
        triage = invoke(
            "triage",
            "--finding",
            finding_id,
            "--status",
            "open",
            "--note",
            note,
        )
        if triage.get("finding") != finding_id or triage.get("status") != "open":
            raise SafetyError(f"Clawpatch did not reopen {finding_id} for its next repair attempt.")

    def record_retry(finding_id: str, reason: str, attempt: int, preservation: dict) -> None:
        retries.append(
            {
                "finding_id": finding_id,
                "reason": reason,
                "attempt": attempt,
                "preservation": preservation,
            }
        )
        progress["retries"] = retries
        save_progress()

    def require_same_next(finding_id: str) -> dict[str, Any]:
        queue = invoke("next")
        if _finding(queue) != finding_id:
            raise SafetyError(
                f"Clawpatch did not return {finding_id} as the next finding after reopening it."
            )
        inspection = invoke("show", "--finding", finding_id)
        _show(inspection, finding_id, "open")
        return inspection

    active = progress.get("active")
    if isinstance(active, dict) and active.get("finding_id") and active.get("baseline"):
        finding_id = str(active["finding_id"])
        baseline = str(active["baseline"])
        inspected = invoke("show", "--finding", finding_id)
        status = shown_status(inspected, finding_id)
        if active.get("phase") == "checkpointed" and status in {"uncertain", "fixed"}:
            revalidated = (
                {"finding": finding_id, "outcome": "fixed", "already_revalidated": True}
                if status == "fixed"
                else invoke("revalidate", "--finding", finding_id)
            )
            if revalidated.get("finding") == finding_id and revalidated.get("outcome") == "fixed":
                recovered = dict(active.get("record", {}) or {})
                recovered["revalidation"] = revalidated
                recovered["resumed_after_controller_restart"] = True
                fixed.append(recovered)
                progress["active"] = None
                save_progress()
            else:
                preservation = preserve_and_rollback(
                    finding_id=finding_id,
                    reason="checkpointed attempt did not revalidate after controller restart",
                    baseline=baseline,
                )
                reopen(
                    finding_id,
                    shown_status(invoke("show", "--finding", finding_id), finding_id),
                    "Retrying a checkpointed Clawpatch attempt after controller restart.",
                )
                record_retry(finding_id, "restart-revalidation", 0, preservation)
                progress["active"] = None
                save_progress()
        else:
            preservation = preserve_and_rollback(
                finding_id=finding_id,
                reason="interrupted Clawpatch attempt recovered after controller restart",
                baseline=baseline,
            )
            reopen(
                finding_id,
                status,
                "Retrying an interrupted Clawpatch attempt after controller restart.",
            )
            record_retry(finding_id, "controller-restart", 0, preservation)
            progress["active"] = None
            save_progress()

    while True:
        queue = invoke("next")
        finding_id = _finding(queue)
        if finding_id is None:
            break
        inspection = invoke("show", "--finding", finding_id)
        _show(inspection, finding_id, "open")
        baseline = head()
        attempt = 0
        while True:
            attempt += 1
            progress["phase"] = "repairing"
            progress["active"] = {
                "phase": "fixing",
                "finding_id": finding_id,
                "baseline": baseline,
                "attempt": attempt,
            }
            save_progress()
            fix_result = execute("fix", "--finding", finding_id)
            if not fix_result.passed:
                retryable = fix_result.timed_out or fix_result.exit_code in {1, 5, 6, 124}
                if not retryable:
                    _json_result(
                        fix_result,
                        [executable, "fix", "--finding", finding_id, "--json"],
                    )
                reason = "timeout" if fix_result.timed_out else f"exit-{fix_result.exit_code}"
                inspected = invoke("show", "--finding", finding_id)
                status = shown_status(inspected, finding_id)
                preservation = preserve_and_rollback(
                    finding_id=finding_id,
                    reason=f"Clawpatch fix {reason}; retrying the same finding",
                    baseline=baseline,
                )
                reopen(
                    finding_id,
                    status,
                    f"Retrying the same Clawpatch finding after {reason}.",
                )
                record_retry(finding_id, reason, attempt, preservation)
                inspection = require_same_next(finding_id)
                retry_wait(min(60.0, float(5 * (2 ** min(attempt - 1, 4)))))
                continue

            applied = _json_result(
                fix_result,
                [executable, "fix", "--finding", finding_id, "--json"],
            )
            if applied.get("finding") != finding_id or applied.get("status") != "applied":
                raise SafetyError(f"Clawpatch fix did not apply finding {finding_id}.")
            patch_id = applied.get("patchAttempt")
            if not isinstance(patch_id, str) or not patch_id:
                raise SafetyError(f"Clawpatch fix returned no patch attempt for {finding_id}.")
            post_fix = invoke("show", "--finding", finding_id)
            _show(post_fix, finding_id, "uncertain")
            files = _attempt_files(post_fix, finding_id, patch_id)
            actual = sorted({safe_repo_relative(item) for item in changed_paths(baseline)})
            retry_reason = ""
            if actual != files:
                retry_reason = (
                    f"patch-path-mismatch attempt={files}, actual={actual}"
                )
            try:
                if not retry_reason:
                    ScopePolicy(tuple(allowed_paths)).validate_paths(actual)
            except SafetyError as exc:
                retry_reason = f"scope-validation: {exc}"
            gates: list[dict] = []
            try:
                if not retry_reason:
                    gates = run_gates()
            except Exception as exc:
                retry_reason = f"manageroo-gates: {exc}"
            if retry_reason:
                preservation = preserve_and_rollback(
                    finding_id=finding_id,
                    reason=retry_reason,
                    baseline=baseline,
                )
                reopen(
                    finding_id,
                    shown_status(invoke("show", "--finding", finding_id), finding_id),
                    "Retrying the same Clawpatch finding after deterministic validation failed.",
                )
                record_retry(finding_id, retry_reason, attempt, preservation)
                inspection = require_same_next(finding_id)
                retry_wait(min(60.0, float(5 * (2 ** min(attempt - 1, 4)))))
                continue

            checkpoint_sha = checkpoint(
                f"MANAGEROO Clawpatch checkpoint {finding_id} baseline={baseline}"
            )
            record = {
                "finding_id": finding_id,
                "patch_attempt": patch_id,
                "files_changed": files,
                "gates": gates,
                "checkpoint": checkpoint_sha,
            }
            progress["active"] = {
                "phase": "checkpointed",
                "finding_id": finding_id,
                "baseline": baseline,
                "checkpoint": checkpoint_sha,
                "record": record,
            }
            save_progress()
            revalidated = invoke("revalidate", "--finding", finding_id)
            if revalidated.get("finding") == finding_id and revalidated.get("outcome") == "fixed":
                record["revalidation"] = revalidated
                fixed.append(record)
                progress["fixed"] = fixed
                progress["active"] = None
                save_progress()
                break
            retry_reason = (
                f"revalidation-{revalidated.get('outcome', 'malformed')}"
            )
            preservation = preserve_and_rollback(
                finding_id=finding_id,
                reason=retry_reason,
                baseline=baseline,
            )
            reopen(
                finding_id,
                shown_status(invoke("show", "--finding", finding_id), finding_id),
                "Retrying the same Clawpatch finding after revalidation did not prove fixed.",
            )
            record_retry(finding_id, retry_reason, attempt, preservation)
            progress["active"] = None
            save_progress()
            inspection = require_same_next(finding_id)
            retry_wait(min(60.0, float(5 * (2 ** min(attempt - 1, 4)))))

    all_revalidation = invoke("revalidate", "--all", "--status", "open")
    open_report = invoke("report", "--status", "open")
    if open_report.get("total") != 0 or open_report.get("items") != []:
        raise SafetyError("Clawpatch queue ended with open findings.")
    uncertain_report = invoke("report", "--status", "uncertain")
    if uncertain_report.get("total") != 0 or uncertain_report.get("items") != []:
        raise SafetyError("Clawpatch reported unexplained uncertain findings.")
    status_after = invoke("status")
    for field in ("openFindings", "activeLocks", "lockFiles"):
        if _required_int(status_after, field) != 0:
            raise SafetyError(f"Clawpatch final status requires {field}=0.")
    final_gates = run_gates()
    progress["phase"] = "complete"
    progress["active"] = None
    progress["fixed"] = fixed
    save_progress()
    return {
        "ok": True,
        "sequential_clawpatch_lifecycle": True,
        "clawpatch_owns_repairs": True,
        "fixed": fixed,
        "unresolved": [],
        "retries": retries,
        "map": mapped,
        "review": {"run": reviewed, "completion": completion},
        "all_revalidation": all_revalidation,
        "open_report": open_report,
        "uncertain_report": uncertain_report,
        "status": status_after,
        "final_gates": final_gates,
        "commands": commands,
    }
