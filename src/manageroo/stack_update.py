from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


GBRAIN_REFERENCE = "https://github.com/garrytan/gbrain"
GITNEXUS_REFERENCE = "https://github.com/nxpatterns/gitnexus"
AUTOREVIEW_REPO = "https://github.com/openclaw/agent-skills.git"
AUTOREVIEW_REFERENCE = "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview"
CLAWPATCH_REFERENCE = "https://github.com/openclaw/clawpatch"
OBSIDIAN_REFERENCE = "https://obsidian.md/download"
STACK_TOOL_NAMES = ("gbrain", "gitnexus", "autoreview", "clawpatch", "obsidian")


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 900) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd or Path.home()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "argv": argv,
            "output": (result.stdout or "")[-8000:],
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"ok": False, "exit_code": 124, "argv": argv, "output": output[-8000:]}
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "argv": argv, "output": str(exc)}


def _tool(name: str, installed: bool, commands: list[list[str]], reference: str, note: str = "") -> dict:
    return {
        "name": name,
        "installed": installed,
        "commands": commands,
        "reference": reference,
        "note": note,
    }


def _normalize_only(only: Iterable[str] | None) -> set[str] | None:
    if only is None:
        return None
    selected = {str(name).strip().lower() for name in only if str(name).strip()}
    unknown = selected - set(STACK_TOOL_NAMES)
    if unknown:
        raise ValueError(f"Unknown stack tool(s): {', '.join(sorted(unknown))}")
    return selected


def stack_update_plan(only: Iterable[str] | None = None) -> dict[str, Any]:
    selected = _normalize_only(only)
    gbrain = shutil.which("gbrain")
    npm = shutil.which("npm")
    gitnexus = shutil.which("gitnexus")
    pnpm = shutil.which("pnpm")
    clawpatch = shutil.which("clawpatch")
    obsidian = shutil.which("obsidian")

    autoreview_candidates = [
        Path.home() / ".agents" / "skills" / "autoreview" / "SKILL.md",
        Path.home() / ".codex" / "skills" / "autoreview" / "SKILL.md",
    ]
    autoreview_installed = any(path.is_file() for path in autoreview_candidates)

    gitnexus_commands: list[list[str]] = []
    gitnexus_note = (
        "Manageroo's recommended stack installs a persistent GitNexus CLI and runs `gitnexus setup`. "
        "Repository indexing remains project-specific and is performed with `gitnexus analyze` from a target repo."
    )
    if gitnexus and npm:
        gitnexus_commands.append([npm, "install", "-g", "gitnexus@latest"])
    elif gitnexus and pnpm:
        gitnexus_commands.append([pnpm, "add", "-g", "gitnexus@latest"])
    elif not gitnexus:
        gitnexus_note += " No persistent GitNexus installation was detected, so stack-update will not install one implicitly."

    obsidian_commands: list[list[str]] = []
    system = platform.system().lower()
    if system == "windows" and shutil.which("winget"):
        obsidian_commands.append([
            shutil.which("winget") or "winget",
            "upgrade",
            "--id",
            "Obsidian.Obsidian",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ])
    elif system == "darwin" and shutil.which("brew"):
        obsidian_commands.append([shutil.which("brew") or "brew", "upgrade", "--cask", "obsidian"])
    elif system == "linux" and shutil.which("flatpak"):
        obsidian_commands.append([
            shutil.which("flatpak") or "flatpak",
            "update",
            "--user",
            "-y",
            "md.obsidian.Obsidian",
        ])
    elif system == "linux" and shutil.which("snap"):
        obsidian_commands.append([shutil.which("snap") or "snap", "refresh", "obsidian"])

    tools = [
        _tool(
            "gbrain",
            bool(gbrain),
            [[gbrain, "upgrade"], [gbrain, "doctor", "--json"]] if gbrain else [],
            GBRAIN_REFERENCE,
            "Uses GBrain's supported upgrade command and verifies the result with `gbrain doctor --json`.",
        ),
        _tool(
            "gitnexus",
            bool(gitnexus),
            gitnexus_commands,
            GITNEXUS_REFERENCE,
            gitnexus_note,
        ),
        _tool(
            "autoreview",
            autoreview_installed,
            [],
            AUTOREVIEW_REFERENCE,
            "Updated from the canonical openclaw/agent-skills repository using its current autoreview folder.",
        ),
        _tool(
            "clawpatch",
            bool(clawpatch),
            [[pnpm, "add", "-g", "clawpatch@latest"], [clawpatch, "doctor"]]
            if clawpatch and pnpm
            else [],
            CLAWPATCH_REFERENCE,
            "Uses the existing pnpm-based package lane and reruns `clawpatch doctor` after update.",
        ),
        _tool(
            "obsidian",
            bool(obsidian),
            obsidian_commands,
            OBSIDIAN_REFERENCE,
            "Uses the detected operating-system package manager when a safe update command is available.",
        ),
    ]
    if selected is not None:
        tools = [tool for tool in tools if tool["name"] in selected]
    return {
        "ok": True,
        "executes_changes": False,
        "selected_tools": [tool["name"] for tool in tools],
        "tools": tools,
    }


