from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from .branding import PUBLIC_COMMAND
from .token_modes import CORE_HELPER_SKILLS, token_mode_skills_dir


DEFAULT_PREFIX = Path.home() / ".local" / "share" / PUBLIC_COMMAND
DEFAULT_BIN_DIR = Path.home() / ".local" / "bin"
LAUNCHER_BASENAMES = {PUBLIC_COMMAND, f"{PUBLIC_COMMAND}.cmd"}


def default_prefix() -> Path:
    return Path(os.environ.get("MANAGEROO_PREFIX") or DEFAULT_PREFIX).expanduser()


def default_lock_path(prefix: Path | None = None) -> Path:
    return (prefix.expanduser() if prefix else default_prefix()) / "install-lock.json"


def _invalid_lock(lock_path: Path, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "lock_path": str(lock_path),
        "error": f"install-lock.json is invalid: {detail}",
        "next_commands": ["Run the Manageroo installer again to recreate install-lock.json."],
    }


def _validate_command_list(value: Any, field: str) -> str | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return f"{field} must be a list of strings"
    return None


def _validated_launcher_value(value: Any) -> tuple[str | None, str | None]:
    if value in (None, ""):
        return None, None
    if not isinstance(value, str) or not value.strip():
        return None, "launcher must be a non-empty absolute path string when present"
    path = Path(value).expanduser()
    if not path.is_absolute():
        return None, "launcher must be an absolute path"
    if path.name not in LAUNCHER_BASENAMES:
        return None, f"launcher basename must be one of: {', '.join(sorted(LAUNCHER_BASENAMES))}"
    return str(path), None


