from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

SIGNALS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "identity-and-access",
        ("auth", "authentication", "authorization", "login", "oauth", "session", "rbac", "jwt"),
        "What identity, authentication, authorization, and account-recovery boundaries must be preserved or added?",
        "Inspect existing auth first; default to preserving current identity boundaries and require explicit approval before weakening them.",
    ),
    (
        "money-and-billing",
        ("stripe", "payment", "billing", "checkout", "subscription", "invoice", "wallet"),
        "What money movement, billing, refund, idempotency, and reconciliation behavior must be proven before release?",
        "Treat financial side effects as high impact; require deterministic tests plus a realistic non-production demonstration path.",
    ),
    (
        "data-and-migrations",
        ("migration", "migrations", "prisma", "alembic", "sequelize", "database", ".sql"),
        "What data must be preserved, migrated, backed up, rolled back, or deleted, and how will that be proven?",
        "Prefer additive and reversible migrations, require backup/rollback notes, and block destructive changes without an explicit decision.",
    ),
    (
        "deployment-and-runtime",
        ("vercel", "docker", "kubernetes", "k8s", "terraform", "deploy", "deployment", "production deploy"),
        "What runtime environments, deployment path, rollback path, secrets, and environment-specific differences matter?",
        "Preserve the current deployment model unless the task requires changing it; require a named rollback path before production release.",
    ),
    (
        "hardware-and-local-ai",
        ("cuda", "torch", "tensorflow", "onnx", "comfyui", "gpu", "vram", "ollama", "local model", "local llm"),
        "What CPU, RAM, GPU, VRAM, disk, model-size, and concurrency assumptions must the target product or explicitly selected local AI tool respect?",
        "Treat the detected host as one example development machine only. Infer the target product's requirements from repository/runtime evidence and never turn the developer's hardware into a Manageroo requirement.",
    ),
    (
        "external-services",
        ("api_key", "api key", "webhook", "third-party", "external api", "rate limit", "redis", "s3"),
        "Which external services can fail, rate-limit, change price, or become unavailable, and what is the fallback behavior?",
        "Treat remote services as failure-prone dependencies; define timeouts, retries, cost boundaries, and degraded behavior where relevant.",
    ),
    (
        "user-facing-quality",
        ("react", "next.js", "nextjs", '"next"', "vite", "frontend", "website", "browser", "user interface"),
        "What accessibility, responsive-layout, browser, loading, empty-state, error-state, and keyboard behavior should be part of acceptance?",
        "Require rendered browser evidence for meaningful user-facing changes and preserve accessibility rather than treating it as cosmetic cleanup.",
    ),
)

ALWAYS_REVIEW = [
    {
        "category": "failure-and-recovery",
        "question": "What happens when the primary operation fails halfway through, is retried, or the process is interrupted?",
        "recommended": "Prefer idempotent operations, durable checkpoints, bounded retries, and an explicit recovery or rollback path.",
    },
    {
        "category": "observability-and-support",
        "question": "How will an operator know this failed in production and have enough evidence to diagnose it?",
        "recommended": "Preserve useful logs and errors, avoid swallowing failures, and identify the minimum production signal needed for high-impact paths.",
    },
    {
        "category": "verification-strength",
        "question": "What evidence would actually prove the requested outcome rather than merely prove that the code compiles?",
        "recommended": "Bind every requested outcome to a specific deterministic gate or realistic demonstration and leave unproven outcomes unknown.",
    },
    {
        "category": "scope-and-non-goals",
        "question": "What adjacent improvements are tempting but explicitly outside this run?",
        "recommended": "Keep unrelated cleanup out of the locked plan and record attractive future ideas separately.",
    },
]

TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".sql"}
SKIP_PARTS = {".git", ".manageroo", "node_modules", ".venv", "dist", "build"}
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_STAT_SUPPORTS_DIR_FD = os.stat in os.supports_dir_fd
_LISTDIR_SUPPORTS_FD = os.listdir in os.supports_fd


def _signal_present(corpus: str, term: str) -> bool:
    if any(char in term for char in " ._-\""):
        return term in corpus
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", corpus) is not None


def _descriptor_scan_supported() -> bool:
    return (
        _OPEN_SUPPORTS_DIR_FD
        and _STAT_SUPPORTS_DIR_FD
        and _LISTDIR_SUPPORTS_FD
        and all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"))
    )


def _open_directory(path: str | Path, *, directory_fd: int | None = None) -> int | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        if directory_fd is None:
            descriptor = os.open(path, flags)
        else:
            descriptor = os.open(path, flags, dir_fd=directory_fd)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            return None
        return descriptor
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        return None


