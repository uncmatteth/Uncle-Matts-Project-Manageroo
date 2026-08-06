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
    if schema_version not in {1, 2}:
        raise SafetyError(f"Persisted discovery evidence uses unsupported schema version: {schema_version!r}")
    if schema_version == 2:
        identity = str(payload.get("discovery_identity") or "")
        if len(identity) != 64 or any(character not in "0123456789abcdef" for character in identity):
            raise SafetyError("Persisted discovery evidence has an invalid discovery identity.")
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
        if not isinstance(contradiction.get("claim_key"), str) or not isinstance(
            contradiction.get("reason"), str
        ):
            raise SafetyError(
                f"Persisted discovery evidence contradiction {index} has invalid text fields."
            )
        referenced = contradiction.get("evidence_hashes", [])
        if not isinstance(referenced, (list, tuple)):
            raise SafetyError(
                f"Persisted discovery evidence contradiction {index} has invalid evidence hashes."
            )
        referenced_hashes = [str(value) for value in referenced]
        referenced_set = set(referenced_hashes)
        if (
            len(referenced_set) < 2
            or len(referenced_set) != len(referenced_hashes)
            or any(value not in hashes for value in referenced_set)
        ):
            raise SafetyError(
                f"Persisted discovery evidence contradiction {index} has invalid evidence hashes."
            )
        preferred = contradiction.get("preferred_hash")
        if not isinstance(preferred, str) or not preferred or preferred not in referenced_set:
            raise SafetyError(
                f"Persisted discovery evidence contradiction {index} has invalid preferred evidence."
            )


def install_evidence_artifact_guard(orchestrator_module: Any) -> None:
    cls = orchestrator_module.Orchestrator
    if getattr(cls, "_manageroo_evidence_artifact_guard_installed", False):
        return
    original = cls._external_intelligence

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
    cls._manageroo_evidence_artifact_guard_installed = True