def _update_autoreview() -> dict[str, Any]:
    git = shutil.which("git")
    if not git:
        return {"ok": False, "name": "autoreview", "error": "git is required to update AUTOREVIEW"}
    destination = Path.home() / ".agents" / "skills" / "autoreview"
    with tempfile.TemporaryDirectory(prefix="manageroo-autoreview-update-") as temp:
        checkout = Path(temp) / "agent-skills"
        clone = _run([git, "clone", "--depth", "1", AUTOREVIEW_REPO, str(checkout)], cwd=Path(temp))
        if not clone["ok"]:
            return {"name": "autoreview", **clone}
        source = checkout / "skills" / "autoreview"
        if not (source / "SKILL.md").is_file():
            return {"ok": False, "name": "autoreview", "error": "canonical autoreview skill was not found"}
        if any(path.is_symlink() for path in source.rglob("*")):
            return {"ok": False, "name": "autoreview", "error": "canonical autoreview tree contains symlinks"}
        backup = None
        if destination.exists():
            backup = destination.with_name(destination.name + ".manageroo-backup")
            if backup.exists():
                shutil.rmtree(backup)
            shutil.move(str(destination), str(backup))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        return {
            "ok": True,
            "name": "autoreview",
            "path": str(destination),
            "backup": str(backup) if backup else None,
        }


def apply_stack_updates(only: Iterable[str] | None = None) -> dict[str, Any]:
    plan = stack_update_plan(only)
    results: list[dict[str, Any]] = []
    for tool in plan["tools"]:
        if tool["name"] == "autoreview":
            if tool["installed"]:
                results.append(_update_autoreview())
            else:
                results.append({"name": "autoreview", "ok": True, "skipped": True, "reason": "not installed"})
            continue
        commands = tool.get("commands", [])
        if not commands:
            results.append({
                "name": tool["name"],
                "ok": True,
                "skipped": True,
                "reason": "no safe automatic update command for the detected installation",
            })
            continue
        command_results = [_run(list(command)) for command in commands]
        results.append({
            "name": tool["name"],
            "ok": all(item.get("ok") for item in command_results),
            "commands": command_results,
        })
    return {
        "ok": all(item.get("ok") for item in results),
        "executes_changes": True,
        "selected_tools": plan.get("selected_tools", []),
        "results": results,
    }


def format_stack_update(report: dict[str, Any]) -> str:
    if report.get("executes_changes"):
        lines = ["STACK UPDATE RESULTS", ""]
        for item in report.get("results", []):
            label = "OK" if item.get("ok") else "FAIL"
            if item.get("skipped"):
                label = "SKIP"
            lines.append(f"- {label} {item.get('name')}: {item.get('reason', '')}".rstrip())
        return "\n".join(lines) + "\n"
    lines = ["STACK UPDATE PLAN", "", "No changes were made. Pass --apply to execute supported updates.", ""]
    for item in report.get("tools", []):
        state = "installed" if item.get("installed") else "not detected"
        lines.append(f"- {item['name']}: {state}")
        if item.get("note"):
            lines.append(f"  {item['note']}")
        for command in item.get("commands", []):
            lines.append("  update: " + " ".join(command))
    return "\n".join(lines) + "\n"
