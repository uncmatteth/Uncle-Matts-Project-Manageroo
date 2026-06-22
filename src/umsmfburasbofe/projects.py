from __future__ import annotations

from pathlib import Path

from .branding import PUBLIC_COMMAND

SKIP_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".next",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "site-packages",
    "vendor",
    "venv",
}


def default_project_roots(*, home: Path | None = None, cwd: Path | None = None) -> list[Path]:
    home = (home or Path.home()).expanduser()
    cwd = (cwd or Path.cwd()).expanduser()
    candidates = []
    if cwd.resolve() != home.resolve():
        candidates.append(cwd)
    candidates.extend(
        [
            home / "Documents" / "GitHub",
            home / "Projects",
            home / "Developer",
        ]
    )
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _iter_project_dirs(root: Path, *, max_depth: int) -> list[Path]:
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    found: list[Path] = []
    stack = [(root, 0)]
    seen: set[Path] = set()
    while stack:
        current, depth = stack.pop()
        try:
            resolved = current.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / ".git").exists():
            found.append(resolved)
            continue
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in reversed(children):
            if not child.is_dir():
                continue
            if child.name in SKIP_DIRS:
                continue
            if child.name.startswith(".") and child.name != ".umsmfburasbofe":
                continue
            stack.append((child, depth + 1))
    return found


def _project_record(path: Path, *, agent: str | None) -> dict:
    initialized = (path / ".umsmfburasbofe").is_dir()
    command = f"{PUBLIC_COMMAND} {'next' if initialized else 'solo'} {path}"
    if agent and not initialized:
        command += f" --agent {agent}"
    return {
        "name": path.name,
        "path": str(path),
        "status": "initialized" if initialized else "git repo",
        "initialized": initialized,
        "next_command": command,
    }


def discover_projects(
    *,
    roots: list[Path] | None = None,
    limit: int = 40,
    max_depth: int = 4,
    agent: str | None = None,
) -> dict:
    selected_roots = roots or default_project_roots()
    projects: list[dict] = []
    seen: set[Path] = set()
    for root in selected_roots:
        for project_dir in _iter_project_dirs(root, max_depth=max_depth):
            if project_dir in seen:
                continue
            seen.add(project_dir)
            projects.append(_project_record(project_dir, agent=agent))
    projects.sort(key=lambda item: (item["status"] != "initialized", item["name"].lower(), item["path"]))
    if limit > 0:
        projects = projects[:limit]
    return {
        "ok": True,
        "roots": [str(root.expanduser().resolve()) for root in selected_roots],
        "count": len(projects),
        "projects": projects,
        "new_project_command": f"{PUBLIC_COMMAND} solo /path/to/new-project --create",
    }


def format_project_discovery(report: dict) -> str:
    lines = [
        "PROJECT PICKER",
        "",
        "This is read-only. Pick a repo, then run the printed command.",
        "",
        "Roots checked:",
    ]
    for root in report.get("roots", []):
        lines.append(f"  - {root}")
    projects = report.get("projects", [])
    lines.extend(["", f"Found {len(projects)} project folder(s)."])
    for index, project in enumerate(projects, start=1):
        lines.extend(
            [
                "",
                f"{index}. {project['name']}",
                f"   Path: {project['path']}",
                f"   Status: {project['status']}",
                f"   Next: {project['next_command']}",
            ]
        )
    lines.extend(
        [
            "",
            "New project:",
            f"  {report.get('new_project_command', f'{PUBLIC_COMMAND} solo /path/to/new-project --create')}",
            "",
            "Guided picker:",
            f"  {PUBLIC_COMMAND} projects --pick",
        ]
    )
    return "\n".join(lines) + "\n"


def format_project_add_checklist(report: dict) -> str:
    lines = [
        "PROJECT SETUP CHECKLIST",
        "",
        "This is bounded and explicit. Pick only the projects you want to add.",
        "Type numbers separated by commas, a range like 1-3, all, or press Enter to skip discovered projects.",
        "",
        "Roots checked:",
    ]
    for root in report.get("roots", []):
        lines.append(f"  - {root}")
    projects = report.get("projects", [])
    lines.extend(["", f"Found {len(projects)} project folder(s)."])
    for index, project in enumerate(projects, start=1):
        lines.extend(
            [
                "",
                f"[ ] {index}. {project['name']}",
                f"    Path: {project['path']}",
                f"    Status: {project['status']}",
            ]
        )
    lines.extend(
        [
            "",
            "Not listed?",
            "  Paste another existing Git project path, or a missing/empty folder for a new project, when asked.",
            "",
            "Run later:",
            f"  {PUBLIC_COMMAND} projects --add",
        ]
    )
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
        if 1 <= index <= len(projects):
            return projects[index - 1]["next_command"]
    path = Path(answer).expanduser().resolve()
    if (path / ".git").exists():
        return _project_record(path, agent=None)["next_command"]
    return f"{PUBLIC_COMMAND} solo {path} --create"
