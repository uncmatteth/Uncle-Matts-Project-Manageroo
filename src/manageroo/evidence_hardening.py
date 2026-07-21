from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _verified_bounded_text(path: Path, root: Path, *, max_bytes: int) -> tuple[str, float] | None:
    """Open one verified regular inode without following a final symlink.

    On Linux, /proc/self/fd binds containment to the actual opened inode. Other platforms
    use a post-open realpath plus device/inode comparison as a conservative fallback.
    """
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            return None
        proc_fd = Path(f"/proc/self/fd/{fd}")
        try:
            actual = proc_fd.resolve(strict=True) if proc_fd.exists() else path.resolve(strict=True)
            actual.relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError:
            return None
        if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            return None
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            block = os.read(fd, min(65536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        payload = b"".join(chunks)[:max_bytes]
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and exc.start >= max(0, len(payload) - 4):
                try:
                    text = payload[: exc.start].decode("utf-8")
                except UnicodeDecodeError:
                    return None
            else:
                return None
        return text, opened.st_mtime
    finally:
        os.close(fd)


def install_evidence_hardening(evidence_module: Any, evidence_policy_module: Any | None = None) -> None:
    if getattr(evidence_module, "_manageroo_evidence_hardening_installed", False):
        return

    original_normalize = evidence_module.normalize_external_payload

    def normalize_external_payload_hardened(*, limit: int = 12, **kwargs: Any):
        if int(limit) <= 0:
            return []
        return original_normalize(limit=limit, **kwargs)

    def project_memory_retrieve(self: Any, query: str, *, limit: int = 12):
        if int(limit) <= 0:
            return []
        lexical = self.repo / evidence_module.PROJECT_DIR / "PROJECT-MEMORY.md"
        record = _verified_bounded_text(
            lexical,
            self.repo,
            max_bytes=evidence_module.MAX_EVIDENCE_INPUT_BYTES,
        )
        if record is None:
            return []
        content, mtime = record
        if not content.strip():
            return []
        terms = evidence_module._query_terms(query)
        lowered = content.lower()
        relevance = sum(lowered.count(term) for term in terms)
        if terms and relevance == 0:
            return []
        return [
            evidence_module.EvidenceItem(
                content=content[: evidence_module.MAX_EVIDENCE_CONTENT_CHARS],
                source=self.name,
                location=str(lexical.relative_to(self.repo)),
                authority="project_memory",
                confidence=0.90,
                freshness=0.85,
                created_at=datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                metadata={
                    "relevance_hits": relevance,
                    "provider": self.name,
                    "input_byte_limit": evidence_module.MAX_EVIDENCE_INPUT_BYTES,
                    "descriptor_verified": True,
                },
            )
        ]

    def run_artifact_retrieve(self: Any, query: str, *, limit: int = 12):
        limit = int(limit)
        if limit <= 0:
            return []
        if not self.artifact_root.is_dir() or self.artifact_root.is_symlink():
            return []
        try:
            root = self.artifact_root.resolve(strict=True)
            root.relative_to(self.run_root)
        except (OSError, ValueError):
            return []
        terms = evidence_module._query_terms(query)
        candidates: list[tuple[int, float, Path, str]] = []
        eligible_seen = 0
        eligible_cap = max(limit * 20, 100)
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = sorted(name for name in dirs if not (Path(current) / name).is_symlink())
            for name in sorted(files):
                if eligible_seen >= eligible_cap:
                    break
                lexical = Path(current) / name
                if lexical.suffix.lower() not in evidence_module.EVIDENCE_SUFFIXES:
                    continue
                eligible_seen += 1
                record = _verified_bounded_text(
                    lexical,
                    root,
                    max_bytes=evidence_module.MAX_EVIDENCE_INPUT_BYTES,
                )
                if record is None:
                    continue
                text, mtime = record
                if not text.strip():
                    continue
                lowered = (lexical.as_posix() + "\n" + text).lower()
                relevance = sum(lowered.count(term) for term in terms)
                if terms and relevance == 0:
                    continue
                candidates.append((relevance, mtime, lexical, text))
            if eligible_seen >= eligible_cap:
                break
        candidates.sort(key=lambda row: (row[0], row[1], row[2].as_posix()), reverse=True)
        items = []
        for relevance, mtime, path, text in candidates[:limit]:
            try:
                location = str(path.relative_to(self.run_root))
            except ValueError:
                continue
            try:
                items.append(
                    evidence_module.EvidenceItem(
                        content=text[: evidence_module.MAX_EVIDENCE_CONTENT_CHARS],
                        source=self.name,
                        location=location,
                        authority="manageroo_run",
                        confidence=0.98,
                        freshness=0.95,
                        created_at=datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                        metadata={
                            "relevance_hits": relevance,
                            "provider": self.name,
                            "input_byte_limit": evidence_module.MAX_EVIDENCE_INPUT_BYTES,
                            "descriptor_verified": True,
                        },
                    )
                )
            except (TypeError, ValueError):
                continue
        return items

    evidence_module.normalize_external_payload = normalize_external_payload_hardened
    evidence_module.ProjectMemoryEvidenceProvider.retrieve = project_memory_retrieve
    evidence_module.RunArtifactEvidenceProvider.retrieve = run_artifact_retrieve
    if evidence_policy_module is not None:
        evidence_policy_module.normalize_external_payload = normalize_external_payload_hardened
    evidence_module._manageroo_evidence_hardening_installed = True
