from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import SafetyError
from .util import atomic_write_json, atomic_write_text, read_json, sha256_file, utc_now


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
        self.ledger_path = self.root / "artifact-ledger.json"
        self.lock_path = self.root / ".artifact-ledger.lock"
        self.transaction_path = self.root / ".artifact-ledger.transaction"
        with self._transaction_lock():
            self._recover_pending_transaction()
            if not self.ledger_path.exists():
                atomic_write_json(self.ledger_path, {"artifacts": {}})

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
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        acquired_identity: tuple[int, int] | None = None
        owner_token = secrets.token_hex(16)
        with self._lock:
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
                            f"Timed out waiting for artifact-store transaction lock: {self.lock_path}"
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
                        f"Could not acquire artifact-store transaction lock: {self.lock_path}: {exc}"
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
                        f"Could not release artifact-store transaction lock: {self.lock_path}: {exc}"
                    ) from exc

    def _ledger(self) -> dict:
        data = read_json(self.ledger_path)
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
            self.transaction_path.name,
        }:
            raise SafetyError(f"Artifact path is reserved: {relative}")
        destination = (self.root / candidate).resolve()
        try:
            destination.relative_to(self.root)
        except ValueError as exc:
            raise SafetyError(f"Artifact path escapes artifact root: {relative}") from exc
        return normalized, destination

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            dir=str(destination.parent),
        )
        try:
            with os.fdopen(fd, "wb") as destination_handle:
                with source.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, destination_handle)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _recover_pending_transaction(self) -> None:
        if self.transaction_path.is_symlink():
            raise SafetyError(
                f"Artifact transaction path is unsafe: {self.transaction_path}"
            )
        if not self.transaction_path.exists():
            return
        if not self.transaction_path.is_dir():
            raise SafetyError(
                f"Artifact transaction path is unsafe: {self.transaction_path}"
            )

        marker_path = self.transaction_path / "pending.json"
        if not marker_path.exists():
            shutil.rmtree(self.transaction_path)
            return
        try:
            pending = read_json(marker_path)
        except (OSError, ValueError) as exc:
            raise SafetyError(
                f"Artifact transaction marker is malformed: {marker_path}"
            ) from exc
        if not isinstance(pending, dict) or type(pending.get("had_artifact")) is not bool:
            raise SafetyError(f"Artifact transaction marker is malformed: {marker_path}")

        _, path = self._safe_path(str(pending.get("path") or ""))
        artifact_before = self.transaction_path / "artifact.before"
        ledger_before = self.transaction_path / "ledger.before"
        try:
            if pending["had_artifact"]:
                if not artifact_before.is_file() or artifact_before.is_symlink():
                    raise SafetyError(
                        f"Artifact transaction backup is missing: {artifact_before}"
                    )
                self._atomic_copy(artifact_before, path)
            else:
                path.unlink(missing_ok=True)
            if not ledger_before.is_file() or ledger_before.is_symlink():
                raise SafetyError(f"Artifact ledger backup is missing: {ledger_before}")
            self._atomic_copy(ledger_before, self.ledger_path)
        except OSError as exc:
            raise SafetyError(
                f"Could not recover artifact transaction: {self.transaction_path}: {exc}"
            ) from exc
        shutil.rmtree(self.transaction_path)

    def _write(self, relative: str, writer: Any, *, lock: bool) -> ArtifactRecord:
        with self._transaction_lock():
            self._recover_pending_transaction()
            normalized, path = self._safe_path(relative)
            ledger = self._ledger()
            current = ledger.get("artifacts", {}).get(normalized)
            if current and current.get("locked"):
                raise SafetyError(f"Attempt to overwrite locked artifact: {normalized}")

            self.transaction_path.mkdir()
            staged_path = self.transaction_path / "artifact.after"
            marker_path = self.transaction_path / "pending.json"
            try:
                self._atomic_copy(self.ledger_path, self.transaction_path / "ledger.before")
                had_artifact = path.exists()
                if had_artifact:
                    self._atomic_copy(path, self.transaction_path / "artifact.before")
                writer(staged_path)
                record = ArtifactRecord(
                    path=normalized,
                    sha256=sha256_file(staged_path),
                    locked=lock,
                    created_at=utc_now(),
                )
                atomic_write_text(
                    marker_path,
                    json.dumps(
                        {"had_artifact": had_artifact, "path": normalized},
                        sort_keys=True,
                    )
                    + "\n",
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, path)
                ledger["artifacts"][normalized] = record.__dict__
                atomic_write_json(self.ledger_path, ledger)
                marker_path.unlink()
            except Exception:
                self._recover_pending_transaction()
                raise
            shutil.rmtree(self.transaction_path, ignore_errors=True)
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
                _, path = self._safe_path(relative)
                if not path.exists() or sha256_file(path) != record["sha256"]:
                    raise SafetyError(f"Locked artifact changed or disappeared: {relative}")