def _read_regular_text(name: str, directory_fd: int, limit: int) -> str | None:
    """Read a regular file relative to one pinned directory descriptor."""
    flags = os.O_RDONLY
    for flag in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag, 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return None
        current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (
            current.st_dev,
            current.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            return None
        handle = os.fdopen(descriptor, "r", encoding="utf-8", errors="ignore")
        descriptor = None
        with handle:
            return handle.read(limit)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _repo_text(repo: Path, *, max_files: int = 250, max_chars: int = 500_000) -> str:
    """Collect a bounded repository text corpus without opening special files."""
    repo = repo.resolve()
    if not _descriptor_scan_supported():
        return ""
    chunks: list[str] = []
    consumed = 0
    scanned = 0
    preferred = {
        "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "requirements.txt", "Dockerfile", "docker-compose.yml", "vercel.json", ".env.example", "README.md", "ARCHITECTURE.md",
    }
    root_descriptor = _open_directory(repo)
    if root_descriptor is None:
        return ""
    open_descriptors = {root_descriptor}
    pending: tuple[int, Path] | None = (root_descriptor, Path())
    stack: list[tuple[int, Path, list[str], int]] = []
    try:
        while pending is not None or stack:
            if pending is not None:
                directory_fd, relative_directory = pending
                pending = None
                try:
                    names = os.listdir(directory_fd)
                except OSError:
                    names = []
                directories: list[str] = []
                files: list[str] = []
                for name in names:
                    try:
                        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(entry.st_mode):
                        if name not in SKIP_PARTS:
                            directories.append(name)
                    elif not stat.S_ISLNK(entry.st_mode):
                        files.append(name)

                ordered_files = sorted(files, key=lambda name: (name not in preferred, name))
                for name in ordered_files:
                    if scanned >= max_files or consumed >= max_chars:
                        return "\n".join(chunks).lower()
                    if Path(name).suffix.lower() not in TEXT_SUFFIXES and name not in preferred:
                        continue
                    remaining = max_chars - consumed
                    text = _read_regular_text(name, directory_fd, min(20_000, remaining))
                    if text is None:
                        continue
                    scanned += 1
                    consumed += len(text)
                    chunks.append((relative_directory / name).as_posix())
                    chunks.append(text)
                    if consumed >= max_chars:
                        return "\n".join(chunks).lower()
                stack.append((directory_fd, relative_directory, sorted(directories), 0))
                continue

            directory_fd, relative_directory, directories, index = stack[-1]
            if index >= len(directories):
                stack.pop()
                os.close(directory_fd)
                open_descriptors.remove(directory_fd)
                continue
            name = directories[index]
            stack[-1] = (directory_fd, relative_directory, directories, index + 1)
            child_descriptor = _open_directory(name, directory_fd=directory_fd)
            if child_descriptor is not None:
                open_descriptors.add(child_descriptor)
                pending = (child_descriptor, relative_directory / name)
        return "\n".join(chunks).lower()
    finally:
        for descriptor in open_descriptors:
            os.close(descriptor)


def build_discovery_preflight(repo: Path, brief: str, capacity: dict[str, Any]) -> dict[str, Any]:
    repo = repo.resolve()
    corpus = (brief + "\n" + _repo_text(repo)).lower()
    triggered: list[dict[str, str]] = []
    for category, terms, question, recommended in SIGNALS:
        matched = [term for term in terms if _signal_present(corpus, term)]
        if matched:
            triggered.append({
                "category": category,
                "signals": ", ".join(matched[:8]),
                "question": question,
                "recommended": recommended,
            })

    capacity_notes: list[str] = [
        "Host hardware is informational development context only. It is not a Manageroo minimum requirement and does not automatically change Manageroo worker concurrency."
    ]
    capacity_notes.extend(list(capacity.get("notes", []) or []))

    return {
        "purpose": (
            "Deterministic preflight for questions the operator may not know to ask. "
            "The product analyst must inspect these categories, answer anything discoverable "
            "from current repo evidence, infer reversible conventional details, and create "
            "blocking decisions only for unresolved high-impact choices."
        ),
        "always_review": ALWAYS_REVIEW,
        "repo_signals": triggered,
        "capacity_notes": capacity_notes,
        "decision_policy": {
            "ask_only_when": [
                "irreversible data loss or migration semantics are genuinely ambiguous",
                "a security or authorization boundary would materially change",
                "meaningful recurring or irreversible cost depends on the choice",
                "legal or regulated behavior depends on the choice",
                "the available options would create materially different products",
                "target-product or explicitly selected local-runtime hardware requirements cannot be inferred safely and affect whether that product can work",
            ],
            "do_not_block_for": [
                "the Manageroo host having different CPU, RAM, GPU, or VRAM than the developer's machine",
                "cosmetic preferences with conventional defaults",
                "implementation details that can be changed later",
                "questions answerable by inspecting the repository",
                "questions whose recommended reversible option is safe to adopt",
            ],
        },
    }
