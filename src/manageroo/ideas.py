from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .branding import PROJECT_DIR
from .util import atomic_write_json, new_run_id, read_json, slugify, utc_now


def _lock_owner_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("pid="):
        return None
    try:
        pid = int(text.split("=", 1)[1])
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_live(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _reclaim_abandoned_lock(path: Path) -> bool:
    pid = _lock_owner_pid(path)
    if pid is not None and _pid_is_live(pid):
        return False
    # Re-read the owner immediately before unlinking so we do not remove a lock that
    # was replaced by a live contender between inspection and takeover.
    before = _lock_owner_pid(path)
    if before is not None and _pid_is_live(before):
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


@contextmanager
def _exclusive_lock(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            _reclaim_abandoned_lock(path)
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
            if _lock_owner_pid(path) == os.getpid():
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
