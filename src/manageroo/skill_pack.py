from __future__ import annotations

import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .branding import PUBLIC_COMMAND
from .token_modes import CORE_HELPER_SKILLS, install_core_helper_skills, token_mode_skills_dir
from .util import sha256_file

_VALID_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}[A-Za-z0-9]$|^[A-Za-z0-9]$")


def _backup_path(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}-{index}")
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
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def _skill_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return _frontmatter_name(text) or path.parent.name


def _safe_target_root(skills_dir: Path | None, *, create: bool = False) -> Path:
    unresolved = (skills_dir or token_mode_skills_dir()).expanduser()
    if unresolved.is_symlink():
        raise ValueError(f"Refusing to use symlinked skills directory: {unresolved}")
    if create:
        unresolved.mkdir(parents=True, exist_ok=True)
    if unresolved.exists() and not unresolved.is_dir():
        raise ValueError(f"Skills target must be a directory: {unresolved}")
    resolved = unresolved.resolve()
    if unresolved.is_symlink():
        raise ValueError(f"Refusing to use symlinked skills directory: {unresolved}")
    return resolved


def _validate_source_tree(source_dir: Path) -> list[Path]:
    if source_dir.is_symlink():
        raise ValueError(f"Refusing to import from symlinked skill source directory: {source_dir}")
    files: list[Path] = []
    for path in source_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Refusing to copy symlinked skill content: {path}")
        if path.is_file():
            files.append(path)
    return files


def _validate_destination_tree(target_dir: Path, target_root: Path) -> None:
    try:
        target_dir.resolve(strict=False).relative_to(target_root)
    except ValueError as exc:
        raise ValueError(f"Skill target escapes approved skills root: {target_dir}") from exc
    current = target_dir
    while current != target_root:
        if current.is_symlink():
            raise ValueError(f"Refusing to import through symlinked skill destination: {current}")
        current = current.parent
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError(f"Refusing to import over non-directory skill path: {target_dir}")
    if target_dir.exists():
        for path in target_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError(f"Refusing to replace skill tree containing symlink: {path}")


def _transactional_replace_skill(source_dir: Path, target_dir: Path, target_root: Path) -> str:
    """Stage a complete skill and swap it atomically at directory granularity."""
    source_files = _validate_source_tree(source_dir)
    _validate_destination_tree(target_dir, target_root)
    stage = target_root / f".{target_dir.name}.manageroo-stage"
    if stage.exists() or stage.is_symlink():
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        else:
            stage.unlink()
    backup: Path | None = None
    try:
        stage.mkdir(parents=False, exist_ok=False)
        for source_file in source_files:
            relative = source_file.relative_to(source_dir)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
        if not (stage / "SKILL.md").is_file():
            raise ValueError(f"Staged skill is missing SKILL.md: {source_dir}")
        if target_dir.exists():
            backup = _backup_path(target_dir)
            target_dir.rename(backup)
        stage.rename(target_dir)
        return str(backup) if backup else ""
    except Exception:
        try:
            if stage.exists() and stage.is_dir() and not stage.is_symlink():
                shutil.rmtree(stage)
            if backup and backup.exists() and not target_dir.exists():
                backup.rename(target_dir)
        except OSError:
            pass
        raise


