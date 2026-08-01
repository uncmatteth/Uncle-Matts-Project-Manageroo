from __future__ import annotations

import errno
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import SafetyError


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
def config_mutation_lock(config_path: Path, *, timeout_seconds: float = 30.0) -> Iterator[None]:
    lock_directory = config_path.parent / "cache"
    try:
        lock_directory.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise SafetyError(
            f"Could not create config lock directory: {lock_directory}: {exc}"
        ) from exc
    if lock_directory.is_symlink() or not lock_directory.is_dir():
        raise SafetyError(f"Config lock directory is unsafe: {lock_directory}")
    lock_path = lock_directory / (config_path.name + ".manageroo.lock")
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise SafetyError(f"Could not open config mutation lock: {lock_path}: {exc}") from exc

    acquired = False
    try:
        lock_state = os.fstat(descriptor)
        if not stat.S_ISREG(lock_state.st_mode):
            raise SafetyError(f"Config mutation lock is not a regular file: {lock_path}")
        if lock_state.st_size == 0:
            os.ftruncate(descriptor, 1)

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _try_lock_file(descriptor)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise SafetyError(
                        f"Could not acquire config mutation lock: {lock_path}: {exc}"
                    ) from exc
                if time.monotonic() >= deadline:
                    raise SafetyError(
                        f"Timed out waiting for config mutation lock: {lock_path}"
                    ) from exc
                time.sleep(0.05)

        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("utf-8"))
        os.fsync(descriptor)
        yield
    finally:
        try:
            if acquired:
                _unlock_file(descriptor)
        except OSError as exc:
            raise SafetyError(
                f"Could not release config mutation lock: {lock_path}: {exc}"
            ) from exc
        finally:
            os.close(descriptor)
