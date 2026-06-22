from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .branding import PUBLIC_COMMAND
from .token_modes import token_mode_skills_dir
from .util import sha256_file


_VALID_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}[A-Za-z0-9]$|^[A-Za-z0-9]$")


def _backup_path(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = destination.with_name(f"{destination.name}.umsmfburasbofe-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = destination.with_name(
            f"{destination.name}.umsmfburasbofe-backup-{stamp}-{index}"
        )
        index += 1
    return candidate


def _frontmatter_name(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    for line in text[4:end].splitlines():
        if line.strip().startswith("name:"):
            raw = line.split(":", 1)[1].strip().strip("'\"")
            return raw
    return ""


def _skill_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return _frontmatter_name(text) or path.parent.name


def _candidate(path: Path, source_root: Path, target_root: Path, seen: set[str]) -> dict[str, Any]:
    name = _skill_name(path).strip()
    status = "importable"
    reason = "ready to import"
    existing = target_root / name / "SKILL.md"
    digest = sha256_file(path)
    if not _VALID_SKILL_NAME.fullmatch(name):
        status = "invalid"
        reason = "skill name must use letters, digits, and hyphens"
    elif name in seen:
        status = "duplicate-source"
        reason = "another SKILL.md in this source folder uses the same skill name"
    elif existing.exists():
        if existing.is_symlink():
            status = "blocked"
            reason = "existing target SKILL.md is a symlink"
        elif sha256_file(existing) == digest:
            status = "already-present"
            reason = "same SKILL.md already installed"
        else:
            status = "conflict"
            reason = "different SKILL.md already exists; import will back it up"
    if status != "invalid":
        seen.add(name)
    return {
        "name": name,
        "path": str(path),
        "relative_path": str(path.relative_to(source_root)),
        "sha256": digest,
        "target": str(existing),
        "status": status,
        "reason": reason,
    }


def scan_skill_folder(source: Path, *, skills_dir: Path | None = None) -> dict[str, Any]:
    source_root = source.expanduser().resolve()
    if not source_root.exists():
        raise ValueError(f"Skill source folder does not exist: {source_root}")
    if not source_root.is_dir():
        raise ValueError(f"Skill source must be a folder: {source_root}")
    target_root = (skills_dir or token_mode_skills_dir()).expanduser().resolve()
    if target_root.exists() and target_root.is_symlink():
        raise ValueError(f"Refusing to use symlinked skills directory: {target_root}")

    seen: set[str] = set()
    candidates = [
        _candidate(path, source_root, target_root, seen)
        for path in sorted(source_root.rglob("SKILL.md"))
        if not path.is_symlink()
    ]
    counts: dict[str, int] = {}
    for item in candidates:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    importable_count = sum(
        1 for item in candidates if item["status"] in {"importable", "conflict"}
    )
    return {
        "ok": True,
        "source": str(source_root),
        "skills_dir": str(target_root),
        "candidate_count": len(candidates),
        "importable_count": importable_count,
        "counts": counts,
        "candidates": candidates,
        "next_command": (
            f"{PUBLIC_COMMAND} skills import {source_root} --apply"
            if importable_count
            else ""
        ),
    }


def import_skill_folder(
    source: Path,
    *,
    skills_dir: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    scan = scan_skill_folder(source, skills_dir=skills_dir)
    if not apply:
        return {
            **scan,
            "applied": False,
            "imported": [],
            "backups": [],
            "next_command": f"{PUBLIC_COMMAND} skills import {scan['source']} --apply",
        }

    target_root = Path(scan["skills_dir"])
    target_root.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, Any]] = []
    backups: list[str] = []
    for item in scan["candidates"]:
        if item["status"] not in {"importable", "conflict"}:
            continue
        source_file = Path(item["path"])
        skill_dir = target_root / item["name"]
        if skill_dir.is_symlink():
            raise ValueError(f"Refusing to import through symlinked skill directory: {skill_dir}")
        if skill_dir.exists() and not skill_dir.is_dir():
            raise ValueError(f"Refusing to import over non-directory skill path: {skill_dir}")
        skill_dir.mkdir(parents=True, exist_ok=True)
        target_file = skill_dir / "SKILL.md"
        if target_file.is_symlink():
            raise ValueError(f"Refusing to overwrite symlinked skill file: {target_file}")
        backup = ""
        if target_file.exists() and sha256_file(target_file) != item["sha256"]:
            backup_path = _backup_path(target_file)
            shutil.copy2(target_file, backup_path)
            backups.append(str(backup_path))
            backup = str(backup_path)
        shutil.copy2(source_file, target_file)
        imported.append(
            {
                "name": item["name"],
                "source": str(source_file),
                "target": str(target_file),
                "backup": backup,
            }
        )
    return {
        **scan,
        "applied": True,
        "imported": imported,
        "backups": backups,
        "next_command": "",
    }


def format_skill_scan(report: dict[str, Any], *, limit: int = 80) -> str:
    lines = [
        "SKILL FOLDER SCAN",
        f"Source: {report['source']}",
        f"Target: {report['skills_dir']}",
        (
            f"Found: {report['candidate_count']} SKILL.md file(s), "
            f"{report['importable_count']} importable or replaceable"
        ),
    ]
    if not report["candidates"]:
        lines.append("ACTION no SKILL.md files found")
    candidates = report["candidates"] if limit <= 0 else report["candidates"][:limit]
    for item in candidates:
        label = "OK" if item["status"] in {"importable", "already-present"} else "ACTION"
        if item["status"] == "duplicate-source":
            label = "SKIP"
        lines.append(f"{label} {item['name']}: {item['status']} - {item['reason']}")
    if limit > 0 and len(report["candidates"]) > limit:
        remaining = len(report["candidates"]) - limit
        lines.append(f"... {remaining} more. Use --limit 0 or --json for the full scan.")
    if report.get("next_command"):
        lines.append(f"Next: {report['next_command']}")
    return "\n".join(lines) + "\n"


def format_skill_import(report: dict[str, Any], *, limit: int = 80) -> str:
    if not report.get("applied"):
        return format_skill_scan(report, limit=limit)
    lines = [
        "SKILL IMPORT COMPLETE",
        f"Source: {report['source']}",
        f"Target: {report['skills_dir']}",
    ]
    if not report["imported"]:
        lines.append("OK nothing new to import")
    for item in report["imported"]:
        suffix = f" backup: {item['backup']}" if item.get("backup") else ""
        lines.append(f"OK {item['name']}: {item['target']}{suffix}")
    return "\n".join(lines) + "\n"
