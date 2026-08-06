from __future__ import annotations

import errno
import json
import os
import secrets
import shutil
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
        self.root = root.expanduser().resolve()
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
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
        descriptor = os.open(self.root, flags)
        try:
            descriptor_state = os.fstat(descriptor)
            path_state = os.stat(self.root, follow_symlinks=False)
            if (
                not stat.S_ISDIR(descriptor_state.st_mode)
                or (descriptor_state.st_dev, descriptor_state.st_ino)
                != (path_state.st_dev, path_state.st_ino)
            ):
                raise SafetyError(f"Artifact root changed while opening: {self.root}")
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

    @classmethod
    def _directory_owner(cls, directory: Path) -> tuple[int, str] | None:
        try:
            lines = (directory / "owner").read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        return cls._owner_from_lines(lines)

    @classmethod
    def _claim_owner(cls, claim_path: Path) -> tuple[int, str] | None:
        if claim_path.is_dir() and not claim_path.is_symlink():
            return cls._directory_owner(claim_path)
        try:
            if claim_path.is_symlink() or not claim_path.is_file():
                return None
            lines = claim_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        return cls._owner_from_lines(lines)

    def _lock_owner(self) -> tuple[int, str] | None:
        return self._directory_owner(self.lock_path)

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
        path_state = self.advisory_lock_path.lstat()
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
            descriptor = os.open(self.advisory_lock_path, flags, 0o600)
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
        owner = self._lock_owner()
        if owner is not None and self._pid_is_live(owner[0]):
            return False
        # Unknown-owner lock directories are reclaimable only after a short age guard,
        # which avoids stealing one during the tiny mkdir -> owner-write window.
        try:
            lock_stat = self.lock_path.stat()
            age = time.time() - lock_stat.st_mtime
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if owner is None and age < 2.0:
            return False

        claim_path = self.lock_path / "reclaim"
        while True:
            claim_token = secrets.token_hex(16)
            try:
                claim_path.mkdir()
                atomic_write_text(
                    claim_path / "owner",
                    (
                        f"pid={os.getpid()}\ntoken={claim_token}\n"
                        f"created_at={utc_now()}\n"
                    ),
                )
                break
            except FileNotFoundError:
                return True
            except FileExistsError:
                if not self._reclaim_abandoned_claim(claim_path):
                    return False
            except OSError:
                return False

        lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
        claimed = False
        try:
            current_stat = self.lock_path.stat()
            if (current_stat.st_dev, current_stat.st_ino) != lock_identity:
                return False
            current_owner = self._lock_owner()
            if current_owner != owner:
                return False
            if current_owner is not None and self._pid_is_live(current_owner[0]):
                return False

            quarantine = self.root / f"{self.lock_path.name}.reclaimed-{secrets.token_hex(16)}"
            os.rename(self.lock_path, quarantine)
            claimed = True
            shutil.rmtree(quarantine, ignore_errors=True)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False
        finally:
            if not claimed:
                try:
                    current_stat = self.lock_path.stat()
                    if (
                        (current_stat.st_dev, current_stat.st_ino) == lock_identity
                        and self._claim_owner(claim_path) == (os.getpid(), claim_token)
                    ):
                        shutil.rmtree(claim_path)
                except OSError:
                    pass

    def _reclaim_abandoned_claim(self, claim_path: Path) -> bool:
        owner = self._claim_owner(claim_path)
        if owner is not None and self._pid_is_live(owner[0]):
            return False
        try:
            if claim_path.is_symlink() or not (claim_path.is_file() or claim_path.is_dir()):
                return False
            claim_stat = claim_path.stat()
            if owner is None and time.time() - claim_stat.st_mtime < 2.0:
                return False
        except FileNotFoundError:
            return True
        except OSError:
            return False

        claim_identity = (claim_stat.st_dev, claim_stat.st_ino)
        quarantine = self.lock_path / f".reclaim-abandoned-{secrets.token_hex(16)}"
        try:
            current_stat = claim_path.stat()
            if (current_stat.st_dev, current_stat.st_ino) != claim_identity:
                return False
            current_owner = self._claim_owner(claim_path)
            if current_owner != owner:
                return False
            if current_owner is not None and self._pid_is_live(current_owner[0]):
                return False
            os.rename(claim_path, quarantine)
            if quarantine.is_dir():
                shutil.rmtree(quarantine, ignore_errors=True)
            else:
                quarantine.unlink(missing_ok=True)
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
                acquired_identity: tuple[int, int] | None = None
                owner_token = secrets.token_hex(16)
                while not acquired:
                    try:
                        self.lock_path.mkdir()
                        acquired = True
                        lock_stat = self.lock_path.stat()
                        acquired_identity = (lock_stat.st_dev, lock_stat.st_ino)
                        (self.lock_path / "owner").write_text(
                            f"pid={os.getpid()}\ntoken={owner_token}\ncreated_at={utc_now()}\n",
                            encoding="utf-8",
                        )
                    except FileExistsError:
                        self._reclaim_abandoned_lock()
                        if time.monotonic() >= deadline:
                            raise SafetyError(
                                "Timed out waiting for artifact-store transaction lock: "
                                f"{self.lock_path}"
                            )
                        time.sleep(0.05)
                    except OSError as exc:
                        if acquired and acquired_identity is not None:
                            try:
                                current_stat = self.lock_path.stat()
                                current_identity = (current_stat.st_dev, current_stat.st_ino)
                                current_owner = self._lock_owner()
                                if current_identity == acquired_identity and current_owner in {
                                    None,
                                    (os.getpid(), owner_token),
                                }:
                                    shutil.rmtree(self.lock_path, ignore_errors=True)
                            except OSError:
                                pass
                        raise SafetyError(
                            "Could not acquire artifact-store transaction lock: "
                            f"{self.lock_path}: {exc}"
                        ) from exc
                try:
                    yield
                finally:
                    try:
                        if self._lock_owner() == (os.getpid(), owner_token):
                            shutil.rmtree(self.lock_path)
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        raise SafetyError(
                            "Could not release artifact-store transaction lock: "
                            f"{self.lock_path}: {exc}"
                        ) from exc

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
