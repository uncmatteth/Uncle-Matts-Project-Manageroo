from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

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


def git_visible_files(repo: Path, runner: CommandRunner) -> list[str]:
    result = runner.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        timeout_seconds=120,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "git ls-files failed")
    return sorted({safe_repo_relative(item) for item in result.stdout.split("\0") if item})


def looks_binary(path: Path) -> bool:
    try:
        data = path.read_bytes()[:8192]
    except OSError:
        return True
    return b"\0" in data


def build_inventory(repo: Path, runner: CommandRunner, chars_per_token: float = 3.5) -> list[InventoryFile]:
    files: list[InventoryFile] = []
    for relative in git_visible_files(repo, runner):
        path = repo / relative
        if not path.is_file() or path.is_symlink() or looks_binary(path):
            continue
        size = path.stat().st_size
        files.append(
            InventoryFile(
                path=relative,
                bytes=size,
                sha256=sha256_file(path),
                language=_LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "text"),
                estimated_tokens=max(1, int(size / chars_per_token)),
            )
        )
    return files


def inventory_summary(files: list[InventoryFile]) -> dict:
    by_language: dict[str, int] = {}
    total_bytes = 0
    for item in files:
        total_bytes += item.bytes
        by_language[item.language] = by_language.get(item.language, 0) + 1
    return {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "languages": dict(sorted(by_language.items())),
        "files": [asdict(item) for item in files],
    }
