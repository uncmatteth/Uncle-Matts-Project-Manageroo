from __future__ import annotations

import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any

from .errors import SafetyError
from .util import atomic_write_json, utc_now


_COMPACTABLE_COMPLETE_PATHS = (
    "packets",
    "review-packets",
    "agent-output",
    "worker-attempts",
    "logs",
    "jobs",
    "artifacts/discovery",
    "artifacts/planning",
    "artifacts/implementation",
    "artifacts/learning",
)


def _tree_bytes(root: Path) -> int:
    total = 0
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories if not (current_path / name).is_symlink()
        ]
        for name in files:
            path = current_path / name
            try:
                metadata = path.lstat()
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
    return total


def _remove_owned_path(path: Path, run_root: Path) -> bool:
    try:
        path.relative_to(run_root)
    except ValueError as exc:
        raise SafetyError(f"Retention target escapes its run root: {path}") from exc
    if path.is_symlink() or path.is_file():
        path.unlink()
        return True
    if path.is_dir():
        shutil.rmtree(path)
        return True
    return False


def _run_status(run_root: Path) -> str:
    for path, field in (
        (run_root / "delivery" / "final-result.json", "status"),
        (run_root / "controller" / "workspace-lifecycle.json", "status"),
        (run_root / "state.json", "phase"),
    ):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            value = str(payload.get(field) or "")
            if value:
                return value
    return "UNKNOWN"


def _compact_complete_run(run_root: Path, max_bytes: int) -> dict[str, Any]:
    before = _tree_bytes(run_root)
    removed: list[str] = []
    if before > max_bytes:
        for relative in _COMPACTABLE_COMPLETE_PATHS:
            path = run_root / relative
            if _remove_owned_path(path, run_root):
                removed.append(relative)
            if _tree_bytes(run_root) <= max_bytes:
                break
    after = _tree_bytes(run_root)
    report = {
        "status": "COMPLETE",
        "bytes_before": before,
        "bytes_after": after,
        "max_bytes": max_bytes,
        "quota_satisfied": after <= max_bytes,
        "removed": removed,
        "checked_at": utc_now(),
    }
    atomic_write_json(run_root / "controller" / "retention.json", report)
    report["bytes_after"] = _tree_bytes(run_root)
    report["quota_satisfied"] = report["bytes_after"] <= max_bytes
    return report


def enforce_run_retention(
    repo: Path, *, current_run_id: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Bound terminal Manageroo state without touching source repository files."""

    max_count = int(config.get("max_run_count", 40))
    max_age_days = int(config.get("max_run_age_days", 30))
    max_bytes = int(config.get("max_run_evidence_bytes", 1073741824))
    if max_count < 1 or max_age_days < 0 or max_bytes < 4096:
        raise SafetyError("Manageroo retention limits are invalid.")

    runs_root = repo.resolve() / ".manageroo" / "runs"
    current_run = runs_root / current_run_id
    current_report: dict[str, Any] = {}
    if current_run.is_dir() and _run_status(current_run) == "COMPLETE":
        current_report = _compact_complete_run(current_run, max_bytes)

    now = time.time()
    terminal: list[tuple[float, Path]] = []
    if runs_root.is_dir():
        for path in runs_root.iterdir():
            if path.name == current_run_id or path.is_symlink() or not path.is_dir():
                continue
            if _run_status(path) not in {"BLOCKED", "CANCELED", "COMPLETE"}:
                continue
            terminal.append((path.stat().st_mtime, path))
    terminal.sort(key=lambda item: (item[0], item[1].name))

    removed_runs: list[str] = []
    age_seconds = max_age_days * 86400
    survivors: list[tuple[float, Path]] = []
    for modified, path in terminal:
        if max_age_days == 0 or now - modified > age_seconds:
            shutil.rmtree(path)
            removed_runs.append(path.name)
        else:
            survivors.append((modified, path))

    keep_old = max(0, max_count - 1)
    excess = max(0, len(survivors) - keep_old)
    for _modified, path in survivors[:excess]:
        shutil.rmtree(path)
        removed_runs.append(path.name)

    report = {
        "schema_version": 1,
        "current_run_id": current_run_id,
        "current_run": current_report,
        "removed_runs": removed_runs,
        "max_run_count": max_count,
        "max_run_age_days": max_age_days,
        "max_run_evidence_bytes": max_bytes,
        "checked_at": utc_now(),
    }
    cache_path = repo.resolve() / ".manageroo" / "cache" / "retention.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cache_path, report)
    return report
