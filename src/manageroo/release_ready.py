from __future__ import annotations

from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .errors import MANAGEROOError
from .gates import GateRunner, gates_from_config
from .policy import CommandPolicy
from .project import git_root
from .project_memory import ensure_project_memory
from .readiness import readiness
from .runner import CommandRunner
from .state import Phase, RunState
from .util import atomic_write_json, atomic_write_text, read_json, sha256_file, utc_now
from .workspace import WorkspaceMirror


def _item(name: str, ok: bool, detail: str, next_command: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
        "next": next_command,
        "required": True,
    }


def _metadata_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / "release-readiness.json"


def _handoff_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / "cache" / "production-handoff.md"


def _load_metadata(repo: Path) -> dict[str, Any]:
    path = _metadata_path(repo)
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _release_metadata_command() -> str:
    return (
        f'{PUBLIC_COMMAND} release-ready --target "Production URL or deploy command" '
        '--rollback "Rollback command or steps" --approved-by "Your name"'
    )


def _git_status(repo: Path) -> tuple[bool, str]:
    result = CommandRunner().run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        timeout_seconds=60,
    )
    if not result.passed:
        return False, result.stderr or "git status failed"
    text = result.stdout.strip()
    return text == "", text


def _git_output(repo: Path, argv: list[str]) -> str:
    result = CommandRunner().run(argv, cwd=repo, timeout_seconds=60)
    if not result.passed:
        return ""
    return result.stdout.strip()


