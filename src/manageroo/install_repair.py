from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

from .token_modes import CORE_HELPER_SKILLS, install_core_helper_skills, token_mode_skills_dir


def default_prefix() -> Path:
    explicit = os.environ.get("MANAGEROO_PREFIX")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".local" / "share" / "manageroo"


def default_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def current_app_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_launcher_text(value: Path) -> str:
    text = str(value)
    if any(character in text for character in ("\r", "\n", '"')):
        raise ValueError(f"Unsafe character in launcher path: {text!r}")
    return text


def _write_launcher(launcher: Path, *, python: Path, app_root: Path, prefix: Path) -> None:
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt" or launcher.suffix.lower() == ".cmd":
        app_text = _safe_launcher_text(app_root)
        prefix_text = _safe_launcher_text(prefix)
        python_text = _safe_launcher_text(python)
        launcher.write_text(
            f'@set "PYTHONPATH={app_text}"\r\n'
            f'@set "MANAGEROO_PREFIX={prefix_text}"\r\n'
            f'@"{python_text}" -m manageroo %*\r\n',
            encoding="utf-8",
        )
    else:
        app_value = shlex.quote(str(app_root))
        prefix_value = shlex.quote(str(prefix))
        python_value = shlex.quote(str(python))
        launcher.write_text(
            "#!/bin/sh\n"
            f"export PYTHONPATH={app_value}${{PYTHONPATH:+:$PYTHONPATH}}\n"
            f"export MANAGEROO_PREFIX={prefix_value}\n"
            f"exec {python_value} -m manageroo \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)


def _check(name: str, ok: bool, detail: str, next_command: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "next": next_command}


def helper_skills_present() -> bool:
    roots = [
        token_mode_skills_dir(),
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
    ]
    for skill in CORE_HELPER_SKILLS:
        if not any((root / skill / "SKILL.md").is_file() for root in roots):
            return False
    return True


def repair_install(
    *,
    prefix: Path | None = None,
    bin_dir: Path | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    prefix = (prefix or default_prefix()).expanduser().resolve()
    bin_dir = (bin_dir or default_bin_dir()).expanduser().resolve()
    lock_path = prefix / "install-lock.json"
    checks: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    next_commands: list[str] = []
    if not lock_path.exists():
        return {
            "ok": False,
            "prefix": str(prefix),
            "checks": [_check("install-lock", False, "missing", "./install.sh")],
            "actions": actions,
            "next_commands": ["./install.sh"],
        }

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "prefix": str(prefix),
            "checks": [_check("install-lock", False, f"malformed or unreadable: {exc}", "./install.sh")],
            "actions": actions,
            "next_commands": ["./install.sh"],
        }
    if not isinstance(lock, dict):
        return {
            "ok": False,
            "prefix": str(prefix),
            "checks": [_check("install-lock", False, "must contain a JSON object", "./install.sh")],
            "actions": actions,
            "next_commands": ["./install.sh"],
        }

    launcher = Path(lock.get("launcher") or bin_dir / "manageroo").expanduser()
    reported_bin_dir = launcher.parent.expanduser().resolve()
    app_root = current_app_root()
    python = Path(sys.executable)

    checks.append(_check("install-lock", True, str(lock_path)))
    checks.append(_check("app-root", app_root.exists(), str(app_root), "./install.sh"))
    checks.append(_check("python", python.exists(), str(python), "Install Python 3.11+"))

    if not launcher.exists():
        if apply:
            try:
                _write_launcher(launcher, python=python, app_root=app_root, prefix=prefix)
                actions.append({"name": "launcher", "status": "recreated", "path": str(launcher)})
            except (OSError, ValueError) as exc:
                checks.append(_check("launcher-write", False, str(exc), "./install.sh"))
                next_commands.append("./install.sh")
        else:
            next_commands.append("manageroo repair-install")
    elif os.name != "nt" and launcher.is_file() and not launcher.is_symlink() and not os.access(launcher, os.X_OK):
        if apply:
            try:
                current_mode = stat.S_IMODE(launcher.stat().st_mode)
                launcher.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                actions.append({"name": "launcher", "status": "made executable", "path": str(launcher)})
            except OSError as exc:
                checks.append(_check("launcher-permissions", False, str(exc), "./install.sh"))
                next_commands.append("./install.sh")
        else:
            next_commands.append("manageroo repair-install")
    elif launcher.exists() and (launcher.is_symlink() or not launcher.is_file()):
        checks.append(_check("launcher-shape", False, "launcher is not a regular file", "./install.sh"))
        next_commands.append("./install.sh")

    launcher_ok = launcher.exists() and launcher.is_file() and not launcher.is_symlink() and (
        os.name == "nt" or os.access(launcher, os.X_OK)
    )
    checks.append(
        _check(
            "launcher",
            launcher_ok,
            str(launcher) if launcher_ok else "missing, unsafe, or not executable",
            "manageroo repair-install" if launcher.exists() and launcher.is_file() else "./install.sh",
        )
    )

    if apply:
        try:
            installed = install_core_helper_skills()
            actions.append({"name": "skill-pack", "status": "checked", "paths": installed})
            checks.append(_check("skill-pack", True, "installed or refreshed"))
        except Exception as exc:
            checks.append(_check("skill-pack", False, str(exc), "manageroo skills reconcile --apply"))
            next_commands.append("manageroo skills reconcile --apply")
    else:
        present = helper_skills_present()
        checks.append(
            _check(
                "skill-pack",
                True,
                "present" if present else "missing; strongly suggested",
                "manageroo skills reconcile --apply",
            )
        )
        if not present:
            next_commands.append("manageroo skills reconcile --apply")

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "prefix": str(prefix),
        "bin_dir": str(reported_bin_dir),
        "lock": str(lock_path),
        "checks": checks,
        "actions": actions,
        "next_commands": next_commands,
    }


def format_repair_install(report: dict[str, Any]) -> str:
    lines = ["INSTALL REPAIR: OK" if report.get("ok") else "INSTALL REPAIR: ACTION"]
    for check in report.get("checks", []):
        label = "OK" if check.get("ok") else "ACTION"
        lines.append(f"{label} {check['name']}: {check['detail']}")
    for action in report.get("actions", []):
        lines.append(f"FIXED {action['name']}: {action.get('path') or action.get('status')}")
    for command in report.get("next_commands", []):
        lines.append(f"Next: {command}")
    return "\n".join(lines) + "\n"