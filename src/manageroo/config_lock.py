from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import SafetyError


def _owner_pid(path: Path) -> int | None:
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


def _pid_live(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


@contextmanager
def config_mutation_lock(config_path: Path, *, timeout_seconds: float = 30.0) -> Iterator[None]:
    lock_path = config_path.with_name(config_path.name + ".manageroo.lock")
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pid = _owner_pid(lock_path)
            if pid is None or not _pid_live(pid):
                try:
                    lock_path.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise SafetyError(f"Timed out waiting for config mutation lock: {lock_path}")
            time.sleep(0.05)
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        try:
            if _owner_pid(lock_path) == os.getpid():
                lock_path.unlink()
        except FileNotFoundError:
            pass
