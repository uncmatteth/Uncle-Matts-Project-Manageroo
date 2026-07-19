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


def _bundle_from_discovery(orchestrator, brief: str, payload: dict[str, Any]) -> EvidenceBundle:
    items = []
    items.extend(ProjectMemoryEvidenceProvider(orchestrator.source_repo).retrieve(brief, limit=4))
    items.extend(RunArtifactEvidenceProvider(orchestrator.run_root).retrieve(brief, limit=8))

    for record in payload.get("records", []):
        if not isinstance(record, dict) or not record.get("ok"):
            continue
        stdout = str(record.get("stdout") or "").strip()
        if not stdout:
            continue
        name = str(record.get("name") or "external-evidence")
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
        provider_errors=[],
    )


def install_evidence_policy(orchestrator_module) -> None:
    original = orchestrator_module.Orchestrator._external_intelligence
    if getattr(original, "_manageroo_evidence_policy", False):
        return

    def _external_intelligence_with_evidence(self, brief: str, inventory: dict[str, Any]) -> dict[str, Any]:
        payload = original(self, brief, inventory)
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
        return {
            **payload,
            "evidence_bundle": evidence_payload,
            "note": (
                str(payload.get("note") or "")
                + " Retrieved evidence is provenance-ranked context only; Manageroo remains the completion authority."
            ).strip(),
        }

    _external_intelligence_with_evidence._manageroo_evidence_policy = True
    orchestrator_module.Orchestrator._external_intelligence = _external_intelligence_with_evidence
