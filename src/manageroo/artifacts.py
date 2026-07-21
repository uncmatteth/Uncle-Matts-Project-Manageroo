from __future__ import annotations

import os
import shutil
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
        with self._transaction_lock():
            if not self.ledger_path.exists():
                atomic_write_json(self.ledger_path, {"artifacts": {}})

    def _lock_owner_pid(self) -> int | None:
        owner = self.lock_path / "owner"
        try:
            lines = owner.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            if line.startswith("pid="):
                try:
                    pid = int(line.split("=", 1)[1])
                except ValueError:
                    return None
                return pid if pid > 0 else None
        return None

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        if pid == os.getpid():
            return True
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
        pid = self._lock_owner_pid()
        if pid is not None and self._pid_is_live(pid):
            return False
        # Unknown-owner lock directories are reclaimable only after a short age guard,
        # which avoids stealing one during the tiny mkdir -> owner-write window.
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except OSError:
            return True
        if pid is None and age < 2.0:
            return False
        pid = self._lock_owner_pid()
        if pid is not None and self._pid_is_live(pid):
            return False
        try:
            shutil.rmtree(self.lock_path)
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
        with self._lock:
            while not acquired:
                try:
                    self.lock_path.mkdir()
                    acquired = True
                    (self.lock_path / "owner").write_text(
                        f"pid={os.getpid()}\ncreated_at={utc_now()}\n",
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
                    if acquired:
                        shutil.rmtree(self.lock_path, ignore_errors=True)
                    raise SafetyError(
                        f"Could not acquire artifact-store transaction lock: {self.lock_path}: {exc}"
                    ) from exc
            try:
                yield
            finally:
                try:
                    if self._lock_owner_pid() == os.getpid():
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
        destination = (self.root / candidate).resolve()
        try:
            destination.relative_to(self.root)
        except ValueError as exc:
            raise SafetyError(f"Artifact path escapes artifact root: {relative}") from exc
        return normalized, destination

    def _record_locked_transaction(self, relative: str, locked: bool) -> ArtifactRecord:
        normalized, path = self._safe_path(relative)
        record = ArtifactRecord(
            path=normalized,
            sha256=sha256_file(path),
            locked=locked,
            created_at=utc_now(),
        )
        ledger = self._ledger()
        ledger["artifacts"][normalized] = record.__dict__
        atomic_write_json(self.ledger_path, ledger)
        return record

    def _write(self, relative: str, writer: Any, *, lock: bool) -> ArtifactRecord:
        with self._transaction_lock():
            normalized, path = self._safe_path(relative)
            current = self._ledger().get("artifacts", {}).get(normalized)
            if current and current.get("locked"):
                raise SafetyError(f"Attempt to overwrite locked artifact: {normalized}")
            writer(path)
            return self._record_locked_transaction(normalized, lock)

    def write_json(self, relative: str, data: Any, *, lock: bool = False) -> ArtifactRecord:
        return self._write(relative, lambda path: atomic_write_json(path, data), lock=lock)

    def write_text(self, relative: str, text: str, *, lock: bool = False) -> ArtifactRecord:
        return self._write(relative, lambda path: atomic_write_text(path, text), lock=lock)

    def verify_locked(self) -> None:
        with self._transaction_lock():
            ledger = self._ledger()
            for relative, record in ledger.get("artifacts", {}).items():
                if not record.get("locked"):
                    continue
                _, path = self._safe_path(relative)
                if not path.exists() or sha256_file(path) != record["sha256"]:
                    raise SafetyError(f"Locked artifact changed or disappeared: {relative}")