def _candidate(path: Path, source_root: Path, target_root: Path, seen: set[str]) -> dict[str, Any]:
    name = _skill_name(path).strip()
    status = "importable"
    reason = "ready to import"
    skill_dir = target_root / name
    existing = skill_dir / "SKILL.md"
    digest = sha256_file(path)
    if not _VALID_SKILL_NAME.fullmatch(name):
        status = "invalid"
        reason = "skill name must use letters, digits, and hyphens"
    elif name in seen:
        status = "duplicate-source"
        reason = "another SKILL.md in this source folder uses the same skill name"
    elif skill_dir.is_symlink():
        status = "blocked"
        reason = "existing target skill directory is a symlink"
    elif existing.exists():
        if existing.is_symlink():
            status = "blocked"
            reason = "existing target SKILL.md is a symlink"
        elif sha256_file(existing) == digest:
            status = "already-present"
            reason = "same SKILL.md already installed"
        else:
            status = "conflict"
            reason = "different skill already exists; import will transactionally back up the complete old skill directory"
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
    unresolved_source = source.expanduser()
    if unresolved_source.is_symlink():
        raise ValueError(f"Refusing to scan symlinked skill source folder: {unresolved_source}")
    source_root = unresolved_source.resolve()
    if not source_root.exists():
        raise ValueError(f"Skill source folder does not exist: {source_root}")
    if not source_root.is_dir():
        raise ValueError(f"Skill source must be a folder: {source_root}")
    target_root = _safe_target_root(skills_dir)

    seen: set[str] = set()
    candidates = [
        _candidate(path, source_root, target_root, seen)
        for path in sorted(source_root.rglob("SKILL.md"))
        if not path.is_symlink()
    ]
    counts: dict[str, int] = {}
    for item in candidates:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    importable_count = sum(1 for item in candidates if item["status"] in {"importable", "conflict"})
    return {
        "ok": True,
        "source": str(source_root),
        "skills_dir": str(target_root),
        "candidate_count": len(candidates),
        "importable_count": importable_count,
        "counts": counts,
        "candidates": candidates,
        "next_command": shlex.join([PUBLIC_COMMAND, "skills", "import", str(source_root), "--apply"]) if importable_count else "",
    }


def default_skill_roots() -> list[Path]:
    roots = [Path.home() / ".agents" / "skills", Path.home() / ".codex" / "skills", Path.home() / "Downloads" / "SKILLS"]
    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        unresolved = root.expanduser()
        if unresolved.is_symlink():
            continue
        expanded = unresolved.resolve()
        if expanded in seen or not expanded.exists():
            continue
        seen.add(expanded)
        result.append(expanded)
    return result


