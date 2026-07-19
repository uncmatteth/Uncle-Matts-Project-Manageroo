from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .runner import CommandRunner
from .util import atomic_write_text, safe_repo_relative


MAX_EXTERNAL_TEXT_CHARS = 12_000


def _terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[a-zA-Z0-9_-]{3,}", query)}


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
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            haystack = (path.name + "\n" + text).lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((score, path, text))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [
            {
                "path": str(path.relative_to(self.vault)),
                "score": score,
                "excerpt": text[:4000],
            }
            for score, path, text in scored[:limit]
        ]

    def export(self, filename: str, markdown: str) -> Path | None:
        if not self.vault or not self.vault.is_dir():
            return None
        export_root = (self.vault / safe_repo_relative(self.export_folder)).resolve()
        destination = (export_root / safe_repo_relative(filename)).resolve()
        destination.relative_to(export_root)
        atomic_write_text(destination, markdown)
        return destination


class ExternalCommandIntegration:
    """Optional integration point with argv-only execution and explicit configuration."""

    def __init__(self, argv_template: Iterable[str], runner: CommandRunner):
        self.argv_template = list(argv_template)
        self.runner = runner

    @property
    def enabled(self) -> bool:
        return bool(self.argv_template)

    def run(
        self,
        *,
        cwd: Path,
        values: dict[str, str],
        timeout_seconds: int = 300,
        log_name: str | None = None,
    ):
        if not self.enabled:
            return None
        argv = [item.format(**values) for item in self.argv_template]
        return self.runner.run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            log_name=log_name,
        )


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
