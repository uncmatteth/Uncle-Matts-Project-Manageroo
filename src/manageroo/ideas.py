from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .branding import PROJECT_DIR
from .util import atomic_write_json, new_run_id, read_json, slugify, utc_now


@contextmanager
def _exclusive_lock(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for idea-inbox lock: {path}")
            time.sleep(0.02)
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class IdeaInbox:
    def __init__(self, repo: Path):
        self.root = repo / PROJECT_DIR / "ideas"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".attach.lock"

    def add(self, text: str, category: str = "unclassified") -> Path:
        idea_id = f"{new_run_id()}-{slugify(text, 32)}"
        path = self.root / f"{idea_id}.json"
        atomic_write_json(
            path,
            {
                "id": idea_id,
                "text": text,
                "category": category,
                "status": "captured",
                "created_at": utc_now(),
                "linked_run": None,
            },
        )
        return path

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        ideas = []
        for path in sorted(self.root.glob("*.json")):
            item = read_json(path)
            if status is None or item.get("status") == status:
                ideas.append(item)
        return ideas

    def attach_pending(self, run_id: str) -> list[dict]:
        attached: list[dict] = []
        # One process owns the read-check-write claim transaction at a time. Re-read
        # durable state while holding the lock so an idea can be attached to one run only.
        with _exclusive_lock(self.lock_path):
            for path in sorted(self.root.glob("*.json")):
                item = read_json(path)
                if item.get("status") != "captured":
                    continue
                item["status"] = "attached"
                item["linked_run"] = run_id
                atomic_write_json(path, item)
                attached.append(item)
        return attached