def launcher_is_manageroo_owned(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        return False
    return "MANAGEROO_PREFIX" in text and "-m manageroo" in text


def _validate_lock_payload(payload: dict[str, Any]) -> str | None:
    _, launcher_problem = _validated_launcher_value(payload.get("launcher"))
    if launcher_problem:
        return launcher_problem
    external_tools = payload.get("external_tools", [])
    if not isinstance(external_tools, list):
        return "external_tools must be a list"
    for index, tool in enumerate(external_tools):
        if not isinstance(tool, dict):
            return f"external_tools[{index}] must be an object"
        for field in ("next_commands", "guidance_commands"):
            if field not in tool:
                continue
            problem = _validate_command_list(tool[field], f"external_tools[{index}].{field}")
            if problem:
                return problem
    stack_summary = payload.get("stack_summary")
    if stack_summary is not None and not isinstance(stack_summary, dict):
        return "stack_summary must be an object when present"
    if isinstance(stack_summary, dict):
        items = stack_summary.get("items", [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return "stack_summary.items must be a list of objects"
        for index, item in enumerate(items):
            if "next_commands" in item:
                problem = _validate_command_list(item["next_commands"], f"stack_summary.items[{index}].next_commands")
                if problem:
                    return problem
    return None


def read_install_lock(path: Path | None = None) -> dict[str, Any]:
    lock_path = (path or default_lock_path()).expanduser()
    if not lock_path.exists():
        return {
            "ok": False,
            "lock_path": str(lock_path),
            "error": "install-lock.json was not found. Run the installer first.",
            "next_commands": ["Run the Manageroo installer again to recreate install-lock.json."],
        }
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "lock_path": str(lock_path),
            "error": f"install-lock.json is unreadable or malformed: {exc}",
            "next_commands": ["Run the Manageroo installer again to recreate install-lock.json."],
        }
    if not isinstance(payload, dict):
        return _invalid_lock(lock_path, "top-level value must be a JSON object")
    problem = _validate_lock_payload(payload)
    if problem:
        return _invalid_lock(lock_path, problem)
    return {"ok": True, "lock_path": str(lock_path), "lock": payload}


def summarize_external_tools(external_tools: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    counts = {"installed": 0, "configured": 0, "skipped": 0, "needs_action": 0}
    for tool in external_tools:
        installed = bool(tool.get("installed") or tool.get("path"))
        configured_present = "configured" in tool
        configured = bool(tool.get("configured"))
        skipped = bool(tool.get("skipped"))
        next_commands = list(tool.get("next_commands") or []) + list(tool.get("guidance_commands") or [])
        needs_action = bool(skipped or tool.get("guidance") or tool.get("error") or next_commands or not installed or (configured_present and not configured))
        counts["installed"] += 1 if installed else 0
        counts["configured"] += 1 if configured else 0
        counts["skipped"] += 1 if skipped else 0
        counts["needs_action"] += 1 if needs_action else 0
        items.append({
            "name": tool.get("name", "unknown"), "installed": installed, "configured": configured,
            "skipped": skipped, "needs_action": needs_action, "path": tool.get("path"),
            "version": tool.get("version"), "reason": tool.get("reason") or tool.get("guidance") or tool.get("error") or "",
            "next_commands": next_commands, "reference": tool.get("reference"),
        })
    return {"counts": counts, "items": items}


def helper_skill_roots() -> list[Path]:
    roots: list[Path] = []
    for root in [token_mode_skills_dir(), Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]:
        expanded = root.expanduser()
        if expanded not in roots:
            roots.append(expanded)
    return roots


def _find_skill(skill: str) -> str | None:
    for root in helper_skill_roots():
        candidate = root / skill / "SKILL.md"
        if candidate.is_file():
            return str(candidate)
    return None


def _reconcile_summary(summary: dict[str, Any], probes: dict[str, str | None]) -> dict[str, Any]:
    items = []
    counts = {"installed": 0, "configured": 0, "skipped": 0, "needs_action": 0}
    for original in summary.get("items", []) if isinstance(summary, dict) else []:
        if not isinstance(original, dict):
            continue
        item = dict(original)
        name = str(item.get("name") or "unknown")
        live_path = probes.get(name)
        if name in probes and not live_path:
            item["installed"] = False
            item["configured"] = False
            item["needs_action"] = True
            item["reason"] = "Recorded as installed previously, but the current executable or skill path is no longer available."
        elif live_path:
            was_missing = not bool(item.get("installed"))
            item["path"] = live_path
            item["installed"] = True
            if was_missing:
                reason = str(item.get("reason") or "").casefold()
                if "not installed" in reason or "no longer available" in reason or "missing" in reason:
                    item["reason"] = ""
                    item["next_commands"] = []
                if not item.get("skipped") and item.get("configured", True) and not item.get("reason"):
                    item["needs_action"] = False
        item["next_commands"] = list(item.get("next_commands") or [])
        counts["installed"] += 1 if item.get("installed") else 0
        counts["configured"] += 1 if item.get("configured") else 0
        counts["skipped"] += 1 if item.get("skipped") else 0
        counts["needs_action"] += 1 if item.get("needs_action") else 0
        items.append(item)
    return {"counts": counts, "items": items}


def stack_status(lock_path: Path | None = None) -> dict[str, Any]:
    loaded = read_install_lock(lock_path)
    if not loaded["ok"]:
        return loaded
    lock = loaded["lock"]
    summary = summarize_external_tools(lock.get("external_tools", []))
    probes: dict[str, str | None] = {name: shutil.which(name) for name in ("codex", "gbrain", "gitnexus", "clawpatch", "obsidian")}
    probes["autoreview"] = _find_skill("autoreview")
    for skill in CORE_HELPER_SKILLS:
        probes[skill] = _find_skill(skill)
    cached_summary = lock.get("stack_summary") or summary
    live_summary = _reconcile_summary(cached_summary, probes)
    return {
        "ok": True, "lock_path": loaded["lock_path"], "installed_at": lock.get("installed_at"),
        "prefix": lock.get("prefix"), "launcher": lock.get("launcher"), "token_mode": lock.get("token_mode"),
        "stack_summary": live_summary, "cached_stack_summary": cached_summary, "current_tool_paths": probes,
    }


def uninstall_plan(prefix: Path | None = None, bin_dir: Path | None = None) -> dict[str, Any]:
    prefix = prefix.expanduser() if prefix else default_prefix()
    loaded = read_install_lock(default_lock_path(prefix))
    launchers: list[Path] = []
    if loaded.get("ok"):
        recorded = loaded["lock"].get("launcher")
        validated, _ = _validated_launcher_value(recorded)
        if validated:
            candidate = Path(validated)
            if launcher_is_manageroo_owned(candidate):
                launchers.append(candidate)
    elif bin_dir is not None:
        root = bin_dir.expanduser()
        for candidate in (root / PUBLIC_COMMAND, root / f"{PUBLIC_COMMAND}.cmd"):
            if launcher_is_manageroo_owned(candidate):
                launchers.append(candidate)
    launcher_commands = [shlex.join(["rm", "-f", *[str(path) for path in launchers]])] if launchers else []
    core_commands = [shlex.join(["rm", "-rf", str(prefix)]), *launcher_commands]
    return {
        "executes_deletions": False,
        "core_paths": [str(prefix), *[str(path) for path in launchers]],
        "core_commands": core_commands,
        "launcher_ownership_known": bool(launchers),
        "third_party_notes": [
            "GBrain, GitNexus, AUTOREVIEW, Clawpatch, Obsidian, Codex, Bun, Node, pnpm, Flatpak, Snap, Homebrew, and Winget are external tools.",
            "MANAGEROO does not remove third-party tools automatically.",
            "Use stack-status first, then remove only the external tools you intentionally want gone.",
            *([] if launchers else ["No Manageroo-owned launcher signature was verified, so no launcher deletion command was generated."]),
        ],
        "skill_paths_to_review": [
            str(root / skill)
            for root in helper_skill_roots()
            for skill in ("autoreview", "pimp-my-prompt", "edit-skill", "caveman", "uncle-matts-caveman-curse")
        ],
    }


def format_stack_status(status: dict[str, Any]) -> str:
    if not status.get("ok"):
        lines = [f"NOT READY: {status.get('error', 'install status unavailable')}"]
        for command in status.get("next_commands", []):
            lines.append(f"next: {command}")
        return "\n".join(lines) + "\n"
    lines = [f"Install lock: {status['lock_path']}", f"Launcher: {status.get('launcher') or '(unknown)'}", "", "Stack tools:"]
    for item in status.get("stack_summary", {}).get("items", []):
        state = "OK" if item.get("installed") and not item.get("needs_action") else "ACTION"
        lines.append(f"- {state} {item.get('name', 'unknown')}")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")
        if item.get("path"):
            lines.append(f"  path: {item['path']}")
        for command in list(item.get("next_commands") or []):
            lines.append(f"  next: {command}")
    return "\n".join(lines) + "\n"


def format_uninstall_plan(plan: dict[str, Any]) -> str:
    lines = ["Uninstall plan only. No deletions were executed.", "", "Core commands:"]
    lines.extend(f"- {command}" for command in plan["core_commands"])
    lines.append("")
    lines.append("Third-party notes:")
    lines.extend(f"- {item}" for item in plan["third_party_notes"])
    return "\n".join(lines) + "\n"
