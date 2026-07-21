from __future__ import annotations

from typing import Any

from .errors import SafetyError
from .util import read_json, sha256_text


_ALLOWED_AUTHORITIES = {
    "current_repo",
    "manageroo_run",
    "project_decision",
    "project_memory",
    "external_knowledge",
    "historical",
    "unknown",
}


def _validate_existing_evidence(path, brief: str) -> None:
    try:
        payload = read_json(path)
    except Exception as exc:
        raise SafetyError(f"Persisted discovery evidence is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SafetyError("Persisted discovery evidence must be a JSON object.")
    schema_version = payload.get("schema_version", 1)
    if schema_version != 1:
        raise SafetyError(f"Persisted discovery evidence uses unsupported schema version: {schema_version!r}")
    if str(payload.get("query") or "") != str(brief):
        raise SafetyError(
            "Persisted discovery evidence belongs to a different product brief and cannot be reused."
        )
    if payload.get("controller_authority") is not True:
        raise SafetyError("Persisted discovery evidence is missing the controller-authority marker.")
    items = payload.get("items")
    if not isinstance(items, list):
        raise SafetyError("Persisted discovery evidence items must be a list.")
    hashes: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise SafetyError(f"Persisted discovery evidence item {index} must be an object.")
        content = str(item.get("content") or "")
        supplied_hash = str(item.get("content_sha256") or "")
        if not content.strip() or not supplied_hash or sha256_text(content) != supplied_hash:
            raise SafetyError(f"Persisted discovery evidence item {index} has invalid content provenance.")
        authority = str(item.get("authority") or "")
        if authority not in _ALLOWED_AUTHORITIES:
            raise SafetyError(f"Persisted discovery evidence item {index} has invalid authority: {authority!r}")
        hashes.add(supplied_hash)
    contradictions = payload.get("contradictions", [])
    if not isinstance(contradictions, list):
        raise SafetyError("Persisted discovery evidence contradictions must be a list.")
    for index, contradiction in enumerate(contradictions):
        if not isinstance(contradiction, dict):
            raise SafetyError(f"Persisted discovery evidence contradiction {index} must be an object.")
        referenced = contradiction.get("evidence_hashes", [])
        if not isinstance(referenced, (list, tuple)) or any(str(value) not in hashes for value in referenced):
            raise SafetyError(
                f"Persisted discovery evidence contradiction {index} references missing evidence."
            )


def install_evidence_artifact_guard(orchestrator_module: Any) -> None:
    cls = orchestrator_module.Orchestrator
    original = cls._external_intelligence
    if getattr(original, "_manageroo_evidence_artifact_guard", False):
        return

    def guarded(self, brief: str, inventory: dict[str, Any]) -> dict[str, Any]:
        evidence_path = self.artifacts.root / "discovery" / "evidence.json"
        if evidence_path.is_file():
            _validate_existing_evidence(evidence_path, brief)
        result = original(self, brief, inventory)
        if evidence_path.is_file():
            _validate_existing_evidence(evidence_path, brief)
        return result

    guarded._manageroo_evidence_artifact_guard = True
    cls._external_intelligence = guarded
