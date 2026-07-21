from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Iterable

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .project import git_root


DEFAULT_DISCOVERY_SUBPATHS = (
    Path("Documents") / "GitHub",
    Path("GitHub"),
    Path("Projects"),
    Path("src"),
)


def default_project_roots(*, home: Path | None = None, cwd: Path | None = None) -> list[Path]:
    """Return bounded default discovery roots without recursively scanning the whole home directory."""
    home = (home or Path.home()).expanduser().resolve()
    cwd = (cwd or Path.cwd()).expanduser().resolve()
    candidates: list[Path] = []
    if cwd != home:
        candidates.append(cwd)
    candidates.extend(home / relative for relative in DEFAULT_DISCOVERY_SUBPATHS)
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        path = candidate.expanduser().resolve()
        if path == home or path in seen or not path.is_dir():
            continue
        seen.add(path)
        roots.append(path)
    return roots


def _candidate_roots(roots: Iterable[Path] | None = None) -> list[Path]:
    selected = list(roots) if roots is not None else default_project_roots()
    seen: set[Path] = set()
    result: list[Path] = []
    for root in selected:
        path = root.expanduser().resolve()
        if path in seen or not path.is_dir():
            continue
        seen.add(path)
        result.append(path)
    return result


def _project_record(path: Path, agent: str | None = None) -> dict:
    path = path.expanduser().resolve()
    initialized = (path / PROJECT_DIR).is_dir()
    if initialized:
        status = "initialized"
        next_command = shlex.join([PUBLIC_COMMAND, "next", str(path)])
    else:
        status = "git repo"
        command = [PUBLIC_COMMAND, "solo", str(path)]
        if agent:
            command.extend(["--agent", agent])
        next_command = shlex.join(command)
    return {
        "name": path.name,
        "path": str(path),
        "status": status,
        "manageroo_configured": (path / PROJECT_DIR / "config.toml").is_file(),
        "product_brief_present": (path / PROJECT_DIR / "PRODUCT-BRIEF.md").is_file(),
        "next_command": next_command,
    }


def discover_projects(
    roots: Iterable[Path] | None = None,
    *,
    limit: int = 40,
    max_depth: int = 4,
    agent: str | None = None,
) -> dict:
    discovered: dict[Path, dict] = {}
    selected_roots = _candidate_roots(roots)
    bounded_limit = max(0, int(limit))
    for root in selected_roots:
        root_depth = len(root.parts)
        for current, dirs, _files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - root_depth
            if depth >= max_depth:
                dirs[:] = []
            if ".git" not in dirs:
                continue
            try:
                repo = git_root(current_path)
            except Exception:
                repo = current_path.resolve()
            discovered.setdefault(repo, _project_record(repo, agent=agent))
            dirs[:] = [name for name in dirs if name != ".git"]
            if bounded_limit and len(discovered) >= bounded_limit:
                break
        if bounded_limit and len(discovered) >= bounded_limit:
            break
    projects = sorted(discovered.values(), key=lambda item: (item["name"].casefold(), item["path"]))
    if bounded_limit:
        projects = projects[:bounded_limit]
    return {
        "ok": True,
        "roots": [str(path) for path in selected_roots],
        "projects": projects,
        "count": len(projects),
        "limit": bounded_limit,
    }


def format_project_discovery(report: dict) -> str:
    projects = list(report.get("projects", []) or [])
    lines = ["PROJECT PICKER", "", f"Found {len(projects)} project folder(s)."]
    for index, project in enumerate(projects, start=1):
        lines.extend(
            [
                "",
                f"[ ] {index}. {project['name']}",
                f"    Path: {project['path']}",
                f"    Status: {project['status']}",
                f"    Next: {project['next_command']}",
            ]
        )
    lines.extend(
        [
            "",
            "New project:",
            f"  {PUBLIC_COMMAND} solo /path/to/new-project --create",
            "",
            "Not listed? Paste another existing Git project path, or a missing/empty folder for a new project.",
            "",
        ]
    )
    return "\n".join(lines)


def format_project_add_checklist(report: dict) -> str:
    projects = list(report.get("projects", []) or [])
    lines = ["PROJECT SETUP CHECKLIST", "", "Pick the projects Manageroo should initialize:"]
    for index, project in enumerate(projects, start=1):
        lines.extend(
            [
                f"[ ] {index}. {project['name']}",
                f"    Path: {project['path']}",
                f"    Status: {project['status']}",
            ]
        )
    if not projects:
        lines.append("[ ] No discovered projects. Add a folder path manually when prompted.")
    lines.append("")
    return "\n".join(lines)


def selected_project_paths(report: dict, answer: str) -> list[Path]:
    answer = answer.strip().lower()
    if not answer or answer in {"none", "skip", "no", "n"}:
        return []
    projects = list(report.get("projects", []) or [])
    if answer in {"all", "*"}:
        return [Path(project["path"]).expanduser().resolve() for project in projects]
    indexes: list[int] = []
    for token in answer.replace(",", " ").split():
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"Invalid project selection: {token}")
            start = int(start_text)
            end = int(end_text)
            if start > end:
                start, end = end, start
            indexes.extend(range(start, end + 1))
            continue
        if not token.isdigit():
            raise ValueError(f"Invalid project selection: {token}")
        indexes.append(int(token))
    selected: list[Path] = []
    seen: set[Path] = set()
    for index in indexes:
        if index < 1 or index > len(projects):
            raise ValueError(f"Project number {index} is outside the displayed list.")
        path = Path(projects[index - 1]["path"]).expanduser().resolve()
        if path not in seen:
            seen.add(path)
            selected.append(path)
    return selected


def selected_project_command(report: dict, answer: str) -> str | None:
    answer = answer.strip()
    if not answer:
        return None
    projects = list(report.get("projects", []) or [])
    if answer.isdigit():
        index = int(answer)
        if index < 1 or index > len(projects):
            raise ValueError(f"Project number {index} is outside the displayed list.")
        return str(projects[index - 1]["next_command"])
    path = Path(answer).expanduser().resolve()
    if (path / ".git").exists():
        return _project_record(path, agent=None)["next_command"]
    return shlex.join([PUBLIC_COMMAND, "solo", str(path), "--create"])
