"""Manageroo evidence retrieval primitives.

Evidence is not memory and is not an authority layer. Providers return
traceable evidence; Manageroo decides what evidence is acceptable for a run.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from .branding import PROJECT_DIR
from .integrations import ExternalCommandIntegration
from .runner import CommandRunner


AUTHORITY_WEIGHTS: dict[str, float] = {
    "current_repo": 1.0,
    "manageroo_run": 0.95,
    "project_decision": 0.90,
    "project_memory": 0.80,
    "external_knowledge": 0.55,
    "historical": 0.25,
    "unknown": 0.10,
}
MAX_EVIDENCE_CONTENT_CHARS = 12_000


def evidence_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _query_terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_.:/-]{3,}", query)}


@dataclass(frozen=True)
class EvidenceItem:
    content: str
    source: str
    location: str = ""
    authority: str = "unknown"
    confidence: float = 0.0
    freshness: float = 0.0
    created_at: str | None = None
    retrieved_at: str = field(default_factory=evidence_timestamp)
    content_sha256: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        content = str(self.content)
        if not content.strip():
            raise ValueError("Evidence content cannot be empty.")
        object.__setattr__(self, "confidence", _clamp(self.confidence))
        object.__setattr__(self, "freshness", _clamp(self.freshness))
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", _sha256_text(content))

    def score(self) -> float:
        authority_weight = AUTHORITY_WEIGHTS.get(self.authority, AUTHORITY_WEIGHTS["unknown"])
        return (authority_weight * 0.55) + (self.confidence * 0.25) + (self.freshness * 0.20)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["score"] = round(self.score(), 6)
        return payload


@dataclass(frozen=True)
class EvidenceContradiction:
    claim_key: str
    evidence_hashes: tuple[str, ...]
    sources: tuple[str, ...]
    preferred_hash: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBundle:
    query: str
    items: list[EvidenceItem]
    contradictions: list[EvidenceContradiction] = field(default_factory=list)
    provider_errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "items": [item.to_dict() for item in self.items],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "provider_errors": list(self.provider_errors),
        }


class EvidenceProvider(Protocol):
    name: str

    def retrieve(self, query: str, *, limit: int = 12) -> list[EvidenceItem]:
        ...


def rank_evidence(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    """Rank evidence without changing provenance or hiding conflicts."""
    return sorted(
        items,
        key=lambda item: (
            item.score(),
            AUTHORITY_WEIGHTS.get(item.authority, AUTHORITY_WEIGHTS["unknown"]),
            item.retrieved_at,
            item.content_sha256,
        ),
        reverse=True,
    )


def detect_contradictions(items: Iterable[EvidenceItem]) -> list[EvidenceContradiction]:
    """Surface conflicting claims when providers supply a shared claim_key.

    Manageroo never guesses semantic contradictions from arbitrary prose. Providers must
    attach metadata.claim_key when two records are intended to describe the same fact.
    """
    grouped: dict[str, list[EvidenceItem]] = {}
    for item in items:
        claim_key = str(item.metadata.get("claim_key") or "").strip()
        if claim_key:
            grouped.setdefault(claim_key, []).append(item)
    contradictions: list[EvidenceContradiction] = []
    for claim_key, group in grouped.items():
        distinct = {item.content_sha256 for item in group}
        if len(distinct) <= 1:
            continue
        ranked = rank_evidence(group)
        contradictions.append(
            EvidenceContradiction(
                claim_key=claim_key,
                evidence_hashes=tuple(sorted(distinct)),
                sources=tuple(sorted({item.source for item in group})),
                preferred_hash=ranked[0].content_sha256,
                reason=(
                    "Conflicting evidence was preserved. The preferred item ranks higher by "
                    "authority, confidence, and freshness; it does not erase lower-ranked evidence."
                ),
            )
        )
    return contradictions


class ProjectMemoryEvidenceProvider:
    name = "project-memory"

    def __init__(self, repo: Path):
        self.repo = repo.expanduser().resolve()

    def retrieve(self, query: str, *, limit: int = 12) -> list[EvidenceItem]:
        path = self.repo / PROJECT_DIR / "PROJECT-MEMORY.md"
        if not path.is_file():
            return []
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        terms = _query_terms(query)
        lowered = content.lower()
        relevance = sum(lowered.count(term) for term in terms)
        if terms and relevance == 0:
            return []
        return [
            EvidenceItem(
                content=content[:MAX_EVIDENCE_CONTENT_CHARS],
                source=self.name,
                location=str(path.relative_to(self.repo)),
                authority="project_memory",
                confidence=0.90,
                freshness=0.85,
                created_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                metadata={"relevance_hits": relevance, "provider": self.name},
            )
        ]


class RunArtifactEvidenceProvider:
    name = "manageroo-run-artifacts"

    def __init__(self, run_root: Path):
        self.run_root = run_root.expanduser().resolve()
        self.artifact_root = self.run_root / "artifacts"

    def retrieve(self, query: str, *, limit: int = 12) -> list[EvidenceItem]:
        if not self.artifact_root.is_dir():
            return []
        terms = _query_terms(query)
        candidates: list[tuple[int, float, Path, str]] = []
        for path in self.artifact_root.rglob("*"):
            if len(candidates) >= max(limit * 20, 100):
                break
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".json", ".md", ".txt"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lowered = (path.as_posix() + "\n" + text).lower()
            relevance = sum(lowered.count(term) for term in terms)
            if terms and relevance == 0:
                continue
            candidates.append((relevance, path.stat().st_mtime, path, text))
        candidates.sort(key=lambda row: (row[0], row[1], row[2].as_posix()), reverse=True)
        items: list[EvidenceItem] = []
        for relevance, mtime, path, text in candidates[:limit]:
            items.append(
                EvidenceItem(
                    content=text[:MAX_EVIDENCE_CONTENT_CHARS],
                    source=self.name,
                    location=str(path.relative_to(self.run_root)),
                    authority="manageroo_run",
                    confidence=0.98,
                    freshness=0.95,
                    created_at=datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                    metadata={"relevance_hits": relevance, "provider": self.name},
                )
            )
        return items


class ExternalCommandEvidenceProvider:
    """Adapter for configured GitNexus/GBrain-style argv-only evidence commands."""

    def __init__(
        self,
        *,
        name: str,
        argv_template: Iterable[str],
        runner: CommandRunner,
        cwd: Path,
        base_values: dict[str, str] | None = None,
        authority: str = "external_knowledge",
        confidence: float = 0.75,
        freshness: float = 0.70,
    ):
        self.name = name
        self.integration = ExternalCommandIntegration(argv_template, runner)
        self.cwd = cwd.expanduser().resolve()
        self.base_values = dict(base_values or {})
        self.authority = authority
        self.confidence = confidence
        self.freshness = freshness

    def retrieve(self, query: str, *, limit: int = 12) -> list[EvidenceItem]:
        if not self.integration.enabled:
            return []
        values = {**self.base_values, "query": query}
        result = self.integration.run(
            cwd=self.cwd,
            values=values,
            timeout_seconds=300,
            log_name=f"evidence-{self.name}",
        )
        if result is None or not result.passed or not (result.stdout or "").strip():
            return []
        stdout = (result.stdout or "").strip()
        return normalize_external_payload(
            provider=self.name,
            payload=stdout,
            authority=self.authority,
            confidence=self.confidence,
            freshness=self.freshness,
            limit=limit,
        )


def normalize_external_payload(
    *,
    provider: str,
    payload: str,
    authority: str = "external_knowledge",
    confidence: float = 0.75,
    freshness: float = 0.70,
    limit: int = 12,
) -> list[EvidenceItem]:
    """Normalize plain text or JSON provider output without inventing provenance."""
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        decoded = None

    rows: list[dict[str, Any]] = []
    if isinstance(decoded, dict) and isinstance(decoded.get("items"), list):
        rows = [item for item in decoded["items"] if isinstance(item, dict)]
    elif isinstance(decoded, list):
        rows = [item for item in decoded if isinstance(item, dict)]

    if not rows:
        return [
            EvidenceItem(
                content=payload[:MAX_EVIDENCE_CONTENT_CHARS],
                source=provider,
                authority=authority,
                confidence=confidence,
                freshness=freshness,
                metadata={"provider": provider, "format": "text"},
            )
        ]

    items: list[EvidenceItem] = []
    for row in rows[:limit]:
        content = str(row.get("content") or row.get("text") or row.get("excerpt") or "").strip()
        if not content:
            continue
        metadata = dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {}
        if row.get("claim_key"):
            metadata["claim_key"] = str(row["claim_key"])
        metadata.setdefault("provider", provider)
        items.append(
            EvidenceItem(
                content=content[:MAX_EVIDENCE_CONTENT_CHARS],
                source=str(row.get("source") or provider),
                location=str(row.get("location") or row.get("path") or ""),
                authority=str(row.get("authority") or authority),
                confidence=float(row.get("confidence", confidence)),
                freshness=float(row.get("freshness", freshness)),
                created_at=str(row.get("created_at")) if row.get("created_at") else None,
                metadata=metadata,
            )
        )
    return items


class EvidenceRouter:
    """Queries independent providers and returns ranked, provenance-preserving evidence."""

    def __init__(self, providers: Iterable[EvidenceProvider]):
        self.providers = list(providers)

    def retrieve(self, query: str, *, limit: int = 20, per_provider_limit: int = 12) -> EvidenceBundle:
        items: list[EvidenceItem] = []
        errors: list[dict[str, str]] = []
        for provider in self.providers:
            try:
                items.extend(provider.retrieve(query, limit=per_provider_limit))
            except Exception as exc:
                errors.append(
                    {
                        "provider": str(getattr(provider, "name", type(provider).__name__)),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        ranked = rank_evidence(items)[:limit]
        return EvidenceBundle(
            query=query,
            items=ranked,
            contradictions=detect_contradictions(items),
            provider_errors=errors,
        )
