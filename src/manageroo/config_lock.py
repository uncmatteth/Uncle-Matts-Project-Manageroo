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


def _validate_config_directory(
    descriptor: int | None,
    config_directory: Path,
    repository: Path | None,
) -> os.stat_result:
    directory_state = os.fstat(descriptor) if descriptor is not None else None
    try:
        path_state = config_directory.lstat()
    except OSError as exc:
        raise SafetyError(
            f"Could not validate config directory: {config_directory}: {exc}"
        ) from exc
    if directory_state is None:
        directory_state = path_state
    if (
        stat.S_ISLNK(path_state.st_mode)
        or _is_reparse_point(path_state)
        or not stat.S_ISDIR(directory_state.st_mode)
        or not stat.S_ISDIR(path_state.st_mode)
        or (directory_state.st_dev, directory_state.st_ino)
        != (path_state.st_dev, path_state.st_ino)
    ):
        raise SafetyError(f"Config directory is unsafe: {config_directory}")
    if repository is not None:
        try:
            relative = config_directory.resolve(strict=True).relative_to(
                repository.resolve(strict=True)
            )
        except (OSError, ValueError) as exc:
            raise SafetyError(
                f"Config directory escapes repository: {config_directory}"
            ) from exc
        if len(relative.parts) != 1:
            raise SafetyError(f"Config directory is unsafe: {config_directory}")
        try:
            final_path_state = config_directory.lstat()
        except OSError as exc:
            raise SafetyError(
                f"Could not revalidate config directory: {config_directory}: {exc}"
            ) from exc
        if (
            stat.S_ISLNK(final_path_state.st_mode)
            or _is_reparse_point(final_path_state)
            or (directory_state.st_dev, directory_state.st_ino)
            != (final_path_state.st_dev, final_path_state.st_ino)
        ):
            raise SafetyError(f"Config directory is unsafe: {config_directory}")
    return directory_state


def _validate_lock_directory(
    descriptor: int | None,
    lock_directory: Path,
    *,
    parent_descriptor: int | None = None,
) -> os.stat_result:
    directory_state = os.fstat(descriptor) if descriptor is not None else None
    try:
        if parent_descriptor is None:
            path_state = lock_directory.lstat()
        else:
            path_state = os.stat(
                lock_directory.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
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
    config_path: Path,
    *,
    timeout_seconds: float = 30.0,
    repository: Path | None = None,
) -> Iterator[int | None]:
    config_directory = config_path.parent
    config_directory_descriptor = None
    if os.name == "nt":
        _validate_config_directory(None, config_directory, repository)
    else:
        _validate_config_directory(None, config_directory, repository)
        config_directory_flags = os.O_RDONLY
        config_directory_flags |= getattr(os, "O_CLOEXEC", 0)
        config_directory_flags |= getattr(os, "O_DIRECTORY", 0)
        config_directory_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            config_directory_descriptor = os.open(
                config_directory,
                config_directory_flags,
            )
        except OSError as exc:
            raise SafetyError(
                f"Could not open config directory: {config_directory}: {exc}"
            ) from exc
        try:
            _validate_config_directory(
                config_directory_descriptor,
                config_directory,
                repository,
            )
        except BaseException:
            os.close(config_directory_descriptor)
            raise

    lock_directory = config_path.parent / "cache"
    try:
        if config_directory_descriptor is None:
            lock_directory.mkdir(mode=0o700, exist_ok=True)
        else:
            try:
                os.mkdir(
                    lock_directory.name,
                    mode=0o700,
                    dir_fd=config_directory_descriptor,
                )
            except FileExistsError:
                pass
    except OSError as exc:
        if config_directory_descriptor is not None:
            os.close(config_directory_descriptor)
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
            directory_descriptor = os.open(
                lock_directory.name,
                directory_flags,
                dir_fd=config_directory_descriptor,
            )
        except OSError as exc:
            if config_directory_descriptor is not None:
                os.close(config_directory_descriptor)
            raise SafetyError(
                f"Could not open config lock directory: {lock_directory}: {exc}"
            ) from exc
        try:
            _validate_lock_directory(
                directory_descriptor,
                lock_directory,
                parent_descriptor=config_directory_descriptor,
            )
        except BaseException:
            os.close(directory_descriptor)
            if config_directory_descriptor is not None:
                os.close(config_directory_descriptor)
            raise

    lock_path = lock_directory / (config_path.name + ".manageroo.lock")
    flags = os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    def open_lock_file(open_flags: int) -> int:
        if directory_descriptor is None:
            return os.open(lock_path, open_flags, 0o600)
        return os.open(
            lock_path.name,
            open_flags,
            0o600,
            dir_fd=directory_descriptor,
        )

    try:
        try:
            descriptor = open_lock_file(flags | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            descriptor = open_lock_file(flags)
    except OSError as exc:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        if config_directory_descriptor is not None:
            os.close(config_directory_descriptor)
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

        _validate_config_directory(
            config_directory_descriptor,
            config_directory,
            repository,
        )
        _validate_lock_directory(
            directory_descriptor,
            lock_directory,
            parent_descriptor=config_directory_descriptor,
        )
        _validate_lock_file(
            descriptor,
            lock_path,
            directory_descriptor=directory_descriptor,
        )
        owner_payload = f"pid={os.getpid()}\n".encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, owner_payload)
        os.ftruncate(descriptor, len(owner_payload))
        os.fsync(descriptor)
        yield config_directory_descriptor
        _validate_config_directory(
            config_directory_descriptor,
            config_directory,
            repository,
        )
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
            if config_directory_descriptor is not None:
                os.close(config_directory_descriptor)
