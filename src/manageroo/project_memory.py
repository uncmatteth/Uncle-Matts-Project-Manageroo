from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR
from .util import atomic_write_text, utc_now

PROJECT_MEMORY_FILENAME = "PROJECT-MEMORY.md"
PLACEHOLDERS = {
    "What This Project Is": "- Describe what this project is for.",
    "What Has Shipped": "- Nothing shipped through MANAGEROO yet.",
    "What Must Not Break": "- Add product promises, workflows, files, or behaviors that must stay intact.",
    "Current Proof": "- Add the commands or manual checks that prove the current state.",
}


def project_memory_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / PROJECT_MEMORY_FILENAME


def _clean(value: str) -> str:
    return " ".join(str(value).strip().split())


def _clean_items(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return [item for item in (_clean(value) for value in (values or [])) if item]


def _bullets(values: list[str], fallback: str) -> list[str]:
    items = values or [fallback]
    return [f"- {item}" for item in items]


def _safe_repo_regular_file(repo: Path, path: Path, *, allow_missing: bool = False) -> Path | None:
    repo = repo.expanduser().resolve()
    lexical = path.expanduser()
    if lexical.is_symlink():
        raise ValueError(f"Refusing to read symlinked repository memory source: {lexical}")
    if not lexical.exists():
        return None if allow_missing else lexical
    if not lexical.is_file():
        raise ValueError(f"Repository memory source must be a regular file: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(repo)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Repository memory source escapes repository root: {lexical}") from exc
    return resolved


def _read_utf8(path: Path, *, repo: Path | None = None) -> str:
    target = _safe_repo_regular_file(repo, path) if repo is not None else path
    assert target is not None
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Refusing to rewrite non-UTF-8 project memory file: {path}. Convert it to UTF-8 first."
        ) from exc


def _readme_summary(repo: Path) -> str:
    readme = repo / "README.md"
    try:
        target = _safe_repo_regular_file(repo, readme, allow_missing=True)
    except ValueError:
        raise
    if target is None:
        return ""
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
    lines = [line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()]
    return " - ".join(lines[:2]) if lines else ""


def build_project_memory(
    repo: Path,
    *,
    project_summary: str = "",
    shipped: list[str] | None = None,
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
    notes: list[str] | None = None,
) -> str:
    summary = _clean(project_summary) or _readme_summary(repo) or "Describe what this project is for."
    shipped_items = _clean_items(shipped)
    must_not_items = _clean_items(must_not)
    proof_items = _clean_items(proof)
    note_items = _clean_items(notes)
    lines = [
        "# Project Memory", "",
        "This is the repo-local continuity file for humans and AI agents.",
        "Read it before broad product work. Keep it short and update it after meaningful releases.", "",
        "## What This Project Is", "", *_bullets([summary], "Describe what this project is for."), "",
        "## What Has Shipped", "", *_bullets(shipped_items, "Nothing shipped through MANAGEROO yet."), "",
        "## What Must Not Break", "", *_bullets(must_not_items, "Add product promises, workflows, files, or behaviors that must stay intact."), "",
        "## Current Proof", "", *_bullets(proof_items, "Add the commands or manual checks that prove the current state."), "",
        "## Operator Notes", "", *_bullets(note_items, f"Created by MANAGEROO on {utc_now()}."), "",
    ]
    return "\n".join(lines)


def _heading_match(text: str, heading: str) -> re.Match[str] | None:
    return re.search(rf"(?m)^## {re.escape(heading)}\s*$", text)


def _append_items(text: str, heading: str, values: list[str]) -> tuple[str, bool]:
    cleaned = _clean_items(values)
    if not cleaned:
        return text, False
    marker = f"## {heading}"
    match = _heading_match(text, heading)
    if match is None:
        addition = ["", marker, "", *[f"- {item}" for item in cleaned], ""]
        return text.rstrip() + "\n" + "\n".join(addition), True
    start = match.end()
    next_match = re.search(r"(?m)^## .+$", text[start:])
    insert_at = len(text.rstrip()) if next_match is None else start + next_match.start()
    section = text[start:insert_at]
    existing = {line.strip() for line in section.splitlines()}
    placeholder = PLACEHOLDERS.get(heading)
    section_changed = False
    if placeholder and placeholder in existing:
        filtered_lines = [line for line in section.splitlines() if line.strip() != placeholder]
        replacement = "\n".join(filtered_lines)
        text = text[:start] + replacement + text[insert_at:]
        next_match = re.search(r"(?m)^## .+$", text[start:])
        insert_at = len(text.rstrip()) if next_match is None else start + next_match.start()
        section = text[start:insert_at]
        existing = {line.strip() for line in section.splitlines()}
        section_changed = True
    new_lines = [f"- {item}" for item in cleaned if f"- {item}" not in existing]
    if not new_lines:
        return text, section_changed
    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:]
    return prefix + "\n" + "\n".join(new_lines) + "\n" + suffix.lstrip("\n"), True


def ensure_project_memory(
    repo: Path,
    *,
    project_summary: str = "",
    shipped: list[str] | None = None,
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    path = project_memory_path(repo)
    if path.is_symlink():
        raise ValueError(f"Refusing to rewrite symlinked project memory file: {path}")
    created = not path.exists()
    updated_sections: list[str] = []
    if created:
        markdown = build_project_memory(repo, project_summary=project_summary, shipped=shipped, must_not=must_not, proof=proof, notes=notes)
        atomic_write_text(path, markdown)
        updated_sections = ["What This Project Is", "What Has Shipped", "What Must Not Break", "Current Proof", "Operator Notes"]
    else:
        markdown = _read_utf8(path, repo=repo)
        updates = [
            ("What This Project Is", [project_summary] if _clean(project_summary) else []),
            ("What Has Shipped", shipped or []),
            ("What Must Not Break", must_not or []),
            ("Current Proof", proof or []),
            ("Operator Notes", notes or []),
        ]
        changed = False
        for heading, values in updates:
            markdown, section_changed = _append_items(markdown, heading, values)
            if section_changed:
                updated_sections.append(heading)
                changed = True
        if changed:
            atomic_write_text(path, markdown)
    return {
        "ok": True,
        "path": str(path),
        "created": created,
        "updated_sections": updated_sections,
        "content": _read_utf8(path, repo=repo),
    }


def read_project_memory(repo: Path) -> dict[str, Any]:
    path = project_memory_path(repo)
    if not path.exists() and not path.is_symlink():
        return {"ok": False, "path": str(path), "content": "", "next_command": "manageroo memory init"}
    try:
        content = _read_utf8(path, repo=repo)
    except ValueError as exc:
        return {"ok": False, "path": str(path), "content": "", "error": str(exc)}
    return {"ok": True, "path": str(path), "content": content}


def format_project_memory(report: dict[str, Any]) -> str:
    if report.get("content"):
        return f"PROJECT MEMORY\nPath: {report['path']}\n\n{report['content']}"
    lines = ["PROJECT MEMORY", f"Path: {report['path']}", f"Created: {'yes' if report.get('created') else 'no'}"]
    if report.get("error"):
        lines.append(f"Error: {report['error']}")
    updated = report.get("updated_sections") or []
    lines.append("Updated: " + (", ".join(updated) if updated else "nothing changed"))
    return "\n".join(lines) + "\n"
