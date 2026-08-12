from __future__ import annotations

import errno
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .branding import PROJECT_DIR
from .util import atomic_write_json, new_run_id, read_json, slugify, utc_now


def _try_lock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _exclusive_lock(path: Path, *, timeout_seconds: float = 10.0) -> Iterator[None]:
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        lock_state = os.fstat(fd)
        path_state = path.lstat()
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        file_attributes = getattr(path_state, "st_file_attributes", 0)
        if stat.S_ISLNK(path_state.st_mode) or (reparse_point and file_attributes & reparse_point):
            raise OSError(f"Idea-inbox lock must not be a symlink or reparse point: {path}")
        if not stat.S_ISREG(lock_state.st_mode):
            raise OSError(f"Idea-inbox lock is not a regular file: {path}")
        if lock_state.st_nlink != 1:
            raise OSError(f"Idea-inbox lock must have exactly one link: {path}")
        if (path_state.st_dev, path_state.st_ino) != (lock_state.st_dev, lock_state.st_ino):
            raise OSError(f"Idea-inbox lock changed while it was opened: {path}")
        if lock_state.st_size == 0:
            os.ftruncate(fd, 1)

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _try_lock_file(fd)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for idea-inbox lock: {path}") from exc
                time.sleep(0.02)

        owner_payload = f"pid={os.getpid()}\n".encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, owner_payload)
        os.ftruncate(fd, len(owner_payload))
        os.fsync(fd)
        yield
    finally:
        try:
            if acquired:
                _unlock_file(fd)
        finally:
            os.close(fd)


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
                "classification": category,
                "disposition": "pending-product-analysis",
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
                item["classification"] = str(
                    item.get("classification") or item.get("category") or "unclassified"
                )
                item["disposition"] = "context-only-not-authorized"
                atomic_write_json(path, item)
                attached.append(item)
        return attached
