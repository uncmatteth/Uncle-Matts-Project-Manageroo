from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .token_modes import CORE_HELPER_SKILLS, install_core_helper_skills, token_mode_skills_dir


def default_prefix() -> Path:
    explicit = os.environ.get("UMSMFBURASBOFE_PREFIX")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".local" / "share" / "umsmfburasbofe"


def default_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def current_app_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_launcher(launcher: Path, *, python: Path, app_root: Path, prefix: Path) -> None:
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt" or launcher.suffix.lower() == ".cmd":
        launcher.write_text(
            f'@set "PYTHONPATH={app_root}"\r\n'
            f'@set "UMSMFBURASBOFE_PREFIX={prefix}"\r\n'
            f'@"{python}" -m umsmfburasbofe %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher.write_text(
            "#!/bin/sh\n"
            f'export PYTHONPATH="{app_root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
            f'export UMSMFBURASBOFE_PREFIX="{prefix}"\n'
            f'exec "{python}" -m umsmfburasbofe "$@"\n',
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
            "checks": [
                _check("install-lock", False, "missing", "./install.sh"),
            ],
            "actions": actions,
            "next_commands": ["./install.sh"],
        }

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    launcher = Path(lock.get("launcher") or bin_dir / "umsmfburasbofe").expanduser()
    reported_bin_dir = launcher.parent.expanduser().resolve()
    app_root = current_app_root()
    python = Path(sys.executable)

    checks.append(_check("install-lock", True, str(lock_path)))
    checks.append(_check("app-root", app_root.exists(), str(app_root), "./install.sh"))
    checks.append(_check("python", python.exists(), str(python), "Install Python 3.11+"))

    if not launcher.exists():
        if apply:
            _write_launcher(launcher, python=python, app_root=app_root, prefix=prefix)
            actions.append({"name": "launcher", "status": "recreated", "path": str(launcher)})
        else:
            next_commands.append("umsmfburasbofe repair-install")
    checks.append(
        _check(
            "launcher",
            launcher.exists(),
            str(launcher) if launcher.exists() else "missing",
            "umsmfburasbofe repair-install",
        )
    )

    if apply:
        try:
            installed = install_core_helper_skills()
            actions.append({"name": "helper-skills", "status": "checked", "paths": installed})
            checks.append(_check("helper-skills", True, "installed or refreshed"))
        except Exception as exc:
            checks.append(_check("helper-skills", False, str(exc), "umsmfburasbofe skills install"))
            next_commands.append("umsmfburasbofe skills install")
    else:
        present = helper_skills_present()
        checks.append(
            _check(
                "helper-skills",
                present,
                "present" if present else "missing",
                "umsmfburasbofe skills install",
            )
        )
        if not present:
            next_commands.append("umsmfburasbofe skills install")

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
