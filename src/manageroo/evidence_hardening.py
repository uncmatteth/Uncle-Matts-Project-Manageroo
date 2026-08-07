from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _descriptor_traversal_supported() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
    )


def _open_directory_fd(path: str | Path, *, dir_fd: int | None = None) -> int | None:
    if not _descriptor_traversal_supported():
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError:
        return None


def _descriptor_names(directory_fd: int) -> list[str]:
    return sorted(os.listdir(directory_fd))


def _walk_descriptor(
    directory_fd: int,
    relative: Path = Path(),
):
    try:
        names = _descriptor_names(directory_fd)
    except OSError:
        return
    for name in names:
        try:
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            continue
        child_relative = relative / name
        if stat.S_ISDIR(entry.st_mode):
            child_fd = _open_directory_fd(name, dir_fd=directory_fd)
            if child_fd is None:
                continue
            try:
                yield from _walk_descriptor(child_fd, child_relative)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(entry.st_mode):
            yield directory_fd, name, child_relative


def _verified_bounded_text(
    directory_fd: int,
    name: str,
    *,
    max_bytes: int,
) -> tuple[str, float] | None:
    """Open one verified regular inode relative to an already anchored directory.

    Every directory component is retained by descriptor, so renaming or replacing its
    pathname cannot redirect this open outside the trusted tree.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            return None
        try:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            return None
        if stat.S_ISLNK(current.st_mode) or (
            current.st_dev,
            current.st_ino,
        ) != (opened.st_dev, opened.st_ino):
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
        repo_fd = _open_directory_fd(self.repo)
        if repo_fd is None:
            return []
        try:
            project_fd = _open_directory_fd(evidence_module.PROJECT_DIR, dir_fd=repo_fd)
            if project_fd is None:
                return []
            try:
                record = _verified_bounded_text(
                    project_fd,
                    "PROJECT-MEMORY.md",
                    max_bytes=evidence_module.MAX_EVIDENCE_INPUT_BYTES,
                )
            finally:
                os.close(project_fd)
        finally:
            os.close(repo_fd)
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

    def run_artifact_retrieve(
        self: Any,
        query: str,
        *,
        limit: int = 12,
        allowed_location_prefixes: Any = None,
    ):
        limit = int(limit)
        if limit <= 0:
            return []
        allowed_prefixes = (
            tuple(str(prefix) for prefix in allowed_location_prefixes)
            if allowed_location_prefixes is not None
            else None
        )
        run_fd = _open_directory_fd(self.run_root)
        if run_fd is None:
            return []
        try:
            artifact_fd = _open_directory_fd("artifacts", dir_fd=run_fd)
            if artifact_fd is None:
                return []
            try:
                terms = evidence_module._query_terms(query)
                candidates: list[tuple[int, float, Path, str]] = []
                verified_seen = 0
                verified_cap = max(limit * 20, 100)
                read_seen = 0
                read_cap = verified_cap * 2
                walker = _walk_descriptor(artifact_fd)
                try:
                    for directory_fd, name, relative in walker:
                        if read_seen >= read_cap or verified_seen >= verified_cap:
                            break
                        lexical = Path("artifacts") / relative
                        location = lexical.as_posix()
                        if allowed_prefixes is not None and not location.startswith(
                            allowed_prefixes
                        ):
                            continue
                        if lexical.suffix.lower() not in evidence_module.EVIDENCE_SUFFIXES:
                            continue
                        if evidence_module._is_derived_run_artifact(
                            self.run_root,
                            self.run_root / lexical,
                        ):
                            continue
                        read_seen += 1
                        record = _verified_bounded_text(
                            directory_fd,
                            name,
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
                        verified_seen += 1
                        candidates.append((relevance, mtime, lexical, text))
                finally:
                    walker.close()
            finally:
                os.close(artifact_fd)
        finally:
            os.close(run_fd)
        candidates.sort(key=lambda row: (row[0], row[1], row[2].as_posix()), reverse=True)
        items = []
        for relevance, mtime, path, text in candidates[:limit]:
            try:
                items.append(
                    evidence_module.EvidenceItem(
                        content=text[: evidence_module.MAX_EVIDENCE_CONTENT_CHARS],
                        source=self.name,
                        location=path.as_posix(),
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
    if _descriptor_traversal_supported():
        evidence_module.ProjectMemoryEvidenceProvider.retrieve = project_memory_retrieve
        evidence_module.RunArtifactEvidenceProvider.retrieve = run_artifact_retrieve
    if evidence_policy_module is not None:
        evidence_policy_module.normalize_external_payload = normalize_external_payload_hardened
    evidence_module._manageroo_evidence_hardening_installed = True
