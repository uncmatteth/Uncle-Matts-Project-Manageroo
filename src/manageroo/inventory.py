from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .file_inspection import (
    content_kind_for_path,
    language_for_media,
    looks_binary,
    media_summary,
    text_summary,
)
from .runner import CommandRunner
from .util import atomic_write_json, read_json, safe_repo_relative, sha256_file


_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".md": "markdown",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sql": "sql",
}


@dataclass(frozen=True)
class InventoryFile:
    path: str
    bytes: int
    sha256: str
    language: str
    estimated_tokens: int
    content_kind: str
    line_count: int
    summary: str


def git_visible_files(repo: Path, runner: CommandRunner) -> list[str]:
    result = runner.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        timeout_seconds=120,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "git ls-files failed")
    return sorted({safe_repo_relative(item) for item in result.stdout.split("\0") if item})


def _load_summary_cache(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = read_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _cached_inventory_file(
    relative: str,
    *,
    cached: dict[str, Any] | None,
    sha256: str,
    size: int,
) -> InventoryFile | None:
    if not cached:
        return None
    try:
        cached_bytes = int(cached.get("bytes", -1))
        if cached.get("sha256") != sha256 or cached_bytes != size:
            return None
        return InventoryFile(
            path=relative,
            bytes=size,
            sha256=sha256,
            language=str(cached["language"]),
            estimated_tokens=int(cached["estimated_tokens"]),
            content_kind=str(cached["content_kind"]),
            line_count=int(cached["line_count"]),
            summary=str(cached["summary"]),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def build_inventory(
    repo: Path,
    runner: CommandRunner,
    chars_per_token: float = 3.5,
    summary_cache_path: Path | None = None,
) -> list[InventoryFile]:
    files: list[InventoryFile] = []
    cache = _load_summary_cache(summary_cache_path)
    next_cache: dict[str, dict[str, Any]] = {}
    for relative in git_visible_files(repo, runner):
        path = repo / relative
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        digest = sha256_file(path)
        cached = _cached_inventory_file(
            relative,
            cached=cache.get(relative) if isinstance(cache.get(relative), dict) else None,
            sha256=digest,
            size=size,
        )
        if cached:
            files.append(cached)
            next_cache[relative] = asdict(cached)
            continue
        content_kind = content_kind_for_path(path)
        if content_kind == "media":
            language = language_for_media(path) or "binary"
            summary, line_count = media_summary(path, relative, runner=runner)
            estimated_tokens = max(1, int(len(summary) / chars_per_token))
        else:
            if looks_binary(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            summary, line_count = text_summary(path, relative)
            language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text")
            estimated_tokens = max(1, int(len(text) / chars_per_token))
            if content_kind == "source":
                summary = f"Source text file. Bytes: {path.stat().st_size}. Lines: {line_count}."
        item = InventoryFile(
            path=relative,
            bytes=size,
            sha256=digest,
            language=language,
            estimated_tokens=estimated_tokens,
            content_kind=content_kind,
            line_count=line_count,
            summary=summary,
        )
        files.append(item)
        next_cache[relative] = asdict(item)
    if summary_cache_path:
        atomic_write_json(summary_cache_path, next_cache)
    return files


def inventory_summary(files: list[InventoryFile]) -> dict:
    by_language: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    total_bytes = 0
    for item in files:
        total_bytes += item.bytes
        by_language[item.language] = by_language.get(item.language, 0) + 1
        by_kind[item.content_kind] = by_kind.get(item.content_kind, 0) + 1
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "languages": dict(sorted(by_language.items())),
        "content_kinds": dict(sorted(by_kind.items())),
        "files": [asdict(item) for item in files],
    }
