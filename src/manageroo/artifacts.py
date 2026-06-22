from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        self.root = root
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = root / "artifact-ledger.json"
        if not self.ledger_path.exists():
            atomic_write_json(self.ledger_path, {"artifacts": {}})

    def _ledger(self) -> dict:
        return read_json(self.ledger_path)

    def path(self, relative: str) -> Path:
        return self.root / relative

    def exists(self, relative: str) -> bool:
        return self.path(relative).is_file()

    def read_json(self, relative: str) -> Any:
        return read_json(self.path(relative))

    def read_text(self, relative: str) -> str:
        return self.path(relative).read_text(encoding="utf-8")

    def _record(self, relative: str, locked: bool) -> ArtifactRecord:
        with self._lock:
            path = self.root / relative
            record = ArtifactRecord(
                path=relative,
                sha256=sha256_file(path),
                locked=locked,
                created_at=utc_now(),
            )
            ledger = self._ledger()
            ledger["artifacts"][relative] = record.__dict__
            atomic_write_json(self.ledger_path, ledger)
            return record

    def write_json(self, relative: str, data: Any, *, lock: bool = False) -> ArtifactRecord:
        with self._lock:
            path = self.root / relative
            if path.exists():
                current = self._ledger().get("artifacts", {}).get(relative)
                if current and current.get("locked"):
                    raise SafetyError(f"Attempt to overwrite locked artifact: {relative}")
            atomic_write_json(path, data)
            return self._record(relative, lock)

    def write_text(self, relative: str, text: str, *, lock: bool = False) -> ArtifactRecord:
        with self._lock:
            path = self.root / relative
            if path.exists():
                current = self._ledger().get("artifacts", {}).get(relative)
                if current and current.get("locked"):
                    raise SafetyError(f"Attempt to overwrite locked artifact: {relative}")
            atomic_write_text(path, text)
            return self._record(relative, lock)

    def verify_locked(self) -> None:
        with self._lock:
            ledger = self._ledger()
            for relative, record in ledger.get("artifacts", {}).items():
                if not record.get("locked"):
                    continue
                path = self.root / relative
                if not path.exists() or sha256_file(path) != record["sha256"]:
                    raise SafetyError(f"Locked artifact changed or disappeared: {relative}")
