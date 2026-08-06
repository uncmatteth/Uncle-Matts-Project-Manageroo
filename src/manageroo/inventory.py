from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .errors import SafetyError
from .file_inspection import (
    content_kind_for_path,
    language_for_media,
    looks_binary,
    media_summary,
    text_summary,
)
from .integrations import _open_beneath, _openat2_syscall_number
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
_FILE_INSPECTION_ATTEMPTS = 3


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


def _inspection_signature(state: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        state.st_dev,
        state.st_ino,
        state.st_mode,
        state.st_size,
        state.st_mtime_ns,
        state.st_ctime_ns,
    )


def _descriptor_inventory_supported() -> bool:
    return (
        _openat2_syscall_number() is not None
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_NONBLOCK")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _open_directory_at(path: str | Path, *, directory_fd: int | None = None) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, dir_fd=directory_fd)


def _copy_inventory_descriptor(source_fd: int, destination) -> str:
    digest = sha256()
    while block := os.read(source_fd, 1024 * 1024):
        digest.update(block)
        destination.write(block)
    return digest.hexdigest()


def _snapshot_inventory_file(
    repo_fd: int,
    relative: str,
) -> tuple[Path, os.stat_result, str] | None:
    file_fd: int | None = None
    verification_fd: int | None = None
    snapshot_fd: int | None = None
    snapshot_name = ""
    keep_snapshot = False
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        file_fd = _open_beneath(repo_fd, relative, flags)
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            return None

        snapshot_fd, snapshot_name = tempfile.mkstemp(suffix=Path(relative).suffix)
        with os.fdopen(snapshot_fd, "wb") as destination:
            snapshot_fd = None
            digest = _copy_inventory_descriptor(file_fd, destination)

        after = os.fstat(file_fd)
        verification_fd = _open_beneath(repo_fd, relative, flags)
        current = os.fstat(verification_fd)
        if (
            _inspection_signature(before) != _inspection_signature(after)
            or after.st_nlink != 1
            or current.st_nlink != 1
            or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
        ):
            return None
        keep_snapshot = True
        return Path(snapshot_name), after, digest
    except OSError:
        return None
    finally:
        if snapshot_fd is not None:
            os.close(snapshot_fd)
        if file_fd is not None:
            os.close(file_fd)
        if verification_fd is not None:
            os.close(verification_fd)
        if snapshot_name and not keep_snapshot:
            Path(snapshot_name).unlink(missing_ok=True)


def build_inventory(
    repo: Path,
    runner: CommandRunner,
    chars_per_token: float = 3.5,
    summary_cache_path: Path | None = None,
) -> list[InventoryFile]:
    if not _descriptor_inventory_supported():
        raise SafetyError(
            "Inventory requires descriptor-relative no-follow filesystem access."
        )
    files: list[InventoryFile] = []
    cache = _load_summary_cache(summary_cache_path)
    next_cache: dict[str, dict[str, Any]] = {}
    repo_fd = _open_directory_at(repo)
    try:
        for relative in git_visible_files(repo, runner):
            path = repo / relative
            item: InventoryFile | None = None
            for _attempt in range(_FILE_INSPECTION_ATTEMPTS):
                snapshot = _snapshot_inventory_file(repo_fd, relative)
                if snapshot is None:
                    continue
                snapshot_path, state, digest = snapshot
                try:
                    size = state.st_size
                    if (
                        snapshot_path.stat().st_size != size
                        or sha256_file(snapshot_path) != digest
                    ):
                        continue
                    cached = _cached_inventory_file(
                        relative,
                        cached=(
                            cache.get(relative)
                            if isinstance(cache.get(relative), dict)
                            else None
                        ),
                        sha256=digest,
                        size=size,
                    )
                    if cached:
                        candidate = cached
                    else:
                        content_kind = content_kind_for_path(path)
                        if content_kind == "media":
                            language = language_for_media(path) or "binary"
                            summary, line_count = media_summary(
                                snapshot_path, relative, runner=runner
                            )
                            estimated_tokens = max(
                                1, int(len(summary) / chars_per_token)
                            )
                        else:
                            if looks_binary(snapshot_path):
                                break
                            text = snapshot_path.read_text(
                                encoding="utf-8", errors="replace"
                            )
                            summary, line_count = text_summary(snapshot_path, relative)
                            language = _LANGUAGE_BY_SUFFIX.get(
                                path.suffix.lower(), "text"
                            )
                            estimated_tokens = max(
                                1, int(len(text) / chars_per_token)
                            )
                            if content_kind == "source":
                                summary = (
                                    f"Source text file. Bytes: {size}. "
                                    f"Lines: {line_count}."
                                )
                        candidate = InventoryFile(
                            path=relative,
                            bytes=size,
                            sha256=digest,
                            language=language,
                            estimated_tokens=estimated_tokens,
                            content_kind=content_kind,
                            line_count=line_count,
                            summary=summary,
                        )
                    item = candidate
                    break
                finally:
                    snapshot_path.unlink(missing_ok=True)
            if item is None:
                continue
            files.append(item)
            next_cache[relative] = asdict(item)
    finally:
        os.close(repo_fd)
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
