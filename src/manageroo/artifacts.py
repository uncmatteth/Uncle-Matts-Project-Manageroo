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
        self.root = root.expanduser().resolve()
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "artifact-ledger.json"
        if not self.ledger_path.exists():
            atomic_write_json(self.ledger_path, {"artifacts": {}})

    def _ledger(self) -> dict:
        return read_json(self.ledger_path)

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

    def _record(self, relative: str, locked: bool) -> ArtifactRecord:
        with self._lock:
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

    def write_json(self, relative: str, data: Any, *, lock: bool = False) -> ArtifactRecord:
        with self._lock:
            normalized, path = self._safe_path(relative)
            if path.exists():
                current = self._ledger().get("artifacts", {}).get(normalized)
                if current and current.get("locked"):
                    raise SafetyError(f"Attempt to overwrite locked artifact: {normalized}")
            atomic_write_json(path, data)
            return self._record(normalized, lock)

    def write_text(self, relative: str, text: str, *, lock: bool = False) -> ArtifactRecord:
        with self._lock:
            normalized, path = self._safe_path(relative)
            if path.exists():
                current = self._ledger().get("artifacts", {}).get(normalized)
                if current and current.get("locked"):
                    raise SafetyError(f"Attempt to overwrite locked artifact: {normalized}")
            atomic_write_text(path, text)
            return self._record(normalized, lock)

    def verify_locked(self) -> None:
        with self._lock:
            ledger = self._ledger()
            for relative, record in ledger.get("artifacts", {}).items():
                if not record.get("locked"):
                    continue
                _, path = self._safe_path(relative)
                if not path.exists() or sha256_file(path) != record["sha256"]:
                    raise SafetyError(f"Locked artifact changed or disappeared: {relative}")