def _git_head_summary(repo: Path) -> dict[str, Any]:
    files_text = _git_output(repo, ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"])
    return {
        "branch": _git_output(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": _git_output(repo, ["git", "rev-parse", "--short=12", "HEAD"]),
        "subject": _git_output(repo, ["git", "log", "-1", "--pretty=%s"]),
        "files": [line for line in files_text.splitlines() if line.strip()],
    }


def _resolve_run_path(
    *,
    run_root: Path,
    value: Any,
    default: Path,
    label: str,
    failures: list[str],
) -> Path:
    candidate = Path(str(value)) if value else default
    if not candidate.is_absolute():
        candidate = run_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(run_root.resolve())
        return resolved
    except Exception:
        failures.append(f"{label} path is outside the run root: {candidate}")
        return candidate


def _validate_state_proof(
    *,
    run_root: Path,
    run_id: str,
    evidence_paths: dict[str, Any],
    failures: list[str],
) -> Path:
    state_path = _resolve_run_path(
        run_root=run_root,
        value=evidence_paths.get("state"),
        default=run_root / "state.json",
        label="state",
        failures=failures,
    )
    if not state_path.is_file():
        failures.append("state file is missing")
        return state_path
    try:
        state = RunState.load(state_path)
    except Exception as exc:
        failures.append(f"state file is unreadable: {exc}")
        return state_path
    if state.run_id != run_id:
        failures.append(f"state run_id is {state.run_id}, expected {run_id}")
    if state.phase != Phase.COMPLETE.value:
        failures.append(f"state phase is {state.phase}, expected COMPLETE")
    if not state.history:
        failures.append("state history is empty")
    return state_path


def _validate_artifact_ledger(
    *,
    run_root: Path,
    evidence_paths: dict[str, Any],
    external_capture_path: Path,
    failures: list[str],
) -> Path:
    ledger_path = _resolve_run_path(
        run_root=run_root,
        value=evidence_paths.get("artifact_ledger"),
        default=run_root / "artifacts" / "artifact-ledger.json",
        label="artifact ledger",
        failures=failures,
    )
    if not ledger_path.is_file():
        failures.append("artifact ledger is missing")
        return ledger_path
    try:
        ledger = read_json(ledger_path)
    except Exception as exc:
        failures.append(f"artifact ledger is unreadable: {exc}")
        return ledger_path
    artifacts = ledger.get("artifacts") if isinstance(ledger, dict) else None
    if not isinstance(artifacts, dict):
        failures.append("artifact ledger has no artifacts map")
        return ledger_path

    capture_relative = "delivery/external-capture.json"
    capture_record = artifacts.get(capture_relative)
    if not isinstance(capture_record, dict):
        failures.append("external capture artifact is not recorded in artifact ledger")
    else:
        recorded_sha = str(capture_record.get("sha256") or "")
        if not recorded_sha:
            failures.append("external capture artifact ledger record has no sha256")
        elif external_capture_path.is_file() and sha256_file(external_capture_path) != recorded_sha:
            failures.append("external capture artifact does not match artifact ledger sha256")

    artifact_root = run_root / "artifacts"
    for relative, record in artifacts.items():
        if not isinstance(record, dict):
            failures.append(f"artifact ledger record is invalid: {relative}")
            continue
        artifact_path = artifact_root / str(relative)
        if not artifact_path.is_file():
            failures.append(f"artifact ledger points to missing artifact: {relative}")
            continue
        recorded_sha = str(record.get("sha256") or "")
        if not recorded_sha:
            failures.append(f"artifact ledger record has no sha256: {relative}")
        elif sha256_file(artifact_path) != recorded_sha:
            failures.append(f"artifact ledger sha256 mismatch: {relative}")
    return ledger_path


def _validate_job_records(*, run_root: Path, failures: list[str]) -> None:
    jobs_root = run_root / "jobs"
    job_paths = sorted(jobs_root.glob("*.json")) if jobs_root.is_dir() else []
    if not job_paths:
        failures.append("no completed worker job records")
        return
    artifact_root = run_root / "artifacts"
    for job_path in job_paths:
        try:
            job = read_json(job_path)
        except Exception as exc:
            failures.append(f"worker job record is unreadable: {job_path.name}: {exc}")
            continue
        job_id = str(job.get("id") or job_path.stem)
        if job.get("status") != "complete":
            failures.append(f"worker job {job_id} is {job.get('status', 'missing')}, expected complete")
        output_artifact = str(job.get("output_artifact") or "")
        output_sha = str(job.get("output_artifact_sha256") or "")
        if not output_artifact:
            failures.append(f"worker job {job_id} has no output artifact")
        elif not output_sha:
            failures.append(f"worker job {job_id} has no output artifact sha256")
        else:
            artifact_path = artifact_root / output_artifact
            if not artifact_path.is_file():
                failures.append(f"worker job {job_id} output artifact is missing")
            elif sha256_file(artifact_path) != output_sha:
                failures.append(f"worker job {job_id} output artifact sha256 mismatch")
        if not job.get("result_sha256"):
            failures.append(f"worker job {job_id} has no result sha256")
        attempt_root = run_root / "worker-attempts" / job_id
        attempts = sorted(attempt_root.glob("*.json")) if attempt_root.is_dir() else []
        completed_attempt = False
        for attempt_path in attempts:
            try:
                attempt = read_json(attempt_path)
            except Exception as exc:
                failures.append(f"worker attempt record is unreadable: {job_id}/{attempt_path.name}: {exc}")
                continue
            if attempt.get("status") == "complete" and attempt.get("result_sha256"):
                completed_attempt = True
        if not completed_attempt:
            failures.append(f"worker job {job_id} has no completed attempt record")


def _validate_applied_source(
    *,
    repo: Path,
    run_root: Path,
    patch_path: Path,
    failures: list[str],
) -> None:
    try:
        mirror = WorkspaceMirror(repo, run_root, CommandRunner())
        mirror.load_existing()
        mirror.assert_source_matches_snapshot_plus_patch(patch_path)
    except Exception as exc:
        failures.append(f"source tree no longer matches approved delivery patch: {exc}")


def _latest_manageroo_run_proof(repo: Path) -> dict[str, Any]:
    results = sorted(
        (repo / PROJECT_DIR / "runs").glob("*/delivery/final-result.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not results:
        return {
            "ok": False,
            "detail": "no completed Manageroo run proof found",
            "next": f"{PUBLIC_COMMAND} run --apply",
        }
    result_path = results[0]
    run_root = result_path.parents[1]
    run_id = run_root.name
    try:
        data = read_json(result_path)
    except Exception as exc:
        return {
            "ok": False,
            "run_id": run_id,
            "detail": f"latest run final-result.json is unreadable: {exc}",
            "next": f"{PUBLIC_COMMAND} run --continue {run_id} --apply",
        }
    delivery = run_root / "delivery"
    report_path = delivery / "FINAL-REPORT.md"
    evidence_paths = data.get("evidence_paths", {})
    if not isinstance(evidence_paths, dict):
        evidence_paths = {}
    failures: list[str] = []
    run_root_value = evidence_paths.get("run_root")
    if run_root_value and Path(str(run_root_value)).resolve() != run_root.resolve():
        failures.append(f"run_root evidence points at {run_root_value}, expected {run_root}")
    patch_path = _resolve_run_path(
        run_root=run_root,
        value=evidence_paths.get("patch"),
        default=delivery / "final.patch",
        label="final patch",
        failures=failures,
    )
    report_path = _resolve_run_path(
        run_root=run_root,
        value=evidence_paths.get("final_report"),
        default=report_path,
        label="final report",
        failures=failures,
    )
    _validate_state_proof(
        run_root=run_root,
        run_id=run_id,
        evidence_paths=evidence_paths,
        failures=failures,
    )
    review_status = data.get("review", {}).get("status")
    applied = bool(data.get("applied_to_source"))
    external_capture_passed = bool(
        data.get("external_capture", {}).get("summary", {}).get("passed")
    )
    external_capture_path = run_root / "artifacts" / "delivery" / "external-capture.json"
    ledger_path = _validate_artifact_ledger(
        run_root=run_root,
        evidence_paths=evidence_paths,
        external_capture_path=external_capture_path,
        failures=failures,
    )
    _validate_job_records(run_root=run_root, failures=failures)
    external_capture_artifact_passed = False
    external_capture_artifact_error = ""
    if external_capture_path.is_file():
        try:
            external_capture_artifact = read_json(external_capture_path)
            external_capture_artifact_passed = bool(
                external_capture_artifact.get("summary", {}).get("passed")
            )
        except Exception as exc:
            external_capture_artifact_error = str(exc)
    if data.get("run_id") and data.get("run_id") != run_id:
        failures.append(f"final-result run_id is {data.get('run_id')}, expected {run_id}")
    if data.get("status") != "COMPLETE":
        failures.append(f"status is {data.get('status', 'missing')}")
    if review_status != "approved":
        failures.append(f"review is {review_status or 'missing'}")
    if not external_capture_passed:
        failures.append("required external capture proof is missing or failed")
    if not external_capture_path.is_file():
        failures.append("external capture artifact is missing")
    elif not external_capture_artifact_passed:
        detail = "external capture artifact is failed or missing a passed summary"
        if external_capture_artifact_error:
            detail += f": {external_capture_artifact_error}"
        failures.append(detail)
    if not report_path.is_file():
        failures.append("final report is missing")
    if not patch_path.is_file():
        failures.append("final patch is missing")
    if not applied:
        failures.append("final patch is not applied to source")
    elif patch_path.is_file():
        _validate_applied_source(
            repo=repo,
            run_root=run_root,
            patch_path=patch_path,
            failures=failures,
        )
    proof = {
        "ok": not failures,
        "run_id": run_id,
        "result_path": str(result_path),
        "final_report": str(report_path),
        "final_patch": str(patch_path),
        "external_capture": str(external_capture_path),
        "artifact_ledger": str(ledger_path),
        "review_status": review_status or "",
        "applied_to_source": applied,
        "detail": (
            f"run {run_id}; report={report_path}; patch={patch_path}; external_capture={external_capture_path}; review={review_status}; applied={applied}"
            if not failures
            else f"run {run_id} incomplete: " + "; ".join(failures)
        ),
        "next": f"{PUBLIC_COMMAND} run --continue {run_id} --apply",
    }
    return proof


def _command_text(argv: list[str]) -> str:
    return " ".join(argv)


def _production_handoff_markdown(report: dict[str, Any]) -> str:
    metadata = report.get("metadata", {})
    git_head = report.get("git_head", {})
    gate_runs = report.get("gate_runs", [])
    failed_items = [item for item in report.get("items", []) if not item.get("ok")]

    lines = [
        "# Production Handoff",
        "",
        f"Status: {report['status']}",
        f"Repo: `{report['repo']}`",
        "",
        "## Operator Decision",
        "",
    ]
    if report.get("ok"):
        lines.append("Ship when the human operator is ready.")
    else:
        lines.append("Do not ship yet.")
    lines.extend(
        [
            "",
            "## Ship Target",
            "",
            metadata.get("target") or "Missing deployment target.",
            "",
            "## Rollback Plan",
            "",
            metadata.get("rollback") or "Missing rollback notes.",
            "",
            "## Human Approval",
            "",
            metadata.get("approved_by") or "Missing approver.",
            "",
            "## Current Code",
            "",
        ]
    )
    commit = git_head.get("commit") or "unknown"
    subject = git_head.get("subject") or "unknown"
    branch = git_head.get("branch") or "unknown"
    lines.append(f"- Branch: `{branch}`")
    lines.append(f"- Commit: `{commit}`")
    lines.append(f"- Commit message: {subject}")

    run_proof = report.get("manageroo_run", {})
    lines.extend(["", "## Manageroo Run Proof", ""])
    if run_proof.get("ok"):
        lines.append(f"- Manageroo run: `{run_proof.get('run_id')}`")
        lines.append(f"- Final report: `{run_proof.get('final_report')}`")
        lines.append(f"- Final patch: `{run_proof.get('final_patch')}`")
        lines.append(f"- Review status: `{run_proof.get('review_status')}`")
        lines.append(f"- Applied to source: `{run_proof.get('applied_to_source')}`")
    else:
        lines.append(f"- Missing or incomplete: {run_proof.get('detail', 'no Manageroo run proof')}")

    files = git_head.get("files") or []
    lines.extend(["", "## What Changed", ""])
    if files:
        lines.extend(f"- `{item}`" for item in files)
    else:
        lines.append("- No latest-commit file list was available.")

    lines.extend(["", "## Proof That Passed", ""])
    passed = [
        run
        for run in gate_runs
        if isinstance(run, dict) and run.get("result", {}).get("exit_code") == 0
    ]
    if passed:
        for run in passed:
            gate = run.get("gate", {})
            result = run.get("result", {})
            lines.append(
                f"- `{gate.get('id', 'gate')}`: `{_command_text(list(result.get('argv') or gate.get('argv') or []))}`"
            )
    else:
        lines.append("- No passing verification commands were recorded.")

    lines.extend(["", "## Release Blockers", ""])
    if failed_items:
        for item in failed_items:
            detail = item.get("detail") or "missing"
            next_command = item.get("next") or ""
            line = f"- {item.get('name', 'unknown')}: {detail}"
            if next_command:
                line += f" Next: `{next_command}`"
            lines.append(line)
    else:
        lines.append("- None detected by `release-ready`.")

    lines.extend(["", "## Project Memory", ""])
    memory_update = report.get("project_memory_update")
    if memory_update:
        lines.append(f"- Updated: `{memory_update.get('path')}`")
    elif report.get("ok"):
        lines.append("- Not updated.")
    else:
        lines.append("- Not updated because the release gate is not ready.")

    lines.extend(["", "## Next Operator Action", ""])
    if report.get("ok"):
        lines.append("Use the ship target above, keep the rollback plan open, and watch production after release.")
    elif report.get("next_commands"):
        lines.append(f"Run: `{report['next_commands'][0]}`")
    else:
        lines.append("Fix the release blockers above, then rerun `manageroo release-ready`.")
    lines.append("")
    return "\n".join(lines)


def _release_memory_update(repo: Path, report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("metadata", {})
    git_head = report.get("git_head", {})
    target = str(metadata.get("target") or "release target")
    commit = str(git_head.get("commit") or "unknown commit")
    subject = str(git_head.get("subject") or "unknown change")
    shipped = [
        f"Release-ready approved for {target} at commit {commit}: {subject}",
    ]
    run_proof = report.get("manageroo_run", {})
    if run_proof.get("run_id"):
        shipped.append(f"Manageroo run proof: {run_proof['run_id']}")
    proof: list[str] = []
    if run_proof.get("ok"):
        proof.append(
            "Manageroo completed run "
            f"{run_proof.get('run_id')} with review={run_proof.get('review_status')} "
            f"and applied_to_source={run_proof.get('applied_to_source')}."
        )
    for run in report.get("gate_runs", []):
        if not isinstance(run, dict) or run.get("result", {}).get("exit_code") != 0:
            continue
        gate = run.get("gate", {})
        result = run.get("result", {})
        argv = list(result.get("argv") or gate.get("argv") or [])
        proof.append(f"release-ready passed {gate.get('id', 'gate')}: {_command_text(argv)}")
    if not proof:
        proof.append("release-ready recorded no passing verification commands.")
    notes = [
        f"Production handoff: {report.get('handoff_path')}",
        f"Final report: {run_proof.get('final_report')}",
        f"Final patch: {run_proof.get('final_patch')}",
        f"Rollback plan: {metadata.get('rollback')}",
        f"Approved by: {metadata.get('approved_by')}",
    ]
    return ensure_project_memory(repo, shipped=shipped, proof=proof, notes=notes)


def release_ready(
    repo_path: Path,
    *,
    target: str = "",
    rollback: str = "",
    approved_by: str = "",
    run_checks: bool = True,
    save: bool = False,
) -> dict[str, Any]:
    repo = git_root(repo_path)
    metadata = _load_metadata(repo)
    target = target.strip() or str(metadata.get("target", "")).strip()
    rollback = rollback.strip() or str(metadata.get("rollback", "")).strip()
    approved_by = approved_by.strip() or str(metadata.get("approved_by", "")).strip()
    if save:
        metadata = {
            "target": target,
            "rollback": rollback,
            "approved_by": approved_by,
            "updated_at": utc_now(),
        }
        atomic_write_json(_metadata_path(repo), metadata)

    items: list[dict[str, Any]] = []
    next_commands: list[str] = []

    ready_report = readiness(repo)
    items.append(
        _item(
            "base readiness",
            bool(ready_report["ok"]),
            ready_report["status"],
            ready_report["next_commands"][0] if ready_report.get("next_commands") else f"{PUBLIC_COMMAND} ready",
        )
    )

    run_proof = _latest_manageroo_run_proof(repo)
    items.append(
        _item(
            "completed Manageroo run",
            bool(run_proof["ok"]),
            run_proof["detail"],
            run_proof["next"],
        )
    )

    gate_runs: list[dict[str, Any]] = []
    try:
        config = load_config(repo)
        gates = gates_from_config(config)
    except MANAGEROOError as exc:
        config = None
        gates = []
        items.append(_item("project config", False, str(exc), f"{PUBLIC_COMMAND} init"))

    items.append(
        _item(
            "verification gates",
            bool(gates),
            ", ".join(gate.id for gate in gates) if gates else "no verification gates configured",
            f"{PUBLIC_COMMAND} checks suggest",
        )
    )

    if gates and run_checks and config is not None:
        runner = GateRunner(
            CommandRunner(log_root=repo / PROJECT_DIR / "cache" / "release-ready-logs"),
            CommandPolicy(tuple(config["safety"]["allowed_programs"])),
            repo / PROJECT_DIR / "cache" / "release-ready-logs",
        )
        try:
            outcomes = runner.run(gates, repo, require_one=True)
            gate_runs = [outcome.to_dict() for outcome in outcomes]
            items.append(
                _item(
                    "verification gates pass",
                    True,
                    ", ".join(outcome.gate.id for outcome in outcomes),
                )
            )
        except MANAGEROOError as exc:
            items.append(
                _item(
                    "verification gates pass",
                    False,
                    str(exc),
                    f"{PUBLIC_COMMAND} checks list",
                )
            )
    elif gates:
        items.append(
            _item(
                "verification gates pass",
                False,
                "not run",
                f"{PUBLIC_COMMAND} release-ready",
            )
        )
    else:
        items.append(
            _item(
                "verification gates pass",
                False,
                "nothing to run",
                f"{PUBLIC_COMMAND} checks suggest",
            )
        )

    clean, status_text = _git_status(repo)
    items.append(
        _item(
            "git clean",
            clean,
            "clean" if clean else status_text,
            "git status --short",
        )
    )

    items.extend(
        [
            _item(
                "deployment target",
                bool(target),
                target or "missing",
                _release_metadata_command(),
            ),
            _item(
                "rollback notes",
                bool(rollback),
                rollback or "missing",
                _release_metadata_command(),
            ),
            _item(
                "human approval",
                bool(approved_by),
                approved_by or "missing",
                _release_metadata_command(),
            ),
        ]
    )

    for item in items:
        if not item["ok"] and item.get("next") and item["next"] not in next_commands:
            next_commands.append(item["next"])

    ok = all(item["ok"] for item in items)
    git_head = _git_head_summary(repo)
    report = {
        "ok": ok,
        "status": "READY FOR OPERATOR RELEASE" if ok else "NOT READY FOR RELEASE",
        "repo": str(repo),
        "metadata_path": str(_metadata_path(repo)),
        "metadata": {
            "target": target,
            "rollback": rollback,
            "approved_by": approved_by,
        },
        "items": items,
        "readiness": ready_report,
        "manageroo_run": run_proof,
        "gate_runs": gate_runs,
        "git_head": git_head,
        "git_status": status_text,
        "next_commands": [] if ok else next_commands,
        "project_memory_update": None,
    }
    handoff_path = _handoff_path(repo)
    report["handoff_path"] = str(handoff_path)
    if ok:
        report["project_memory_update"] = _release_memory_update(repo, report)
    handoff_markdown = _production_handoff_markdown(report)
    atomic_write_text(handoff_path, handoff_markdown)
    report["handoff_markdown"] = handoff_markdown
    return report


def format_release_ready(report: dict[str, Any]) -> str:
    lines = [report["status"], ""]
    for item in report["items"]:
        label = "OK" if item["ok"] else "ACTION"
        lines.append(f"{label} {item['name']}: {item['detail']}")
    if report.get("handoff_path"):
        lines.extend(["", f"Production handoff: {report['handoff_path']}"])
    if report.get("project_memory_update"):
        lines.append(f"Project memory updated: {report['project_memory_update']['path']}")
    if report.get("next_commands"):
        lines.extend(["", "Next:"])
        lines.append(report["next_commands"][0])
    return "\n".join(lines) + "\n"
