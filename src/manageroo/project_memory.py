from __future__ import annotations

from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR
from .util import atomic_write_text, utc_now

PROJECT_MEMORY_FILENAME = "PROJECT-MEMORY.md"


def project_memory_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / PROJECT_MEMORY_FILENAME


def _clean(value: str) -> str:
    return " ".join(str(value).strip().split())


def _clean_items(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return [item for item in (_clean(value) for value in (values or [])) if item]


def _bullets(values: list[str], fallback: str) -> list[str]:
    items = values or [fallback]
    return [f"- {item}" for item in items]


def _readme_summary(repo: Path) -> str:
    readme = repo / "README.md"
    if not readme.exists():
        return ""
    lines = [
        line.strip().lstrip("#").strip()
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if not lines:
        return ""
    return " - ".join(lines[:2])


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
        "# Project Memory",
        "",
        "This is the repo-local continuity file for humans and AI agents.",
        "Read it before broad product work. Keep it short and update it after meaningful releases.",
        "",
        "## What This Project Is",
        "",
        *_bullets([summary], "Describe what this project is for."),
        "",
        "## What Has Shipped",
        "",
        *_bullets(shipped_items, "Nothing shipped through MANAGEROO yet."),
        "",
        "## What Must Not Break",
        "",
        *_bullets(must_not_items, "Add product promises, workflows, files, or behaviors that must stay intact."),
        "",
        "## Current Proof",
        "",
        *_bullets(proof_items, "Add the commands or manual checks that prove the current state."),
        "",
        "## Operator Notes",
        "",
        *_bullets(note_items, f"Created by MANAGEROO on {utc_now()}."),
        "",
    ]
    return "\n".join(lines)


def _append_items(text: str, heading: str, values: list[str]) -> tuple[str, bool]:
    cleaned = _clean_items(values)
    if not cleaned:
        return text, False
    marker = f"## {heading}"
    if marker not in text:
        addition = ["", marker, "", *[f"- {item}" for item in cleaned], ""]
        return text.rstrip() + "\n" + "\n".join(addition), True
    start = text.index(marker) + len(marker)
    next_heading = text.find("\n## ", start)
    insert_at = len(text.rstrip()) if next_heading == -1 else next_heading
    section = text[start:insert_at]
    existing = {line.strip() for line in section.splitlines()}
    new_lines = [f"- {item}" for item in cleaned if f"- {item}" not in existing]
    if not new_lines:
        return text, False
    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:]
    return prefix + "\n" + "\n".join(new_lines) + ("\n" if suffix else "\n") + suffix.lstrip("\n"), True


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
    created = not path.exists()
    updated_sections: list[str] = []
    if created:
        markdown = build_project_memory(
            repo,
            project_summary=project_summary,
            shipped=shipped,
            must_not=must_not,
            proof=proof,
            notes=notes,
        )
        atomic_write_text(path, markdown)
        updated_sections = [
            "What This Project Is",
            "What Has Shipped",
            "What Must Not Break",
            "Current Proof",
            "Operator Notes",
        ]
    else:
        markdown = path.read_text(encoding="utf-8", errors="replace")
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
        "content": path.read_text(encoding="utf-8", errors="replace"),
    }


def read_project_memory(repo: Path) -> dict[str, Any]:
    path = project_memory_path(repo)
    if not path.exists():
        return {"ok": False, "path": str(path), "content": "", "next_command": "manageroo memory init"}
    return {"ok": True, "path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")}


def format_project_memory(report: dict[str, Any]) -> str:
    if report.get("content"):
        return f"PROJECT MEMORY\nPath: {report['path']}\n\n{report['content']}"
    lines = [
        "PROJECT MEMORY",
        f"Path: {report['path']}",
        f"Created: {'yes' if report.get('created') else 'no'}",
    ]
    updated = report.get("updated_sections") or []
    lines.append("Updated: " + (", ".join(updated) if updated else "nothing changed"))
    return "\n".join(lines) + "\n"
