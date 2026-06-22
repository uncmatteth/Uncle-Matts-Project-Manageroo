from __future__ import annotations

from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .errors import UMSMFBURASBOFEError
from .gates import GateRunner, gates_from_config
from .policy import CommandPolicy
from .project import git_root
from .readiness import readiness
from .runner import CommandRunner
from .util import atomic_write_json, read_json, utc_now


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

    gate_runs: list[dict[str, Any]] = []
    try:
        config = load_config(repo)
        gates = gates_from_config(config)
    except UMSMFBURASBOFEError as exc:
        config = None
        gates = []
        items.append(_item("project config", False, str(exc), f"{PUBLIC_COMMAND} init"))

    items.append(
        _item(
            "verification gates",
            bool(gates),
            ", ".join(gate.id for gate in gates) if gates else "no verification gates configured",
            f"{PUBLIC_COMMAND} checks add smoke -- npm test",
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
        except UMSMFBURASBOFEError as exc:
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
                f"{PUBLIC_COMMAND} checks add smoke -- npm test",
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
    return {
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
        "gate_runs": gate_runs,
        "git_status": status_text,
        "next_commands": [] if ok else next_commands,
    }


def format_release_ready(report: dict[str, Any]) -> str:
    lines = [report["status"], ""]
    for item in report["items"]:
        label = "OK" if item["ok"] else "ACTION"
        lines.append(f"{label} {item['name']}: {item['detail']}")
    if report.get("next_commands"):
        lines.extend(["", "Next:"])
        lines.append(report["next_commands"][0])
    return "\n".join(lines) + "\n"
