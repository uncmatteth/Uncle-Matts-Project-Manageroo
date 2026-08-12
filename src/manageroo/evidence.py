"""Manageroo evidence retrieval primitives.

Evidence is not memory and is not an authority layer. Providers return
traceable evidence; Manageroo decides what evidence is acceptable for a run.
"""

from __future__ import annotations

import hashlib
import json
import os
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
MAX_EVIDENCE_INPUT_BYTES = 256_000
EVIDENCE_SUFFIXES = {".json", ".md", ".txt"}
DERIVED_RUN_ARTIFACTS = {
    "artifacts/discovery/document-intelligence.json",
    "artifacts/discovery/evidence.json",
    "artifacts/discovery/external-intelligence.json",
    "artifacts/discovery/unknown-unknowns-preflight.json",
}


def evidence_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return fallback
    return parsed


def _query_terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9_.:/-]{3,}", query)}


def _read_bounded_text(
    path: Path,
    *,
    max_bytes: int = MAX_EVIDENCE_INPUT_BYTES,
) -> tuple[str, float] | None:
    """Read a bounded UTF-8 prefix from a caller-trusted path."""
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as handle:
            payload = handle.read(max_bytes + 1)
            opened = os.fstat(handle.fileno())
    except OSError:
        return None
    payload = payload[:max_bytes]
    try:
        return payload.decode("utf-8"), opened.st_mtime
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data" and exc.start >= max(0, len(payload) - 4):
            try:
                return payload[: exc.start].decode("utf-8"), opened.st_mtime
            except UnicodeDecodeError:
                return None
        return None


def _is_derived_run_artifact(run_root: Path, candidate: Path) -> bool:
    try:
        location = candidate.relative_to(run_root).as_posix()
    except ValueError:
        return False
    return location in DERIVED_RUN_ARTIFACTS


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
        computed = _sha256_text(content)
        supplied = str(self.content_sha256 or "").strip()
        if supplied and supplied != computed:
            raise ValueError("Evidence content_sha256 does not match evidence content.")
        object.__setattr__(self, "content_sha256", computed)

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
    """Surface conflicting claims when providers supply a shared claim_key."""
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


def _bounded_ranked_bundle(items: list[EvidenceItem], limit: int) -> tuple[list[EvidenceItem], list[EvidenceContradiction]]:
    """Keep every evidence record referenced by a returned contradiction resolvable."""
    ranked_all = rank_evidence(items)
    selected = ranked_all[: max(0, limit)]
    contradictions = detect_contradictions(selected)
    # Contradictions are computed over exactly the returned item set. This deliberately
    # avoids dangling hashes to evidence the bundle omitted.
    return selected, contradictions


class ProjectMemoryEvidenceProvider:
    name = "project-memory"

    def __init__(self, repo: Path):
        self.repo = repo.expanduser().resolve()

    def retrieve(self, query: str, *, limit: int = 12) -> list[EvidenceItem]:
        # The hardening installer replaces this with descriptor-anchored retrieval.
        # Pathname validation followed by a separate open is raceable, so fail closed.
        return []


class RunArtifactEvidenceProvider:
    name = "manageroo-run-artifacts"

    def __init__(self, run_root: Path):
        self.run_root = run_root.expanduser().resolve()
        self.artifact_root = self.run_root / "artifacts"

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 12,
        allowed_location_prefixes: Iterable[str] | None = None,
    ) -> list[EvidenceItem]:
        # The hardening installer replaces this with descriptor-anchored retrieval.
        # Pathname validation followed by a separate open is raceable, so fail closed.
        return []


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
        normalized = normalize_external_payload(
            provider=self.name,
            payload=stdout,
            authority=self.authority,
            confidence=self.confidence,
            freshness=self.freshness,
            limit=limit,
        )
        classified: list[EvidenceItem] = []
        for item in normalized:
            metadata = dict(item.metadata)
            metadata["provider_claimed_authority"] = item.authority
            metadata["provider_claimed_confidence"] = item.confidence
            metadata["provider_claimed_freshness"] = item.freshness
            classified.append(
                EvidenceItem(
                    content=item.content,
                    source=item.source,
                    location=item.location,
                    authority=self.authority,
                    confidence=self.confidence,
                    freshness=self.freshness,
                    created_at=item.created_at,
                    metadata=metadata,
                )
            )
        return classified


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
    structured = False
    try:
        decoded = json.loads(payload)
        structured = isinstance(decoded, (dict, list))
    except json.JSONDecodeError:
        decoded = None

    rows: list[dict[str, Any]] = []
    if isinstance(decoded, dict) and isinstance(decoded.get("items"), list):
        rows = [item for item in decoded["items"] if isinstance(item, dict)]
    elif isinstance(decoded, list):
        rows = [item for item in decoded if isinstance(item, dict)]

    if structured and not rows:
        return []
    if not rows:
        if not payload.strip():
            return []
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
    for row in rows:
        if len(items) >= limit:
            break
        content = str(row.get("content") or row.get("text") or row.get("excerpt") or "").strip()
        if not content:
            continue
        metadata = dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {}
        if row.get("claim_key"):
            metadata["claim_key"] = str(row["claim_key"])
        metadata.setdefault("provider", provider)
        try:
            items.append(
                EvidenceItem(
                    content=content[:MAX_EVIDENCE_CONTENT_CHARS],
                    source=str(row.get("source") or provider),
                    location=str(row.get("location") or row.get("path") or ""),
                    authority=str(row.get("authority") or authority),
                    confidence=_safe_float(row.get("confidence", confidence), confidence),
                    freshness=_safe_float(row.get("freshness", freshness), freshness),
                    created_at=str(row.get("created_at")) if row.get("created_at") else None,
                    metadata=metadata,
                )
            )
        except (TypeError, ValueError):
            # One malformed provider row must never abort the complete evidence lane.
            continue
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
        ranked, contradictions = _bounded_ranked_bundle(items, limit)
        return EvidenceBundle(
            query=query,
            items=ranked,
            contradictions=contradictions,
            provider_errors=errors,
        )
