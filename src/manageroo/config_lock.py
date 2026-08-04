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


def _is_reparse_point(state: os.stat_result) -> bool:
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(state, "st_file_attributes", 0) & reparse_point)


def _validate_lock_directory(
    descriptor: int | None, lock_directory: Path
) -> os.stat_result:
    directory_state = os.fstat(descriptor) if descriptor is not None else None
    try:
        path_state = lock_directory.lstat()
    except OSError as exc:
        raise SafetyError(
            f"Could not validate config lock directory: {lock_directory}: {exc}"
        ) from exc
    if directory_state is None:
        directory_state = path_state
    getuid = getattr(os, "getuid", None)
    owner_is_unsafe = getuid is not None and directory_state.st_uid != getuid()
    permissions_are_unsafe = (
        os.name != "nt" and stat.S_IMODE(directory_state.st_mode) & 0o022 != 0
    )
    if (
        stat.S_ISLNK(path_state.st_mode)
        or _is_reparse_point(path_state)
        or not stat.S_ISDIR(directory_state.st_mode)
        or not stat.S_ISDIR(path_state.st_mode)
        or owner_is_unsafe
        or permissions_are_unsafe
        or (directory_state.st_dev, directory_state.st_ino)
        != (path_state.st_dev, path_state.st_ino)
    ):
        raise SafetyError(f"Config lock directory is unsafe: {lock_directory}")
    return directory_state


def _validate_lock_file(
    descriptor: int,
    lock_path: Path,
    *,
    directory_descriptor: int | None,
) -> os.stat_result:
    lock_state = os.fstat(descriptor)
    try:
        if directory_descriptor is None:
            path_state = lock_path.lstat()
        else:
            path_state = os.stat(
                lock_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
    except OSError as exc:
        raise SafetyError(
            f"Could not validate config mutation lock: {lock_path}: {exc}"
        ) from exc
    getuid = getattr(os, "getuid", None)
    owner_is_unsafe = getuid is not None and lock_state.st_uid != getuid()
    permissions_are_unsafe = (
        os.name != "nt" and stat.S_IMODE(lock_state.st_mode) & 0o077 != 0
    )
    if (
        stat.S_ISLNK(path_state.st_mode)
        or _is_reparse_point(path_state)
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
def config_mutation_lock(
    config_path: Path, *, timeout_seconds: float = 30.0
) -> Iterator[None]:
    lock_directory = config_path.parent / "cache"
    try:
        lock_directory.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise SafetyError(
            f"Could not create config lock directory: {lock_directory}: {exc}"
        ) from exc
    directory_descriptor = None
    if os.name == "nt":
        _validate_lock_directory(None, lock_directory)
    else:
        directory_flags = os.O_RDONLY
        directory_flags |= getattr(os, "O_CLOEXEC", 0)
        directory_flags |= getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_descriptor = os.open(lock_directory, directory_flags)
        except OSError as exc:
            raise SafetyError(
                f"Could not open config lock directory: {lock_directory}: {exc}"
            ) from exc
        try:
            _validate_lock_directory(directory_descriptor, lock_directory)
        except BaseException:
            os.close(directory_descriptor)
            raise

    lock_path = lock_directory / (config_path.name + ".manageroo.lock")
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        if directory_descriptor is None:
            descriptor = os.open(lock_path, flags, 0o600)
        else:
            descriptor = os.open(
                lock_path.name,
                flags,
                0o600,
                dir_fd=directory_descriptor,
            )
    except OSError as exc:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise SafetyError(f"Could not open config mutation lock: {lock_path}: {exc}") from exc

    acquired = False
    try:
        lock_state = _validate_lock_file(
            descriptor,
            lock_path,
            directory_descriptor=directory_descriptor,
        )
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

        _validate_lock_directory(directory_descriptor, lock_directory)
        _validate_lock_file(
            descriptor,
            lock_path,
            directory_descriptor=directory_descriptor,
        )
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
            if directory_descriptor is not None:
                os.close(directory_descriptor)
