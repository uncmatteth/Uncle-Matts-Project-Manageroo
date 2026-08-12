from __future__ import annotations

import errno
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator

from .errors import SafetyError
from .util import atomic_write_json, atomic_write_text, utc_now


@dataclass
class ArtifactRecord:
    path: str
    sha256: str
    locked: bool
    created_at: str


class ArtifactStore:
    def __init__(self, root: Path):
        expanded_root = root.expanduser()
        self.root = (
            expanded_root
            if expanded_root.is_absolute()
            else Path.cwd() / expanded_root
        )
        self._lock = threading.RLock()
        self._root_descriptor = self._open_root_descriptor()
        self.ledger_path = self.root / "artifact-ledger.json"
        self.lock_path = self.root / ".artifact-ledger.lock"
        self.advisory_lock_path = self.root / ".artifact-ledger.advisory.lock"
        self.transaction_path = self.root / ".artifact-ledger.transaction"
        try:
            with self._transaction_lock():
                self._recover_pending_transaction()
                try:
                    descriptor = self._open_regular_at(
                        self._root_descriptor,
                        self.ledger_path.name,
                    )
                except FileNotFoundError:
                    self._atomic_write_at(
                        self._root_descriptor,
                        self.ledger_path.name,
                        lambda path: atomic_write_json(path, {"artifacts": {}}),
                    )
                else:
                    os.close(descriptor)
        except BaseException:
            os.close(self._root_descriptor)
            self._root_descriptor = -1
            raise

    def __del__(self) -> None:
        descriptor = getattr(self, "_root_descriptor", -1)
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
            self._root_descriptor = -1

    def _open_root_descriptor(self) -> int:
        required = (
            hasattr(os, "O_DIRECTORY")
            and hasattr(os, "O_NOFOLLOW")
            and os.open in os.supports_dir_fd
            and os.mkdir in os.supports_dir_fd
            and os.rename in os.supports_dir_fd
            and os.rmdir in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks
            and os.unlink in os.supports_dir_fd
            and os.listdir in os.supports_fd
        )
        if not required:
            raise SafetyError(
                "Artifact storage requires descriptor-relative no-follow filesystem access."
            )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        if not self.root.anchor:
            raise SafetyError(f"Artifact root is not absolute: {self.root}")
        try:
            descriptor = os.open(self.root.anchor, flags)
        except OSError as exc:
            raise SafetyError(f"Could not open artifact storage base: {self.root}") from exc
        try:
            for component in self.root.parts[1:]:
                if component in {"", ".", ".."}:
                    raise SafetyError(f"Artifact root is unsafe: {self.root}")
                try:
                    observed = os.stat(
                        component,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    try:
                        os.mkdir(component, 0o777, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    except OSError as exc:
                        raise SafetyError(
                            f"Could not create artifact root: {self.root}"
                        ) from exc
                    observed = os.stat(
                        component,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    raise SafetyError(
                        f"Could not inspect artifact root: {self.root}"
                    ) from exc

                reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                if (
                    stat.S_ISLNK(observed.st_mode)
                    or bool(
                        getattr(observed, "st_file_attributes", 0) & reparse_point
                    )
                    or not stat.S_ISDIR(observed.st_mode)
                ):
                    raise SafetyError(
                        f"Artifact root contains a symlink or unsafe directory: {self.root}"
                    )

                child_descriptor = self._open_directory_at(
                    descriptor,
                    component,
                    str(self.root),
                )
                try:
                    opened = os.fstat(child_descriptor)
                    current = os.stat(
                        component,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        not self._same_object(observed, opened)
                        or not self._same_object(opened, current)
                    ):
                        raise SafetyError(
                            f"Artifact root changed while opening: {self.root}"
                        )
                except BaseException:
                    os.close(child_descriptor)
                    raise
                os.close(descriptor)
                descriptor = child_descriptor
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _owner_from_lines(lines: list[str]) -> tuple[int, str] | None:
        pid: int | None = None
        token = ""
        for line in lines:
            if line.startswith("pid="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    return None
            elif line.startswith("token="):
                token = line.split("=", 1)[1].strip()
        return (pid, token) if pid is not None and pid > 0 else None

    def _owner_file_at(self, directory_fd: int, name: str) -> tuple[int, str] | None:
        try:
            descriptor = self._open_regular_at(directory_fd, name)
        except FileNotFoundError:
            return None
        try:
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                return self._owner_from_lines(handle.read().splitlines())
        except OSError:
            return None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _owner_at(self, directory_fd: int) -> tuple[int, str] | None:
        return self._owner_file_at(directory_fd, "owner")

    def _write_owner_at(self, directory_fd: int, token: str) -> None:
        payload = (
            f"pid={os.getpid()}\ntoken={token}\ncreated_at={utc_now()}\n"
        ).encode("utf-8")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open("owner", flags, 0o600, dir_fd=directory_fd)
        try:
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("Artifact lock owner write made no progress.")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_fd)

    def _open_lock_directory(self) -> int:
        return self._open_directory_at(
            self._root_descriptor,
            self.lock_path.name,
            self.lock_path.name,
        )

    def _lock_owner(self) -> tuple[int, str] | None:
        try:
            descriptor = self._open_lock_directory()
        except FileNotFoundError:
            return None
        try:
            return self._owner_at(descriptor)
        finally:
            os.close(descriptor)

    def _remove_tree_at(
        self,
        parent_fd: int,
        name: str,
        *,
        expected: os.stat_result | None = None,
    ) -> None:
        try:
            state = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if expected is not None and not self._same_object(expected, state):
            raise SafetyError(f"Artifact lock path changed during cleanup: {name}")
        if not stat.S_ISDIR(state.st_mode):
            os.unlink(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            return

        descriptor = self._open_directory_at(parent_fd, name, name)
        try:
            directory_state = os.fstat(descriptor)
            if not self._same_object(state, directory_state):
                raise SafetyError(f"Artifact lock path changed during cleanup: {name}")
            for child in os.listdir(descriptor):
                child_state = os.stat(child, dir_fd=descriptor, follow_symlinks=False)
                self._remove_tree_at(descriptor, child, expected=child_state)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not self._same_object(state, current):
            raise SafetyError(f"Artifact lock path changed during cleanup: {name}")
        os.rmdir(name, dir_fd=parent_fd)
        os.fsync(parent_fd)

    @staticmethod
    def _windows_pid_is_live(pid: int) -> bool:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_invalid_parameter = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() != error_invalid_parameter
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        if pid == os.getpid():
            return True
        if os.name == "nt":
            return ArtifactStore._windows_pid_is_live(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    @staticmethod
    def _try_advisory_lock(descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_advisory_lock(descriptor: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def _validate_advisory_lock(self, descriptor: int) -> None:
        descriptor_state = os.fstat(descriptor)
        path_state = os.stat(
            self.advisory_lock_path.name,
            dir_fd=self._root_descriptor,
            follow_symlinks=False,
        )
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        getuid = getattr(os, "getuid", None)
        if (
            stat.S_ISLNK(path_state.st_mode)
            or bool(getattr(path_state, "st_file_attributes", 0) & reparse_point)
            or not stat.S_ISREG(descriptor_state.st_mode)
            or not stat.S_ISREG(path_state.st_mode)
            or descriptor_state.st_nlink != 1
            or path_state.st_nlink != 1
            or (getuid is not None and descriptor_state.st_uid != getuid())
            or (os.name != "nt" and stat.S_IMODE(descriptor_state.st_mode) & 0o077 != 0)
            or (descriptor_state.st_dev, descriptor_state.st_ino)
            != (path_state.st_dev, path_state.st_ino)
        ):
            raise SafetyError(
                f"Artifact-store advisory lock is unsafe: {self.advisory_lock_path}"
            )

    @contextmanager
    def _advisory_transaction_lock(
        self, *, timeout_seconds: float
    ) -> Iterator[None]:
        flags = os.O_CREAT | os.O_RDWR
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(
                self.advisory_lock_path.name,
                flags,
                0o600,
                dir_fd=self._root_descriptor,
            )
        except OSError as exc:
            raise SafetyError(
                f"Could not open artifact-store advisory lock: "
                f"{self.advisory_lock_path}: {exc}"
            ) from exc

        acquired = False
        try:
            self._validate_advisory_lock(descriptor)
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    self._try_advisory_lock(descriptor)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise SafetyError(
                            f"Could not acquire artifact-store advisory lock: "
                            f"{self.advisory_lock_path}: {exc}"
                        ) from exc
                    if time.monotonic() >= deadline:
                        raise SafetyError(
                            f"Timed out waiting for artifact-store transaction lock: "
                            f"{self.advisory_lock_path}"
                        ) from exc
                    time.sleep(0.05)
            self._validate_advisory_lock(descriptor)
            yield
        finally:
            try:
                if acquired:
                    self._unlock_advisory_lock(descriptor)
            except OSError as exc:
                raise SafetyError(
                    f"Could not release artifact-store advisory lock: "
                    f"{self.advisory_lock_path}: {exc}"
                ) from exc
            finally:
                os.close(descriptor)

    def _reclaim_abandoned_lock(self) -> bool:
        try:
            lock_fd = self._open_lock_directory()
        except FileNotFoundError:
            return True
        lock_state = os.fstat(lock_fd)
        claim_state: os.stat_result | None = None
        claim_token = ""
        claimed = False
        try:
            owner = self._owner_at(lock_fd)
            if owner is not None and self._pid_is_live(owner[0]):
                return False
            # Unknown-owner lock directories are reclaimable only after a short age
            # guard, which avoids stealing one during owner publication.
            if owner is None and time.time() - lock_state.st_mtime < 2.0:
                return False

            while True:
                claim_token = secrets.token_hex(16)
                try:
                    os.mkdir("reclaim", 0o700, dir_fd=lock_fd)
                except FileExistsError:
                    if not self._reclaim_abandoned_claim(lock_fd):
                        return False
                    continue
                except FileNotFoundError:
                    return True
                claim_fd = self._open_directory_at(lock_fd, "reclaim", "reclaim")
                try:
                    claim_state = os.fstat(claim_fd)
                    self._write_owner_at(claim_fd, claim_token)
                except BaseException:
                    self._remove_tree_at(lock_fd, "reclaim", expected=claim_state)
                    claim_state = None
                    raise
                finally:
                    os.close(claim_fd)
                break

            try:
                current_state = os.stat(
                    self.lock_path.name,
                    dir_fd=self._root_descriptor,
                    follow_symlinks=False,
                )
                if not self._same_object(lock_state, current_state):
                    return False
                current_owner = self._owner_at(lock_fd)
                if current_owner != owner:
                    return False
                if current_owner is not None and self._pid_is_live(current_owner[0]):
                    return False

                quarantine_name = (
                    f"{self.lock_path.name}.reclaimed-{secrets.token_hex(16)}"
                )
                os.rename(
                    self.lock_path.name,
                    quarantine_name,
                    src_dir_fd=self._root_descriptor,
                    dst_dir_fd=self._root_descriptor,
                )
                claimed = True
                self._remove_tree_at(
                    self._root_descriptor,
                    quarantine_name,
                    expected=lock_state,
                )
                return True
            except FileNotFoundError:
                return True
            except OSError:
                return False
        finally:
            if not claimed and claim_state is not None:
                try:
                    current_state = os.stat(
                        self.lock_path.name,
                        dir_fd=self._root_descriptor,
                        follow_symlinks=False,
                    )
                    if (
                        self._same_object(lock_state, current_state)
                        and self._claim_owner_at(lock_fd) == (os.getpid(), claim_token)
                    ):
                        self._remove_tree_at(lock_fd, "reclaim", expected=claim_state)
                except OSError:
                    pass
            os.close(lock_fd)

    def _claim_owner_at(self, lock_fd: int) -> tuple[int, str] | None:
        state = os.stat("reclaim", dir_fd=lock_fd, follow_symlinks=False)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(state.st_mode) or bool(
            getattr(state, "st_file_attributes", 0) & reparse_point
        ):
            raise SafetyError(f"Artifact-store reclaim claim is unsafe: {self.lock_path}")
        if stat.S_ISDIR(state.st_mode):
            descriptor = self._open_directory_at(lock_fd, "reclaim", "reclaim")
            try:
                return self._owner_at(descriptor)
            finally:
                os.close(descriptor)
        if stat.S_ISREG(state.st_mode):
            return self._owner_file_at(lock_fd, "reclaim")
        return None

    def _reclaim_abandoned_claim(self, lock_fd: int) -> bool:
        try:
            claim_state = os.stat("reclaim", dir_fd=lock_fd, follow_symlinks=False)
        except FileNotFoundError:
            return True
        owner = self._claim_owner_at(lock_fd)
        if owner is not None and self._pid_is_live(owner[0]):
            return False
        if not (stat.S_ISREG(claim_state.st_mode) or stat.S_ISDIR(claim_state.st_mode)):
            return False
        if owner is None and time.time() - claim_state.st_mtime < 2.0:
            return False

        quarantine_name = f".reclaim-abandoned-{secrets.token_hex(16)}"
        try:
            current_state = os.stat("reclaim", dir_fd=lock_fd, follow_symlinks=False)
            if not self._same_object(claim_state, current_state):
                return False
            current_owner = self._claim_owner_at(lock_fd)
            if current_owner != owner:
                return False
            if current_owner is not None and self._pid_is_live(current_owner[0]):
                return False
            os.rename(
                "reclaim",
                quarantine_name,
                src_dir_fd=lock_fd,
                dst_dir_fd=lock_fd,
            )
            self._remove_tree_at(lock_fd, quarantine_name, expected=claim_state)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @contextmanager
    def _transaction_lock(self, *, timeout_seconds: float = 30.0) -> Iterator[None]:
        """Cross-process lock with conservative abandoned-owner recovery."""
        with self._lock:
            with self._advisory_transaction_lock(timeout_seconds=timeout_seconds):
                deadline = time.monotonic() + timeout_seconds
                acquired = False
                acquired_fd: int | None = None
                acquired_state: os.stat_result | None = None
                owner_token = secrets.token_hex(16)
                while not acquired:
                    try:
                        os.mkdir(
                            self.lock_path.name,
                            0o700,
                            dir_fd=self._root_descriptor,
                        )
                    except FileExistsError:
                        self._reclaim_abandoned_lock()
                        if time.monotonic() >= deadline:
                            raise SafetyError(
                                "Timed out waiting for artifact-store transaction lock: "
                                f"{self.lock_path}"
                            )
                        time.sleep(0.05)
                        continue
                    except OSError as exc:
                        raise SafetyError(
                            "Could not acquire artifact-store transaction lock: "
                            f"{self.lock_path}: {exc}"
                        ) from exc
                    try:
                        acquired_fd = self._open_lock_directory()
                        acquired_state = os.fstat(acquired_fd)
                        self._write_owner_at(acquired_fd, owner_token)
                        acquired = True
                    except (OSError, SafetyError) as exc:
                        if acquired_fd is not None and acquired_state is not None:
                            try:
                                current_state = os.stat(
                                    self.lock_path.name,
                                    dir_fd=self._root_descriptor,
                                    follow_symlinks=False,
                                )
                                current_owner = self._owner_at(acquired_fd)
                                if (
                                    self._same_object(acquired_state, current_state)
                                    and current_owner
                                    in {None, (os.getpid(), owner_token)}
                                ):
                                    self._remove_tree_at(
                                        self._root_descriptor,
                                        self.lock_path.name,
                                        expected=acquired_state,
                                    )
                            except OSError:
                                pass
                            finally:
                                os.close(acquired_fd)
                                acquired_fd = None
                        if isinstance(exc, SafetyError):
                            raise
                        raise SafetyError(
                            "Could not acquire artifact-store transaction lock: "
                            f"{self.lock_path}: {exc}"
                        ) from exc
                try:
                    yield
                finally:
                    try:
                        if acquired_fd is not None and acquired_state is not None:
                            current_state = os.stat(
                                self.lock_path.name,
                                dir_fd=self._root_descriptor,
                                follow_symlinks=False,
                            )
                            if (
                                self._same_object(acquired_state, current_state)
                                and self._owner_at(acquired_fd)
                                == (os.getpid(), owner_token)
                            ):
                                self._remove_tree_at(
                                    self._root_descriptor,
                                    self.lock_path.name,
                                    expected=acquired_state,
                                )
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        raise SafetyError(
                            "Could not release artifact-store transaction lock: "
                            f"{self.lock_path}: {exc}"
                        ) from exc
                    finally:
                        if acquired_fd is not None:
                            os.close(acquired_fd)

    def _ledger(self) -> dict:
        try:
            data = self._read_json_at(self._root_descriptor, self.ledger_path.name)
        except (OSError, ValueError) as exc:
            raise SafetyError(f"Artifact ledger is malformed: {self.ledger_path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("artifacts"), dict):
            raise SafetyError(f"Artifact ledger is malformed: {self.ledger_path}")
        return data

    def _safe_path(self, relative: str) -> tuple[str, Path]:
        value = str(relative).strip()
        if not value:
            raise SafetyError("Artifact path cannot be empty.")
        candidate = Path(value)
        if candidate.is_absolute():
            raise SafetyError(f"Artifact path must be relative: {relative}")
        normalized = candidate.as_posix()
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise SafetyError(f"Artifact path is unsafe: {relative}")
        if normalized == self.ledger_path.name or candidate.parts[0] in {
            self.lock_path.name,
            self.advisory_lock_path.name,
            self.transaction_path.name,
        }:
            raise SafetyError(f"Artifact path is reserved: {relative}")
        return normalized, self.root / candidate

    @staticmethod
    def _directory_flags() -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        return flags | getattr(os, "O_CLOEXEC", 0)

    @staticmethod
    def _same_object(first: os.stat_result, second: os.stat_result) -> bool:
        return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)

    def _open_directory_at(self, directory_fd: int, name: str, relative: str) -> int:
        try:
            descriptor = os.open(name, self._directory_flags(), dir_fd=directory_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SafetyError(
                f"Artifact path contains a symlink or unsafe directory: {relative}"
            ) from exc
        state = os.fstat(descriptor)
        if not stat.S_ISDIR(state.st_mode):
            os.close(descriptor)
            raise SafetyError(f"Artifact path contains an unsafe directory: {relative}")
        return descriptor

    def _open_parent(
        self,
        relative: str,
        *,
        create: bool,
    ) -> tuple[int, str]:
        parts = Path(relative).parts
        current_fd = os.dup(self._root_descriptor)
        try:
            for part in parts[:-1]:
                try:
                    child_fd = self._open_directory_at(current_fd, part, relative)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    child_fd = self._open_directory_at(current_fd, part, relative)
                os.close(current_fd)
                current_fd = child_fd
            return current_fd, parts[-1]
        except BaseException:
            os.close(current_fd)
            raise

    @staticmethod
    def _open_regular_at(directory_fd: int, name: str) -> int:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SafetyError(f"Artifact file is unsafe or a symlink: {name}") from exc
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
            os.close(descriptor)
            raise SafetyError(f"Artifact file is unsafe: {name}")
        return descriptor

    @staticmethod
    def _digest_descriptor(descriptor: int) -> str:
        digest = sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        while block := os.read(descriptor, 1024 * 1024):
            digest.update(block)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return digest.hexdigest()

    @staticmethod
    def _copy_descriptor(source_fd: int, destination_fd: int) -> None:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while block := os.read(source_fd, 1024 * 1024):
            remaining = memoryview(block)
            while remaining:
                written = os.write(destination_fd, remaining)
                if written <= 0:
                    raise OSError("Artifact copy made no progress.")
                remaining = remaining[written:]

    def _atomic_install_at(
        self,
        source_fd: int,
        destination_fd: int,
        destination_name: str,
    ) -> os.stat_result:
        source_state = os.fstat(source_fd)
        if not stat.S_ISREG(source_state.st_mode) or source_state.st_nlink != 1:
            raise SafetyError(f"Artifact copy source is unsafe: {destination_name}")
        temporary_name = f".{destination_name}.{secrets.token_hex(16)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        temporary_fd: int | None = None
        replaced = False
        try:
            temporary_fd = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=destination_fd,
            )
            self._copy_descriptor(source_fd, temporary_fd)
            os.fsync(temporary_fd)
            written_state = os.fstat(temporary_fd)
            if not stat.S_ISREG(written_state.st_mode) or written_state.st_nlink != 1:
                raise SafetyError(f"Artifact temporary file is unsafe: {destination_name}")
            os.replace(
                temporary_name,
                destination_name,
                src_dir_fd=destination_fd,
                dst_dir_fd=destination_fd,
            )
            replaced = True
            current = os.stat(
                destination_name,
                dir_fd=destination_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
                or not self._same_object(written_state, current)
            ):
                raise SafetyError(f"Artifact changed during replacement: {destination_name}")
            os.fsync(destination_fd)
            return current
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if not replaced:
                try:
                    os.unlink(temporary_name, dir_fd=destination_fd)
                except FileNotFoundError:
                    pass

    def _atomic_write_at(self, directory_fd: int, name: str, writer: Any) -> os.stat_result:
        with tempfile.TemporaryDirectory(prefix="manageroo-artifact-stage-") as temp:
            staged_path = Path(temp) / name
            writer(staged_path)
            stage_directory_fd = os.open(temp, self._directory_flags())
            try:
                source_fd = self._open_regular_at(stage_directory_fd, name)
            finally:
                os.close(stage_directory_fd)
            try:
                return self._atomic_install_at(source_fd, directory_fd, name)
            finally:
                os.close(source_fd)

    def _copy_at(
        self,
        source_directory_fd: int,
        source_name: str,
        destination_directory_fd: int,
        destination_name: str,
    ) -> os.stat_result:
        source_fd = self._open_regular_at(source_directory_fd, source_name)
        try:
            return self._atomic_install_at(
                source_fd,
                destination_directory_fd,
                destination_name,
            )
        finally:
            os.close(source_fd)

    def _read_json_at(self, directory_fd: int, name: str) -> Any:
        descriptor = self._open_regular_at(directory_fd, name)
        try:
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                descriptor = -1
                return json.load(handle)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _open_transaction_directory(self) -> tuple[int, os.stat_result] | None:
        try:
            descriptor = self._open_directory_at(
                self._root_descriptor,
                self.transaction_path.name,
                self.transaction_path.name,
            )
        except FileNotFoundError:
            return None
        state = os.fstat(descriptor)
        return descriptor, state

    def _create_transaction_directory(self) -> tuple[int, os.stat_result]:
        try:
            os.mkdir(self.transaction_path.name, 0o700, dir_fd=self._root_descriptor)
        except OSError as exc:
            raise SafetyError(
                f"Could not create artifact transaction: {self.transaction_path}: {exc}"
            ) from exc
        opened = self._open_transaction_directory()
        if opened is None:
            raise SafetyError(f"Artifact transaction disappeared: {self.transaction_path}")
        return opened

    def _remove_transaction_directory(
        self,
        transaction_fd: int,
        transaction_state: os.stat_result,
    ) -> None:
        for name in os.listdir(transaction_fd):
            state = os.stat(name, dir_fd=transaction_fd, follow_symlinks=False)
            if stat.S_ISDIR(state.st_mode):
                raise SafetyError(
                    f"Artifact transaction contains an unsafe directory: {name}"
                )
            os.unlink(name, dir_fd=transaction_fd)
        os.fsync(transaction_fd)
        try:
            current = os.stat(
                self.transaction_path.name,
                dir_fd=self._root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        if not self._same_object(transaction_state, current):
            raise SafetyError(f"Artifact transaction path changed: {self.transaction_path}")
        os.rmdir(self.transaction_path.name, dir_fd=self._root_descriptor)
        os.fsync(self._root_descriptor)

    @staticmethod
    def _unlink_at(directory_fd: int, name: str) -> None:
        try:
            state = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISDIR(state.st_mode):
            raise SafetyError(f"Artifact destination is an unsafe directory: {name}")
        os.unlink(name, dir_fd=directory_fd)
        os.fsync(directory_fd)

    def _verify_attached_destination(
        self,
        relative: str,
        parent_fd: int,
        name: str,
        expected: os.stat_result,
    ) -> None:
        verification_fd, verification_name = self._open_parent(relative, create=False)
        try:
            if (
                verification_name != name
                or not self._same_object(os.fstat(parent_fd), os.fstat(verification_fd))
            ):
                raise SafetyError(f"Artifact parent changed during replacement: {relative}")
            current = os.stat(name, dir_fd=verification_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
                or not self._same_object(expected, current)
            ):
                raise SafetyError(f"Artifact changed during replacement: {relative}")
        except OSError as exc:
            raise SafetyError(f"Artifact changed during replacement: {relative}") from exc
        finally:
            os.close(verification_fd)

    def _recover_transaction(
        self,
        transaction_fd: int,
        transaction_state: os.stat_result,
        *,
        artifact_target: tuple[int, str, str] | None = None,
    ) -> None:
        try:
            pending = self._read_json_at(transaction_fd, "pending.json")
        except FileNotFoundError:
            self._remove_transaction_directory(transaction_fd, transaction_state)
            return
        except (OSError, ValueError) as exc:
            raise SafetyError(
                f"Artifact transaction marker is malformed: "
                f"{self.transaction_path / 'pending.json'}"
            ) from exc
        if not isinstance(pending, dict) or type(pending.get("had_artifact")) is not bool:
            raise SafetyError(
                f"Artifact transaction marker is malformed: "
                f"{self.transaction_path / 'pending.json'}"
            )

        normalized, _ = self._safe_path(str(pending.get("path") or ""))
        if artifact_target is None:
            parent_fd, name = self._open_parent(normalized, create=True)
            close_parent = True
        else:
            supplied_fd, name, supplied_relative = artifact_target
            if supplied_relative != normalized:
                raise SafetyError("Artifact recovery target does not match transaction marker.")
            parent_fd = os.dup(supplied_fd)
            close_parent = True
        try:
            if pending["had_artifact"]:
                try:
                    restored = self._copy_at(
                        transaction_fd,
                        "artifact.before",
                        parent_fd,
                        name,
                    )
                except FileNotFoundError as exc:
                    raise SafetyError(
                        "Artifact transaction backup is missing: "
                        f"{self.transaction_path / 'artifact.before'}"
                    ) from exc
                if artifact_target is None:
                    self._verify_attached_destination(
                        normalized,
                        parent_fd,
                        name,
                        restored,
                    )
            else:
                self._unlink_at(parent_fd, name)
            try:
                self._copy_at(
                    transaction_fd,
                    "ledger.before",
                    self._root_descriptor,
                    self.ledger_path.name,
                )
            except FileNotFoundError as exc:
                raise SafetyError(
                    f"Artifact ledger backup is missing: "
                    f"{self.transaction_path / 'ledger.before'}"
                ) from exc
        except OSError as exc:
            raise SafetyError(
                f"Could not recover artifact transaction: {self.transaction_path}: {exc}"
            ) from exc
        finally:
            if close_parent:
                os.close(parent_fd)
        self._remove_transaction_directory(transaction_fd, transaction_state)

    def _recover_pending_transaction(self) -> None:
        opened = self._open_transaction_directory()
        if opened is None:
            return
        transaction_fd, transaction_state = opened
        try:
            self._recover_transaction(transaction_fd, transaction_state)
        finally:
            os.close(transaction_fd)

    def _write(self, relative: str, writer: Any, *, lock: bool) -> ArtifactRecord:
        with self._transaction_lock():
            self._recover_pending_transaction()
            normalized, _ = self._safe_path(relative)
            ledger = self._ledger()
            current = ledger.get("artifacts", {}).get(normalized)
            if current and current.get("locked"):
                raise SafetyError(f"Attempt to overwrite locked artifact: {normalized}")

            parent_fd, name = self._open_parent(normalized, create=True)
            transaction_fd, transaction_state = self._create_transaction_directory()
            try:
                self._copy_at(
                    self._root_descriptor,
                    self.ledger_path.name,
                    transaction_fd,
                    "ledger.before",
                )
                try:
                    artifact_fd = self._open_regular_at(parent_fd, name)
                except FileNotFoundError:
                    had_artifact = False
                else:
                    had_artifact = True
                    try:
                        self._atomic_install_at(
                            artifact_fd,
                            transaction_fd,
                            "artifact.before",
                        )
                    finally:
                        os.close(artifact_fd)

                with tempfile.TemporaryDirectory(
                    prefix="manageroo-artifact-writer-"
                ) as temp:
                    staged_path = Path(temp) / "artifact.after"
                    writer(staged_path)
                    stage_directory_fd = os.open(temp, self._directory_flags())
                    try:
                        staged_fd = self._open_regular_at(
                            stage_directory_fd,
                            staged_path.name,
                        )
                    finally:
                        os.close(stage_directory_fd)
                    try:
                        record = ArtifactRecord(
                            path=normalized,
                            sha256=self._digest_descriptor(staged_fd),
                            locked=lock,
                            created_at=utc_now(),
                        )
                        self._atomic_write_at(
                            transaction_fd,
                            "pending.json",
                            lambda path: atomic_write_text(
                                path,
                                json.dumps(
                                    {
                                        "had_artifact": had_artifact,
                                        "path": normalized,
                                    },
                                    sort_keys=True,
                                )
                                + "\n",
                            ),
                        )
                        installed = self._atomic_install_at(
                            staged_fd,
                            parent_fd,
                            name,
                        )
                    finally:
                        os.close(staged_fd)
                self._verify_attached_destination(
                    normalized,
                    parent_fd,
                    name,
                    installed,
                )
                ledger["artifacts"][normalized] = record.__dict__
                self._atomic_write_at(
                    self._root_descriptor,
                    self.ledger_path.name,
                    lambda path: atomic_write_json(path, ledger),
                )
                self._unlink_at(transaction_fd, "pending.json")
                self._remove_transaction_directory(transaction_fd, transaction_state)
            except Exception:
                self._recover_transaction(
                    transaction_fd,
                    transaction_state,
                    artifact_target=(parent_fd, name, normalized),
                )
                raise
            finally:
                os.close(transaction_fd)
                os.close(parent_fd)
            return record

    def write_json(self, relative: str, data: Any, *, lock: bool = False) -> ArtifactRecord:
        return self._write(relative, lambda path: atomic_write_json(path, data), lock=lock)

    def write_text(self, relative: str, text: str, *, lock: bool = False) -> ArtifactRecord:
        return self._write(relative, lambda path: atomic_write_text(path, text), lock=lock)

    def verify_locked(self) -> None:
        with self._transaction_lock():
            self._recover_pending_transaction()
            ledger = self._ledger()
            for relative, record in ledger.get("artifacts", {}).items():
                if not record.get("locked"):
                    continue
                normalized, _ = self._safe_path(relative)
                try:
                    parent_fd, name = self._open_parent(normalized, create=False)
                except (FileNotFoundError, SafetyError):
                    raise SafetyError(f"Locked artifact changed or disappeared: {relative}")
                try:
                    try:
                        descriptor = self._open_regular_at(parent_fd, name)
                    except (FileNotFoundError, SafetyError):
                        raise SafetyError(
                            f"Locked artifact changed or disappeared: {relative}"
                        ) from None
                    try:
                        digest = self._digest_descriptor(descriptor)
                    finally:
                        os.close(descriptor)
                    if digest != record["sha256"]:
                        raise SafetyError(
                            f"Locked artifact changed or disappeared: {relative}"
                        )
                finally:
                    os.close(parent_fd)
