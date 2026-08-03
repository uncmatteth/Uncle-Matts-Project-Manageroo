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


def _validate_lock_file(descriptor: int, lock_path: Path) -> os.stat_result:
    lock_state = os.fstat(descriptor)
    try:
        path_state = lock_path.lstat()
    except OSError as exc:
        raise SafetyError(
            f"Could not validate config mutation lock: {lock_path}: {exc}"
        ) from exc
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    is_reparse_point = bool(
        getattr(path_state, "st_file_attributes", 0) & reparse_point
    )
    getuid = getattr(os, "getuid", None)
    owner_is_unsafe = getuid is not None and lock_state.st_uid != getuid()
    permissions_are_unsafe = (
        os.name != "nt" and stat.S_IMODE(lock_state.st_mode) & 0o077 != 0
    )
    if (
        stat.S_ISLNK(path_state.st_mode)
        or is_reparse_point
        or not stat.S_ISREG(lock_state.st_mode)
        or not stat.S_ISREG(path_state.st_mode)
        or lock_state.st_nlink != 1
        or path_state.st_nlink != 1
        or owner_is_unsafe
        or permissions_are_unsafe
        or (lock_state.st_dev, lock_state.st_ino) != (path_state.st_dev, path_state.st_ino)
    ):
        raise SafetyError(f"Config mutation lock is unsafe: {lock_path}")
    return lock_state


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
        lock_state = _validate_lock_file(descriptor, lock_path)
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

        _validate_lock_file(descriptor, lock_path)
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
