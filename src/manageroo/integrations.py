from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .errors import SafetyError
from .runner import CommandRunner
from .util import atomic_write_text, safe_repo_relative


MAX_EXTERNAL_TEXT_CHARS = 12_000


def _terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[a-zA-Z0-9_-]{3,}", query)}


def _ensure_safe_directory_chain(root: Path, relative: str) -> Path:
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise SafetyError(f"Obsidian export path contains a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise SafetyError(f"Obsidian export path component is not a directory: {current}")
        current.mkdir(exist_ok=True)
        resolved = current.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SafetyError(f"Obsidian export path escapes the configured vault: {current}") from exc
    return current


class ObsidianIntegration:
    """Reads/writes plain Markdown. Obsidian itself is not required."""

    def __init__(self, vault: str, export_folder: str):
        self.vault = Path(vault).expanduser().resolve() if vault else None
        self.export_folder = export_folder

    def search(self, query: str, limit: int = 12) -> list[dict]:
        if not self.vault or not self.vault.is_dir():
            return []
        terms = _terms(query)
        scored: list[tuple[int, Path, str]] = []
        for path in self.vault.rglob("*.md"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                resolved.relative_to(self.vault)
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            haystack = (path.name + "\n" + text).lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, resolved, text))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [
            {"path": str(path.relative_to(self.vault)), "score": score, "excerpt": text[:4000]}
            for score, path, text in scored[:limit]
        ]

    def export(self, filename: str, markdown: str) -> Path | None:
        if not self.vault or not self.vault.is_dir():
            return None
        export_relative = safe_repo_relative(self.export_folder)
        filename_relative = safe_repo_relative(filename)
        export_root = _ensure_safe_directory_chain(self.vault, export_relative)
        if export_root.is_symlink():
            raise SafetyError("Configured Obsidian export root must not be a symlink.")
        try:
            export_root.resolve(strict=True).relative_to(self.vault)
        except (OSError, ValueError) as exc:
            raise SafetyError("Configured Obsidian export root escapes the vault.") from exc
        parent_relative = str(Path(filename_relative).parent)
        destination_parent = export_root if parent_relative == "." else _ensure_safe_directory_chain(export_root, parent_relative)
        destination = destination_parent / Path(filename_relative).name
        if destination.is_symlink():
            raise SafetyError(f"Refusing to overwrite symlinked Obsidian export: {destination}")
        atomic_write_text(destination, markdown)
        resolved_destination = destination.resolve(strict=True)
        try:
            resolved_destination.relative_to(export_root)
        except ValueError as exc:
            raise SafetyError("Obsidian export escaped the configured export root.") from exc
        return resolved_destination


class ExternalCommandIntegration:
    """Optional integration point with argv-only execution and explicit configuration."""

    def __init__(self, argv_template: Iterable[str], runner: CommandRunner):
        self.argv_template = list(argv_template)
        self.runner = runner

    @property
    def enabled(self) -> bool:
        return bool(self.argv_template)

    def run(self, *, cwd: Path, values: dict[str, str], timeout_seconds: int = 300, log_name: str | None = None):
        if not self.enabled:
            return None
        argv = [item.format(**values) for item in self.argv_template]
        return self.runner.run(argv, cwd=cwd, timeout_seconds=timeout_seconds, log_name=log_name)


def command_record(name: str, result) -> dict:
    if result is None:
        return {"name": name, "enabled": False, "ok": False}
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "name": name,
        "enabled": True,
        "ok": result.passed,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "argv": result.argv,
        "stdout": stdout[:MAX_EXTERNAL_TEXT_CHARS],
        "stderr": stderr[:MAX_EXTERNAL_TEXT_CHARS],
        "truncated": len(stdout) > MAX_EXTERNAL_TEXT_CHARS or len(stderr) > MAX_EXTERNAL_TEXT_CHARS,
    }
