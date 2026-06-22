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
from .util import atomic_write_json, atomic_write_text, read_json, utc_now


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
    patch_value = data.get("evidence_paths", {}).get("patch")
    patch_path = Path(patch_value) if patch_value else delivery / "final.patch"
    review_status = data.get("review", {}).get("status")
    applied = bool(data.get("applied_to_source"))
    failures: list[str] = []
    if data.get("status") != "COMPLETE":
        failures.append(f"status is {data.get('status', 'missing')}")
    if review_status != "approved":
        failures.append(f"review is {review_status or 'missing'}")
    if not report_path.is_file():
        failures.append("final report is missing")
    if not patch_path.is_file():
        failures.append("final patch is missing")
    if not applied:
        failures.append("final patch is not applied to source")
    proof = {
        "ok": not failures,
        "run_id": run_id,
        "result_path": str(result_path),
        "final_report": str(report_path),
        "final_patch": str(patch_path),
        "review_status": review_status or "",
        "applied_to_source": applied,
        "detail": (
            f"run {run_id}; report={report_path}; patch={patch_path}; review={review_status}; applied={applied}"
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
