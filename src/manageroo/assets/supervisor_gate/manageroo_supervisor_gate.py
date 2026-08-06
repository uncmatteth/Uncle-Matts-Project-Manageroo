from __future__ import annotations

import errno
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


GATE_VERSION = "1.0.0"
GATE_VERSION_ARG = "--manageroo-runtime-gate-version"
TRANSIENT_EXIT_CODE = 75


class RuntimeLockBusy(Exception):
    pass


def _is_reparse_point(state: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(state, "st_file_attributes", 0) & marker)


@contextmanager
def _runtime_lock() -> Iterator[None]:
    active = Path(sys.argv[0]).expanduser().resolve(strict=True)
    lock_directory = active.parent / "cache"
    lock_directory.mkdir(mode=0o700, exist_ok=True)
    directory_state = lock_directory.lstat()
    getuid = getattr(os, "getuid", None)
    if (
        stat.S_ISLNK(directory_state.st_mode)
        or _is_reparse_point(directory_state)
        or not stat.S_ISDIR(directory_state.st_mode)
        or (getuid is not None and directory_state.st_uid != getuid())
        or (os.name != "nt" and stat.S_IMODE(directory_state.st_mode) & 0o022)
    ):
        raise OSError(f"Supervisor runtime lock directory is unsafe: {lock_directory}")

    lock_path = lock_directory / f"{active.name}.manageroo.lock"
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    acquired = False
    try:
        lock_state = os.fstat(descriptor)
        path_state = lock_path.lstat()
        if (
            stat.S_ISLNK(path_state.st_mode)
            or _is_reparse_point(path_state)
            or not stat.S_ISREG(lock_state.st_mode)
            or not stat.S_ISREG(path_state.st_mode)
            or lock_state.st_nlink != 1
            or path_state.st_nlink != 1
            or (getuid is not None and lock_state.st_uid != getuid())
            or (os.name != "nt" and stat.S_IMODE(lock_state.st_mode) & 0o077)
            or (lock_state.st_dev, lock_state.st_ino)
            != (path_state.st_dev, path_state.st_ino)
        ):
            raise OSError(f"Supervisor runtime lock is unsafe: {lock_path}")
        if lock_state.st_size == 0:
            os.ftruncate(descriptor, 1)
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeLockBusy from exc
            raise
        acquired = True
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _run_supervisor() -> int:
    from clawpatch_supervise.clawpatch_external import main

    return int(main())


def main() -> int:
    if sys.argv[1:] == [GATE_VERSION_ARG]:
        print(GATE_VERSION)
        return 0
    if sys.argv[1:] == ["--version"]:
        return _run_supervisor()
    try:
        with _runtime_lock():
            return _run_supervisor()
    except RuntimeLockBusy:
        print(
            "The ClawPatch supervisor installation is being updated or is already active.",
            file=sys.stderr,
        )
        return TRANSIENT_EXIT_CODE
