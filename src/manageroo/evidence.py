"""Manageroo evidence retrieval primitives.

Evidence is not memory and is not an authority layer. Providers return
traceable evidence; Manageroo decides what evidence is acceptable for a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class EvidenceItem:
    content: str
    source: str
    location: str = ""
    authority: str = "unknown"
    confidence: float = 0.0
    freshness: float = 0.0
    created_at: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def score(self) -> float:
        authority_weight = {
            "current_repo": 1.0,
            "manageroo_run": 0.95,
            "project_decision": 0.85,
            "external_knowledge": 0.55,
            "historical": 0.25,
        }.get(self.authority, 0.1)
        return (authority_weight * 0.5) + (self.confidence * 0.3) + (self.freshness * 0.2)


class EvidenceProvider(Protocol):
    name: str

    def retrieve(self, query: str) -> list[EvidenceItem]:
        ...


def rank_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Rank evidence without changing provenance or hiding conflicts."""
    return sorted(items, key=lambda item: item.score(), reverse=True)


def evidence_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
