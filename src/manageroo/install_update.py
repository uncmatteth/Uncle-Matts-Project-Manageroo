from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from .install_status import (
    _validated_launcher_value,
    default_prefix,
    installation_is_manageroo_owned,
    read_install_lock,
)


_VERSION = re.compile(r"\b\d{4}\.\d+\.\d+\.\d+\b")


def _source_version(source: Path) -> str:
    project_file = source / "pyproject.toml"
    with project_file.open("rb") as handle:
        payload = tomllib.load(handle)
    version = payload.get("project", {}).get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError(f"Manageroo source has an invalid project version: {project_file}")
    return version


def _installed_version(lock: dict[str, Any]) -> str:
    match = _VERSION.search(str(lock.get("manageroo_version_output") or ""))
    return match.group(0) if match else "unknown"


def update_install(
    *,
    prefix: Path | None = None,
    source: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    selected_prefix = (prefix or default_prefix()).expanduser().resolve()
    loaded = read_install_lock(selected_prefix / "install-lock.json")
    if not loaded.get("ok"):
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "error": str(loaded.get("error") or "Manageroo install lock is unavailable."),
            "next_commands": list(loaded.get("next_commands") or []),
        }
    if not installation_is_manageroo_owned(selected_prefix):
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "error": "Manageroo installation ownership could not be verified; refusing update.",
            "next_commands": [],
        }
    lock = loaded["lock"]
    source_value = source if source is not None else lock.get("source_root")
    if not isinstance(source_value, (str, os.PathLike)):
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "error": "The original Manageroo source folder is not recorded. Download a current release and rerun with --source PATH.",
            "next_commands": ["manageroo update --source /path/to/current/Manageroo --apply"],
        }
    unresolved_source = Path(source_value).expanduser()
    try:
        if unresolved_source.is_symlink():
            raise ValueError("source folder must not be a symlink")
        selected_source = unresolved_source.resolve(strict=True)
        installer = selected_source / "install.sh"
        required = (installer, selected_source / "scripts" / "install.py", selected_source / "pyproject.toml")
        if any(path.is_symlink() or not path.is_file() for path in required):
            raise ValueError("source folder is not a complete Manageroo release")
        available_version = _source_version(selected_source)
    except (OSError, RuntimeError, ValueError, tomllib.TOMLDecodeError) as exc:
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "source": str(unresolved_source),
            "error": f"Manageroo update source is invalid: {exc}",
            "next_commands": ["manageroo update --source /path/to/current/Manageroo --apply"],
        }
    launcher_value, launcher_problem = _validated_launcher_value(lock.get("launcher"))
    if launcher_problem or launcher_value is None:
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "source": str(selected_source),
            "error": (
                "The owned installation does not record a valid Manageroo launcher; "
                "rerun the full installer before updating."
            ),
            "next_commands": [str(installer)],
        }
    launcher = Path(launcher_value).expanduser()
    bin_dir = launcher.parent.resolve(strict=False)
    agent = str(lock.get("agent_preference") or "auto")
    if agent not in {"ask", "auto", "codex", "claude-code", "gemini"}:
        agent = "auto"
    token_record = lock.get("token_mode")
    token_mode = str(token_record.get("mode") if isinstance(token_record, dict) else token_record or "off")
    if token_mode not in {"off", "caveman", "curse"}:
        token_mode = "off"
    shell = shutil.which("sh")
    if shell is None:
        return {
            "ok": False,
            "applied": False,
            "prefix": str(selected_prefix),
            "source": str(selected_source),
            "error": "A POSIX sh executable is required to update Manageroo.",
            "next_commands": [],
        }
    argv = [
        shell,
        str(installer),
        "--prefix",
        str(selected_prefix),
        "--bin-dir",
        str(bin_dir),
        "--agent",
        agent,
        "--stack",
        "skip",
        "--skill-pack",
        "install",
        "--token-mode",
        token_mode,
        "--stack-doctor",
        "skip",
        "--no-music",
        "--no-animation",
    ]
    report = {
        "ok": True,
        "applied": False,
        "prefix": str(selected_prefix),
        "source": str(selected_source),
        "installed_version": _installed_version(lock),
        "available_version": available_version,
        "argv": argv,
        "next_commands": ["manageroo update --apply"] if not apply else [],
    }
    if not apply:
        return report
    completed = subprocess.run(
        argv,
        cwd=selected_source,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    report["applied"] = completed.returncode == 0
    report["ok"] = completed.returncode == 0
    report["exit_code"] = completed.returncode
    if completed.returncode:
        report["error"] = f"Manageroo installer exited with code {completed.returncode}."
    return report


def format_install_update(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        lines = [f"UPDATE BLOCKED: {report.get('error', 'unknown update error')}"]
    elif report.get("applied"):
        lines = [f"UPDATED Manageroo to {report.get('available_version')}"]
    else:
        lines = [
            f"UPDATE READY: {report.get('installed_version')} -> {report.get('available_version')}",
            f"Source: {report.get('source')}",
            "No changes were made.",
        ]
    for command in report.get("next_commands", []):
        lines.append(f"Next: {command}")
    return "\n".join(lines) + "\n"