def _all_skill_candidates(roots: list[Path], target_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists() or not root.is_dir() or root.is_symlink():
            continue
        seen: set[str] = set()
        for path in sorted(root.rglob("SKILL.md")):
            if path.is_symlink():
                continue
            item = _candidate(path, root.resolve(), target_root, seen)
            item["root"] = str(root.resolve())
            item["in_target"] = path.resolve().is_relative_to(target_root)
            candidates.append(item)
    return candidates


def reconcile_skill_pack(
    *,
    sources: list[Path] | None = None,
    skills_dir: Path | None = None,
    apply: bool = False,
    include_external: bool = False,
    scan_default_roots: bool = True,
) -> dict[str, Any]:
    target_root = _safe_target_root(skills_dir, create=apply)
    source_roots = default_skill_roots() if scan_default_roots else []
    for source in sources or []:
        unresolved = source.expanduser()
        if unresolved.is_symlink():
            raise ValueError(f"Refusing symlinked skill source root: {unresolved}")
        expanded = unresolved.resolve()
        if expanded not in source_roots:
            source_roots.append(expanded)

    installed = install_core_helper_skills(target_root) if apply else {}
    import_reports: list[dict[str, Any]] = []
    if apply and include_external:
        for source in source_roots:
            if source == target_root or not source.exists() or not source.is_dir():
                continue
            report = import_skill_folder(source, skills_dir=target_root, apply=True)
            report["source"] = str(source)
            import_reports.append(report)

    scan_roots = [target_root, *[root for root in source_roots if root != target_root]]
    candidates = _all_skill_candidates(scan_roots, target_root)
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_name.setdefault(item["name"], []).append(item)
    duplicate_names = {
        name: items for name, items in sorted(by_name.items())
        if len({item["sha256"] for item in items}) > 1 or len(items) > 1
    }
    missing_bundled = [name for name in sorted(CORE_HELPER_SKILLS) if not (target_root / name / "SKILL.md").exists()]
    return {
        "ok": not missing_bundled if apply else True,
        "applied": apply,
        "skills_dir": str(target_root),
        "source_roots": [str(root) for root in source_roots],
        "bundled_skill_count": len(CORE_HELPER_SKILLS),
        "installed_bundled": installed,
        "missing_bundled": missing_bundled,
        "duplicate_count": len(duplicate_names),
        "duplicates": duplicate_names,
        "external_imports": import_reports,
        "next_command": "" if apply else shlex.join([PUBLIC_COMMAND, "skills", "reconcile", "--apply"]),
        "note": (
            "Reconcile installs one active Manageroo-managed copy of each bundled skill under the target skills directory. "
            "It reports duplicate names in other agent skill roots instead of deleting outside directories."
        ),
    }


def import_skill_folder(source: Path, *, skills_dir: Path | None = None, apply: bool = False) -> dict[str, Any]:
    scan = scan_skill_folder(source, skills_dir=skills_dir)
    if not apply:
        return {
            **scan,
            "applied": False,
            "imported": [],
            "backups": [],
            "next_command": shlex.join([PUBLIC_COMMAND, "skills", "import", scan["source"], "--apply"]),
        }

    target_root = _safe_target_root(Path(scan["skills_dir"]), create=True)
    imported: list[dict[str, Any]] = []
    backups: list[str] = []
    for item in scan["candidates"]:
        if item["status"] not in {"importable", "conflict"}:
            continue
        source_file = Path(item["path"])
        skill_dir = target_root / item["name"]
        backup = _transactional_replace_skill(source_file.parent, skill_dir, target_root)
        if backup:
            backups.append(backup)
        imported.append({
            "name": item["name"],
            "source": str(source_file),
            "target": str(skill_dir / "SKILL.md"),
            "backup": backup,
            "backups": [backup] if backup else [],
        })
    return {**scan, "applied": True, "imported": imported, "backups": backups, "next_command": ""}


def format_skill_scan(report: dict[str, Any], *, limit: int = 80) -> str:
    lines = [
        "SKILL FOLDER SCAN",
        f"Source: {report['source']}",
        f"Target: {report['skills_dir']}",
        f"Found: {report['candidate_count']} SKILL.md file(s), {report['importable_count']} importable or replaceable",
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
        lines.append(f"... {len(report['candidates']) - limit} more. Use --limit 0 or --json for the full scan.")
    if report.get("next_command"):
        lines.append(f"Next: {report['next_command']}")
    return "\n".join(lines) + "\n"


def format_skill_import(report: dict[str, Any], *, limit: int = 80) -> str:
    if not report.get("applied"):
        return format_skill_scan(report, limit=limit)
    lines = ["SKILL IMPORT COMPLETE", f"Source: {report['source']}", f"Target: {report['skills_dir']}"]
    if not report["imported"]:
        lines.append("OK nothing new to import")
    for item in report["imported"]:
        suffix = f" backup: {item['backup']}" if item.get("backup") else ""
        lines.append(f"OK {item['name']}: {item['target']}{suffix}")
    return "\n".join(lines) + "\n"


def format_skill_reconcile(report: dict[str, Any], *, limit: int = 80) -> str:
    lines = [
        "SKILL RECONCILE",
        f"Target: {report['skills_dir']}",
        f"Bundled Manageroo skills: {report['bundled_skill_count']}",
        f"Applied: {str(report['applied']).lower()}",
    ]
    if report.get("missing_bundled"):
        lines.append("ACTION missing bundled skills: " + ", ".join(report["missing_bundled"][:limit]))
    else:
        lines.append("OK bundled skills have one active target copy")
    duplicates = report.get("duplicates", {})
    if duplicates:
        lines.append(f"WARN duplicate skill names found across scanned roots: {len(duplicates)}")
        items = list(duplicates.items()) if limit <= 0 else list(duplicates.items())[:limit]
        for name, matches in items:
            roots = sorted({item["root"] for item in matches})
            lines.append(f"WARN {name}: {len(matches)} copy/copies across {', '.join(roots)}")
        if limit > 0 and len(duplicates) > limit:
            lines.append(f"... {len(duplicates) - limit} more. Use --limit 0 or --json.")
    else:
        lines.append("OK no duplicate skill names found in scanned roots")
    if report.get("external_imports"):
        imported = sum(len(item.get("imported", [])) for item in report["external_imports"])
        lines.append(f"OK external imports applied: {imported}")
    if report.get("next_command"):
        lines.append(f"Next: {report['next_command']}")
    lines.append(report["note"])
    return "\n".join(lines) + "\n"