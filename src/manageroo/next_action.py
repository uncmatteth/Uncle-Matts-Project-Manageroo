from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .errors import ConfigurationError
from .project import git_root
from .readiness import brief_is_template, readiness


DEFAULT_WANT = "Describe the first useful version"


def _command(argv: list[str]) -> str:
    return shlex.join(argv)


def _solo_setup_command(repo: Path, *, force: bool = False) -> str:
    argv = [PUBLIC_COMMAND, "solo", str(repo), "--want", DEFAULT_WANT]
    if force:
        argv.append("--force")
    return _command(argv)


def _create_command(path: Path) -> str:
    return _command([PUBLIC_COMMAND, "solo", str(path), "--create", "--want", DEFAULT_WANT])


def _run_command(repo: Path, *, mode: str, apply_on_success: bool) -> str:
    apply_flag = "--apply" if apply_on_success else "--no-apply"
    return _command([PUBLIC_COMMAND, "run", "--repo", str(repo), "--mode", mode, apply_flag])


def _git_init_command(path: Path) -> str:
    return _command(["git", "-C", str(path), "init", "-b", "main"])


def next_action(
    repo_path: Path,
    *,
    mode: str = "build",
    apply_on_success: bool = True,
) -> dict[str, Any]:
    requested = repo_path.expanduser().resolve()
    if not requested.exists():
        return {
            "ok": True,
            "stage": "needs-project",
            "repo": str(requested),
            "reason": "That path does not exist yet.",
            "command": _create_command(requested),
        }

    try:
        repo = git_root(requested)
    except ConfigurationError:
        if requested.is_dir() and not any(requested.iterdir()):
            command = _create_command(requested)
            reason = "That folder is empty and can become a new project repo."
        else:
            command = _git_init_command(requested)
            reason = "That path exists, but it is not a Git repository yet."
        return {
            "ok": True,
            "stage": "needs-git-repo",
            "repo": str(requested),
            "reason": reason,
            "command": command,
        }

    config_path = repo / PROJECT_DIR / "config.toml"
    brief_path = repo / PROJECT_DIR / "PRODUCT-BRIEF.md"
    memory_path = repo / PROJECT_DIR / "PROJECT-MEMORY.md"
    if not config_path.is_file():
        return {
            "ok": True,
            "stage": "needs-setup",
            "repo": str(repo),
            "reason": "This is a Git repo, but MANAGEROO has not set up its project files yet.",
            "command": _solo_setup_command(repo),
        }
    if not brief_path.is_file() or brief_is_template(brief_path):
        return {
            "ok": True,
            "stage": "needs-brief",
            "repo": str(repo),
            "reason": "The product brief is missing or still the starter template.",
            "command": _solo_setup_command(repo, force=True),
        }
    if not memory_path.is_file():
        return {
            "ok": True,
            "stage": "needs-project-memory",
            "repo": str(repo),
            "reason": "The repo-local project memory file is missing.",
            "command": _command([PUBLIC_COMMAND, "memory", "init", str(repo)]),
        }

    ready = readiness(repo)
    for item in ready.get("items", []):
        if item.get("required", True) and not item.get("ok"):
            return {
                "ok": True,
                "stage": f"needs-{item['name'].replace(' ', '-')}",
                "repo": str(repo),
                "reason": item.get("detail", "A required readiness item is missing."),
                "command": item.get("next") or _command([PUBLIC_COMMAND, "ready", str(repo)]),
                "readiness": ready,
            }

    return {
        "ok": True,
        "stage": "ready-to-run",
        "repo": str(repo),
        "reason": "Required readiness checks are green.",
        "command": _run_command(repo, mode=mode, apply_on_success=apply_on_success),
        "readiness": ready,
    }


def format_next_action(report: dict[str, Any]) -> str:
    return (
        "NEXT ACTION\n"
        f"Stage: {report['stage']}\n"
        f"Repo: {report['repo']}\n"
        f"Reason: {report['reason']}\n"
        "Command:\n"
        f"  {report['command']}\n"
    )
