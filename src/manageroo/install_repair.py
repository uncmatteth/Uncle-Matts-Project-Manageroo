from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path
from typing import Any

from .install_status import _validated_launcher_value, launcher_is_manageroo_owned
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
    if any(character in text for character in ("\r", "\n", '"', "%")):
        raise ValueError(f"Unsafe character in launcher path: {text!r}")
    return text


def _write_launcher(launcher: Path, *, python: Path, app_root: Path, prefix: Path) -> None:
    if launcher.is_symlink():
        raise ValueError(f"Refusing to write through symlinked launcher path: {launcher}")
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
        launcher.write_text(
            "#!/bin/sh\n"
            f"export PYTHONPATH={shlex.quote(str(app_root))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
            f"export MANAGEROO_PREFIX={shlex.quote(str(prefix))}\n"
            f"exec {shlex.quote(str(python))} -m manageroo \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)


def _check(name: str, ok: bool, detail: str, next_command: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "next": next_command}


def _invalid_report(prefix: Path, detail: str, *, bin_dir: Path | None = None) -> dict[str, Any]:
    report = {
        "ok": False,
        "prefix": str(prefix),
        "checks": [_check("install-lock", False, detail, "./install.sh")],
        "actions": [],
        "next_commands": ["./install.sh"],
    }
    if bin_dir is not None:
        report["bin_dir"] = str(bin_dir)
    return report


def helper_skills_present() -> bool:
    roots = [token_mode_skills_dir(), Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]
    for skill in CORE_HELPER_SKILLS:
        if not any((root / skill / "SKILL.md").is_file() for root in roots):
            return False
    return True


def repair_install(*, prefix: Path | None = None, bin_dir: Path | None = None, apply: bool = True) -> dict[str, Any]:
    prefix = (prefix or default_prefix()).expanduser().resolve()
    requested_bin_dir = bin_dir.expanduser().resolve() if bin_dir is not None else None
    fallback_bin_dir = requested_bin_dir or default_bin_dir().expanduser().resolve()
    lock_path = prefix / "install-lock.json"
    checks: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    next_commands: list[str] = []
    if not lock_path.exists():
        return _invalid_report(prefix, "missing", bin_dir=fallback_bin_dir)
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _invalid_report(prefix, f"malformed or unreadable: {exc}", bin_dir=fallback_bin_dir)
    if not isinstance(lock, dict):
        return _invalid_report(prefix, "must contain a JSON object", bin_dir=fallback_bin_dir)

    raw_launcher = lock.get("launcher")
    validated_launcher, launcher_problem = _validated_launcher_value(raw_launcher)
    if launcher_problem:
        return _invalid_report(prefix, launcher_problem, bin_dir=fallback_bin_dir)
    expected_name = "manageroo.cmd" if os.name == "nt" else "manageroo"
    launcher = Path(validated_launcher).expanduser() if validated_launcher else fallback_bin_dir / expected_name
    effective_bin_dir = launcher.parent.expanduser().resolve()

    # When the operator explicitly supplied --bin-dir, do not silently mutate a different
    # recorded launcher. Without an explicit override, the install lock remains the source
    # of truth for custom installation locations.
    if requested_bin_dir is not None and effective_bin_dir != requested_bin_dir:
        return _invalid_report(
            prefix,
            f"recorded launcher is outside the requested Manageroo bin directory; rerun with --bin-dir {effective_bin_dir} only if that is the intended installation",
            bin_dir=effective_bin_dir,
        )
    if launcher.name != expected_name:
        return _invalid_report(prefix, f"recorded launcher has unexpected basename: {launcher.name}", bin_dir=effective_bin_dir)

    app_root = current_app_root()
    python = Path(sys.executable)
    checks.append(_check("install-lock", True, str(lock_path)))
    checks.append(_check("app-root", app_root.exists(), str(app_root), "./install.sh"))
    checks.append(_check("python", python.exists(), str(python), "Install Python 3.11+"))

    if launcher.is_symlink():
        checks.append(_check("launcher-shape", False, "launcher is a symlink; refusing mutation", "./install.sh"))
        next_commands.append("./install.sh")
    elif not launcher.exists():
        if apply:
            try:
                _write_launcher(launcher, python=python, app_root=app_root, prefix=prefix)
                actions.append({"name": "launcher", "status": "recreated", "path": str(launcher)})
            except (OSError, ValueError) as exc:
                checks.append(_check("launcher-write", False, str(exc), "./install.sh"))
                next_commands.append("./install.sh")
        else:
            next_commands.append("manageroo repair-install")
    elif not launcher.is_file() or not launcher_is_manageroo_owned(launcher):
        checks.append(_check("launcher-ownership", False, "existing launcher is not a verified Manageroo launcher", "./install.sh"))
        next_commands.append("./install.sh")
    elif os.name != "nt" and not os.access(launcher, os.X_OK):
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

    launcher_ok = launcher_is_manageroo_owned(launcher) and (os.name == "nt" or os.access(launcher, os.X_OK))
    checks.append(_check("launcher", launcher_ok, str(launcher) if launcher_ok else "missing, unsafe, unowned, or not executable", "manageroo repair-install" if launcher.exists() and launcher.is_file() else "./install.sh"))

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
        checks.append(_check("skill-pack", True, "present" if present else "missing; strongly suggested", "manageroo skills reconcile --apply"))
        if not present:
            next_commands.append("manageroo skills reconcile --apply")

    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "prefix": str(prefix),
        "bin_dir": str(effective_bin_dir),
        "lock": str(lock_path),
        "checks": checks,
        "actions": actions,
        "next_commands": next_commands,
    }


def format_repair_install(report: dict[str, Any]) -> str:
    lines = ["INSTALL REPAIR: OK" if report.get("ok") else "INSTALL REPAIR: ACTION"]
    for check in report.get("checks", []):
        lines.append(f"{'OK' if check.get('ok') else 'ACTION'} {check['name']}: {check['detail']}")
    for action in report.get("actions", []):
        lines.append(f"FIXED {action['name']}: {action.get('path') or action.get('status')}")
    for command in report.get("next_commands", []):
        lines.append(f"Next: {command}")
    return "\n".join(lines) + "\n"
