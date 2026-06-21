from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .file_inspection import (
    content_kind_for_path,
    language_for_media,
    looks_binary,
    media_summary,
    text_summary,
)
from .runner import CommandRunner
from .util import safe_repo_relative, sha256_file


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


def build_inventory(repo: Path, runner: CommandRunner, chars_per_token: float = 3.5) -> list[InventoryFile]:
    files: list[InventoryFile] = []
    for relative in git_visible_files(repo, runner):
        path = repo / relative
        if not path.is_file() or path.is_symlink():
            continue
        content_kind = content_kind_for_path(path)
        if content_kind == "media":
            language = language_for_media(path) or "binary"
            summary, line_count = media_summary(path, relative)
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
        size = path.stat().st_size
        files.append(
            InventoryFile(
                path=relative,
                bytes=size,
                sha256=sha256_file(path),
                language=language,
                estimated_tokens=estimated_tokens,
                content_kind=content_kind,
                line_count=line_count,
                summary=summary,
            )
        )
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
