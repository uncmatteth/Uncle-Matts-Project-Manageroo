from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


GBRAIN_REFERENCE = "https://github.com/garrytan/gbrain"
GBRAIN_COMMIT = "3cc34c92eec2540ef36d2513eff8d4e4bf73bad9"
GITNEXUS_REFERENCE = "https://github.com/abhigyanpatwari/GitNexus"
GITNEXUS_PACKAGE = "gitnexus@1.6.9"
AUTOREVIEW_REPO = "https://github.com/openclaw/agent-skills.git"
AUTOREVIEW_COMMIT = "c4ab5e7f999cf504890986322473d3e7afd373af"
AUTOREVIEW_REFERENCE = (
    "https://github.com/openclaw/agent-skills/tree/"
    f"{AUTOREVIEW_COMMIT}/skills/autoreview"
)
CLAWPATCH_PACKAGE = "clawpatch@0.7.1"
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


def _tool(
    name: str,
    installed: bool,
    commands: list[list[str]],
    reference: str,
    note: str = "",
    **extra: Any,
) -> dict:
    return {
        "name": name,
        "installed": installed,
        "commands": commands,
        "reference": reference,
        "note": note,
        **extra,
    }


def _normalize_only(only: Iterable[str] | None) -> set[str] | None:
    if only is None:
        return None
    selected = {str(name).strip().lower() for name in only if str(name).strip()}
    unknown = selected - set(STACK_TOOL_NAMES)
    if unknown:
        raise ValueError(f"Unknown stack tool(s): {', '.join(sorted(unknown))}")
    return selected


def _autoreview_installations() -> list[Path]:
    candidates = [
        Path.home() / ".agents" / "skills" / "autoreview",
        Path.home() / ".codex" / "skills" / "autoreview",
    ]
    resolved: list[Path] = []
    for path in candidates:
        if not (path / "SKILL.md").is_file():
            continue
        try:
            target = path.resolve(strict=True)
        except OSError:
            continue
        if target not in resolved:
            resolved.append(target)
    return resolved


def _pinned_package_commands(
    *,
    executable: str | None,
    npm: str | None,
    pnpm: str | None,
    package: str,
) -> list[list[str]]:
    """Return deterministic update commands for an already-detected CLI.

    PATH discovery is the installation boundary for npm/pnpm-managed CLIs. Ownership
    probes are intentionally not required here: they made dry-run planning dependent on
    host-specific package-manager output and could suppress a valid pinned update.
    """
    if not executable:
        return []
    if npm:
        return [[npm, "install", "-g", package]]
    if pnpm:
        return [[pnpm, "add", "-g", package]]
    return []


def _obsidian_update_commands(obsidian: str | None) -> tuple[list[list[str]], str]:
    if not obsidian:
        return [], "Obsidian was not detected."
    system = platform.system().lower()
    if system == "windows" and shutil.which("winget"):
        return [[
            shutil.which("winget") or "winget",
            "upgrade",
            "--id",
            "Obsidian.Obsidian",
            "-e",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]], "Detected Windows installation; using the Obsidian Winget package id."
    if system == "darwin" and shutil.which("brew"):
        probe = _run([shutil.which("brew") or "brew", "list", "--cask", "obsidian"], timeout=30)
        if probe.get("ok"):
            return [[shutil.which("brew") or "brew", "upgrade", "--cask", "obsidian"]], "Homebrew owns the detected Obsidian installation."
        return [], "Could not prove that Homebrew owns the detected Obsidian installation."
    if system == "linux":
        flatpak = shutil.which("flatpak")
        snap = shutil.which("snap")
        normalized = str(obsidian).replace("\\", "/").lower()
        # The resolved executable path is strong ownership evidence for a Snap install.
        if snap and (normalized.startswith("/snap/") or "/snap/bin/" in normalized):
            return [[snap, "refresh", "obsidian"]], "Detected Snap-owned Obsidian installation."
        if flatpak:
            probe = _run([flatpak, "info", "--user", "md.obsidian.Obsidian"], timeout=30)
            if probe.get("ok"):
                return [[flatpak, "update", "--user", "-y", "md.obsidian.Obsidian"]], "Flatpak owns the detected Obsidian installation."
        if snap:
            probe = _run([snap, "list", "obsidian"], timeout=30)
            if probe.get("ok"):
                return [[snap, "refresh", "obsidian"]], "Snap owns the detected Obsidian installation."
        return [], "Could not safely identify which Linux package manager owns the detected Obsidian installation."
    return [], "No supported automatic update lane was identified for the detected Obsidian installation."


