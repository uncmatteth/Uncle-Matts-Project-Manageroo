"""Controller integration for provenance-aware discovery evidence.

This module keeps the large orchestrator focused on lifecycle control. It normalizes the
existing GitNexus/GBrain command-owned discovery lanes plus native Manageroo evidence into
one ranked artifact. Retrieval informs planning; it never owns completion.
"""

from __future__ import annotations

from typing import Any

from .evidence import (
    EvidenceBundle,
    ProjectMemoryEvidenceProvider,
    RunArtifactEvidenceProvider,
    detect_contradictions,
    normalize_external_payload,
    rank_evidence,
)


PLANNING_EVIDENCE_ROLES = {
    "product-analyst",
    "reuse-researcher",
    "plan-compiler",
    "plan-reviewer",
}
PLANNING_EVIDENCE_LIMIT = 8
PLANNING_EVIDENCE_CONTENT_CHARS = 4_000


def _bundle_from_discovery(orchestrator, brief: str, payload: dict[str, Any]) -> EvidenceBundle:
    items = []
    provider_errors: list[dict[str, str]] = []
    items.extend(ProjectMemoryEvidenceProvider(orchestrator.source_repo).retrieve(brief, limit=4))
    items.extend(RunArtifactEvidenceProvider(orchestrator.run_root).retrieve(brief, limit=8))

    for record in payload.get("records", []):
        if not isinstance(record, dict) or not record.get("enabled"):
            continue
        name = str(record.get("name") or "external-evidence")
        if not record.get("ok"):
            provider_errors.append(
                {
                    "provider": name,
                    "error_type": str(record.get("error_type") or "CommandFailure"),
                    "error": str(record.get("error") or record.get("stderr") or "provider command failed")[:2000],
                }
            )
            continue
        stdout = str(record.get("stdout") or "").strip()
        if not stdout:
            continue
        if name.startswith("gitnexus"):
            authority = "current_repo"
            confidence = 0.92
            freshness = 1.0
        elif name.startswith("gbrain"):
            authority = "external_knowledge"
            confidence = 0.78
            freshness = 0.75
        else:
            authority = "external_knowledge"
            confidence = 0.70
            freshness = 0.70
        items.extend(
            normalize_external_payload(
                provider=name,
                payload=stdout,
                authority=authority,
                confidence=confidence,
                freshness=freshness,
                limit=12,
            )
        )

    ranked = rank_evidence(items)[:24]
    return EvidenceBundle(
        query=brief,
        items=ranked,
        contradictions=detect_contradictions(items),
        provider_errors=provider_errors,
    )


def _planning_items(evidence_payload: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in list(evidence_payload.get("items", []) or [])[:PLANNING_EVIDENCE_LIMIT]:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        original_content = str(item.get("content") or "")
        item["content"] = original_content[:PLANNING_EVIDENCE_CONTENT_CHARS]
        if item["content"] != original_content:
            item.pop("content_sha256", None)
            item["metadata"] = {
                **(dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}),
                "planning_excerpt": True,
            }
        selected.append(item)
    return selected


def _evidence_summary(orchestrator, evidence_payload: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in evidence_payload.get("items", []) if isinstance(item, dict)]
    contradictions = [
        item for item in evidence_payload.get("contradictions", []) if isinstance(item, dict)
    ]
    provider_errors = [
        item for item in evidence_payload.get("provider_errors", []) if isinstance(item, dict)
    ]
    return {
        "artifact": str(orchestrator.artifacts.root / "discovery" / "evidence.json"),
        "item_count": len(items),
        "contradiction_count": len(contradictions),
        "provider_error_count": len(provider_errors),
        "top_sources": list(dict.fromkeys(str(item.get("source") or "unknown") for item in items))[:8],
        "controller_authority": True,
        "context_only": True,
    }


def install_evidence_policy(orchestrator_module) -> None:
    original_external = orchestrator_module.Orchestrator._external_intelligence
    original_call = orchestrator_module.Orchestrator._call
    if getattr(original_external, "_manageroo_evidence_policy", False):
        return

    def _external_intelligence_with_evidence(self, brief: str, inventory: dict[str, Any]) -> dict[str, Any]:
        payload = original_external(self, brief, inventory)
        existing = self._artifact_json("discovery/evidence.json")
        if existing is None:
            bundle = _bundle_from_discovery(self, brief, payload)
            evidence_payload = {
                **bundle.to_dict(),
                "authority_rule": (
                    "Current repository evidence outranks run evidence, explicit project knowledge, "
                    "and historical external knowledge. Retrieval never overrides controller proof."
                ),
                "controller_authority": True,
            }
            self.artifacts.write_json("discovery/evidence.json", evidence_payload, lock=True)
        else:
            evidence_payload = existing
        self._planning_evidence_items = _planning_items(evidence_payload)
        return {
            **payload,
            "evidence_bundle": _evidence_summary(self, evidence_payload),
            "note": (
                str(payload.get("note") or "")
                + " Retrieved evidence is provenance-ranked context only; Manageroo remains the completion authority."
            ).strip(),
        }

    def _call_with_evidence(self, *args, **kwargs):
        role = str(kwargs.get("role") or "")
        if role in PLANNING_EVIDENCE_ROLES:
            evidence_items = list(getattr(self, "_planning_evidence_items", []) or [])
            if evidence_items:
                metadata = dict(kwargs.get("metadata") or {})
                metadata["_evidence_items"] = evidence_items
                metadata["_evidence_policy"] = {
                    "source": "discovery/evidence.json",
                    "context_only": True,
                    "controller_authority": True,
                }
                kwargs["metadata"] = metadata
        return original_call(self, *args, **kwargs)

    _external_intelligence_with_evidence._manageroo_evidence_policy = True
    _call_with_evidence._manageroo_evidence_policy = True
    orchestrator_module.Orchestrator._external_intelligence = _external_intelligence_with_evidence
    orchestrator_module.Orchestrator._call = _call_with_evidence
