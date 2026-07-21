from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Iterable

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .project import git_root


DEFAULT_DISCOVERY_ROOTS = (
    Path.home() / "Documents" / "GitHub",
    Path.home() / "GitHub",
    Path.home() / "Projects",
    Path.home() / "src",
)


def _candidate_roots(roots: Iterable[Path] | None = None) -> list[Path]:
    selected = list(roots or DEFAULT_DISCOVERY_ROOTS)
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
    configured = (path / PROJECT_DIR / "config.toml").is_file()
    brief = (path / PROJECT_DIR / "PRODUCT-BRIEF.md").is_file()
    if configured and brief:
        status = "manageroo-ready"
        next_command = shlex.join([PUBLIC_COMMAND, "next", "--repo", str(path)])
    elif configured:
        status = "manageroo-configured"
        next_command = shlex.join([PUBLIC_COMMAND, "solo", str(path)])
    else:
        status = "git-project"
        command = [PUBLIC_COMMAND, "solo", str(path)]
        if agent:
            command.extend(["--agent", agent])
        next_command = shlex.join(command)
    return {
        "name": path.name,
        "path": str(path),
        "status": status,
        "manageroo_configured": configured,
        "product_brief_present": brief,
        "next_command": next_command,
    }


def discover_projects(
    roots: Iterable[Path] | None = None,
    *,
    max_depth: int = 4,
    agent: str | None = None,
) -> dict:
    discovered: dict[Path, dict] = {}
    selected_roots = _candidate_roots(roots)
    for root in selected_roots:
        root_depth = len(root.parts)
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - root_depth
            if depth >= max_depth:
                dirs[:] = []
            if ".git" in dirs:
                try:
                    repo = git_root(current_path)
                except Exception:
                    repo = current_path.resolve()
                discovered.setdefault(repo, _project_record(repo, agent=agent))
                dirs[:] = [name for name in dirs if name != ".git"]
    projects = sorted(discovered.values(), key=lambda item: (item["name"].lower(), item["path"]))
    return {
        "ok": True,
        "roots": [str(path) for path in selected_roots],
        "projects": projects,
        "count": len(projects),
    }


def format_project_discovery(report: dict) -> str:
    lines = [
        "MANAGEROO PROJECT DISCOVERY",
        "",
        "Roots checked:",
    ]
    for root in report.get("roots", []):
        lines.append(f"  - {root}")
    projects = report.get("projects", [])
    lines.extend(["", f"Found {len(projects)} project folder(s)."])
    for index, project in enumerate(projects, start=1):
        lines.extend(["", f"[ ] {index}. {project['name']}", f"    Path: {project['path']}", f"    Status: {project['status']}"])
    lines.extend([
        "",
        "Not listed?",
        "  Paste another existing Git project path, or a missing/empty folder for a new project, when asked.",
        "",
        "Run later:",
        f"  {shlex.join([PUBLIC_COMMAND, 'projects', '--add'])}",
    ])
    return "\n".join(lines) + "\n"


def selected_project_paths(report: dict, answer: str) -> list[Path]:
    answer = answer.strip().lower()
    if not answer or answer in {"none", "skip", "no", "n"}:
        return []
    projects = report.get("projects", [])
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
    projects = report.get("projects", [])
    if answer.isdigit():
        index = int(answer)
        if index < 1 or index > len(projects):
            raise ValueError(f"Project number {index} is outside the displayed list.")
        return projects[index - 1]["next_command"]
    path = Path(answer).expanduser().resolve()
    if (path / ".git").exists():
        return _project_record(path, agent=None)["next_command"]
    return shlex.join([PUBLIC_COMMAND, "solo", str(path), "--create"])