def stack_update_plan(only: Iterable[str] | None = None) -> dict[str, Any]:
    selected = _normalize_only(only)
    gbrain = shutil.which("gbrain")
    npm = shutil.which("npm")
    gitnexus = shutil.which("gitnexus")
    pnpm = shutil.which("pnpm")
    clawpatch = shutil.which("clawpatch")
    obsidian = shutil.which("obsidian")
    autoreview_paths = _autoreview_installations()

    gitnexus_commands = _pinned_package_commands(
        executable=gitnexus,
        npm=npm,
        pnpm=pnpm,
        package=GITNEXUS_PACKAGE,
    )
    gitnexus_note = (
        f"Updates only to the Manageroo-release pin {GITNEXUS_PACKAGE}. "
        "Repository indexing remains project-specific and is performed with `gitnexus analyze` from a target repo."
    )
    if not gitnexus:
        gitnexus_note += " No persistent GitNexus installation was detected, so stack-update will not install one implicitly."

    clawpatch_commands = _pinned_package_commands(
        executable=clawpatch,
        npm=None,
        pnpm=pnpm,
        package=CLAWPATCH_PACKAGE,
    )
    if clawpatch_commands and clawpatch:
        clawpatch_commands.append([clawpatch, "doctor"])

    obsidian_commands, obsidian_note = _obsidian_update_commands(obsidian)

    tools = [
        _tool(
            "gbrain",
            bool(gbrain),
            [[gbrain, "doctor", "--json"]] if gbrain else [],
            GBRAIN_REFERENCE,
            (
                "Manageroo does not run GBrain's mutable self-upgrade command. "
                f"The installer pin for this Manageroo release is commit {GBRAIN_COMMIT}; stack-update only verifies the existing installation."
            ),
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
            bool(autoreview_paths),
            [],
            AUTOREVIEW_REFERENCE,
            (
                f"Updates each unique resolved AUTOREVIEW installation from pinned commit {AUTOREVIEW_COMMIT}. "
                "Skill-root symlinks remain symlinks and aliases to the same target are updated only once."
            ),
            install_paths=[str(path) for path in autoreview_paths],
        ),
        _tool(
            "clawpatch",
            bool(clawpatch),
            clawpatch_commands,
            CLAWPATCH_REFERENCE,
            f"Updates only to the Manageroo-release pin {CLAWPATCH_PACKAGE} and reruns `clawpatch doctor`.",
        ),
        _tool(
            "obsidian",
            bool(obsidian),
            obsidian_commands,
            OBSIDIAN_REFERENCE,
            obsidian_note,
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


def _unique_backup(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}-{index}")
        index += 1
    return candidate


def _replace_autoreview(source: Path, destination: Path) -> dict[str, Any]:
    destination = destination.expanduser()
    if destination.is_symlink():
        return {
            "ok": False,
            "name": "autoreview",
            "path": str(destination),
            "error": "Refusing to replace a symlink alias directly; update its resolved target instead.",
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(destination.name + ".manageroo-stage")
    if stage.exists():
        shutil.rmtree(stage)
    backup: Path | None = None
    try:
        shutil.copytree(source, stage)
        if destination.exists():
            backup = _unique_backup(destination)
            destination.rename(backup)
        stage.rename(destination)
        return {
            "ok": True,
            "name": "autoreview",
            "path": str(destination),
            "backup": str(backup) if backup else None,
        }
    except Exception as exc:
        try:
            if stage.exists():
                shutil.rmtree(stage)
            if backup and backup.exists() and not destination.exists():
                backup.rename(destination)
        except OSError as rollback_exc:
            return {
                "ok": False,
                "name": "autoreview",
                "path": str(destination),
                "error": f"update failed: {exc}; rollback failed: {rollback_exc}",
            }
        return {
            "ok": False,
            "name": "autoreview",
            "path": str(destination),
            "error": f"update failed and original installation was preserved: {exc}",
        }


def _update_autoreview(destinations: Iterable[Path]) -> dict[str, Any]:
    targets: list[Path] = []
    for path in destinations:
        target = Path(path).expanduser().resolve()
        if target not in targets:
            targets.append(target)
    if not targets:
        return {"ok": True, "name": "autoreview", "skipped": True, "reason": "not installed"}
    git = shutil.which("git")
    if not git:
        return {"ok": False, "name": "autoreview", "error": "git is required to update AUTOREVIEW"}
    with tempfile.TemporaryDirectory(prefix="manageroo-autoreview-update-") as temp:
        checkout = Path(temp) / "agent-skills"
        clone = _run([git, "clone", "--no-checkout", AUTOREVIEW_REPO, str(checkout)], cwd=Path(temp))
        if not clone["ok"]:
            return {"name": "autoreview", **clone}
        checkout_result = _run([git, "checkout", "--detach", AUTOREVIEW_COMMIT], cwd=checkout)
        if not checkout_result["ok"]:
            return {"name": "autoreview", **checkout_result}
        resolved = _run([git, "rev-parse", "HEAD"], cwd=checkout)
        if not resolved["ok"] or resolved.get("output", "").strip().lower() != AUTOREVIEW_COMMIT.lower():
            return {
                "ok": False,
                "name": "autoreview",
                "error": "pinned AUTOREVIEW commit verification failed",
            }
        source = checkout / "skills" / "autoreview"
        if not (source / "SKILL.md").is_file():
            return {"ok": False, "name": "autoreview", "error": "pinned autoreview skill was not found"}
        if source.is_symlink() or any(path.is_symlink() for path in source.rglob("*")):
            return {"ok": False, "name": "autoreview", "error": "pinned autoreview tree contains symlinks"}
        results = [_replace_autoreview(source, destination) for destination in targets]
        return {
            "ok": all(item.get("ok") for item in results),
            "name": "autoreview",
            "pinned_commit": AUTOREVIEW_COMMIT,
            "installations": results,
        }


def apply_stack_updates(only: Iterable[str] | None = None) -> dict[str, Any]:
    plan = stack_update_plan(only)
    results: list[dict[str, Any]] = []
    for tool in plan["tools"]:
        if tool["name"] == "autoreview":
            results.append(_update_autoreview(Path(path) for path in tool.get("install_paths", [])))
            continue
        commands = tool.get("commands", [])
        if not commands:
            results.append(
                {
                    "name": tool["name"],
                    "ok": True,
                    "skipped": True,
                    "reason": "no safe automatic update command for the detected installation",
                }
            )
            continue
        command_results = [_run(list(command)) for command in commands]
        results.append(
            {
                "name": tool["name"],
                "ok": all(item.get("ok") for item in command_results),
                "commands": command_results,
            }
        )
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
        for path in item.get("install_paths", []):
            lines.append(f"  path: {path}")
        for command in item.get("commands", []):
            lines.append("  update: " + " ".join(command))
    return "\n".join(lines) + "\n"