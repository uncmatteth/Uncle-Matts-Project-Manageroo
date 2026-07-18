from __future__ import annotations

from pathlib import Path
from typing import Any


SIGNALS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "identity-and-access",
        ("auth", "login", "oauth", "session", "permission", "role", "rbac", "jwt"),
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
        ("migration", "migrations", "prisma", "alembic", "sequelize", "database", ".sql", "schema"),
        "What data must be preserved, migrated, backed up, rolled back, or deleted, and how will that be proven?",
        "Prefer additive and reversible migrations, require backup/rollback notes, and block destructive changes without an explicit decision.",
    ),
    (
        "deployment-and-runtime",
        ("vercel", "docker", "kubernetes", "k8s", "terraform", "deploy", "production"),
        "What runtime environments, deployment path, rollback path, secrets, and environment-specific differences matter?",
        "Preserve the current deployment model unless the task requires changing it; require a named rollback path before production release.",
    ),
    (
        "hardware-and-local-ai",
        ("cuda", "torch", "tensorflow", "onnx", "comfy", "gpu", "vram", "model", "ollama"),
        "What CPU, RAM, GPU, VRAM, disk, model-size, and concurrency assumptions must the product respect?",
        "Use the detected host profile as a development baseline, but document minimum and recommended capacity separately from one developer machine.",
    ),
    (
        "external-services",
        ("api_key", "api key", "webhook", "third-party", "external api", "rate limit", "redis", "s3"),
        "Which external services can fail, rate-limit, change price, or become unavailable, and what is the fallback behavior?",
        "Treat remote services as failure-prone dependencies; define timeouts, retries, cost boundaries, and degraded behavior where relevant.",
    ),
    (
        "user-facing-quality",
        ("react", "next", "vite", "frontend", "website", "browser", "ui", "ux"),
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


def _repo_text(repo: Path, *, max_files: int = 250, max_chars: int = 500_000) -> str:
    chunks: list[str] = []
    consumed = 0
    scanned = 0
    preferred = {
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
        "vercel.json",
        ".env.example",
        "README.md",
        "ARCHITECTURE.md",
    }
    candidates = sorted(
        (path for path in repo.rglob("*") if path.is_file()),
        key=lambda path: (path.name not in preferred, len(path.parts), path.as_posix()),
    )
    for path in candidates:
        if scanned >= max_files or consumed >= max_chars:
            break
        try:
            relative = path.relative_to(repo)
        except ValueError:
            continue
        if any(part in {".git", ".manageroo", "node_modules", ".venv", "dist", "build"} for part in relative.parts):
            continue
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".sql"} and path.name not in preferred:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:20_000]
        except OSError:
            continue
        scanned += 1
        consumed += len(text)
        chunks.append(relative.as_posix())
        chunks.append(text)
    return "\n".join(chunks).lower()


def build_discovery_preflight(repo: Path, brief: str, capacity: dict[str, Any]) -> dict[str, Any]:
    repo = repo.resolve()
    corpus = (brief + "\n" + _repo_text(repo)).lower()
    triggered: list[dict[str, str]] = []
    for category, terms, question, recommended in SIGNALS:
        matched = [term for term in terms if term in corpus]
        if not matched:
            continue
        triggered.append(
            {
                "category": category,
                "signals": ", ".join(matched[:8]),
                "question": question,
                "recommended": recommended,
            }
        )

    capacity_notes: list[str] = []
    warnings = list(capacity.get("warnings", []) or [])
    if warnings:
        capacity_notes.extend(warnings)
    capacity_notes.append(
        "Detected development-host capacity class: "
        + str(capacity.get("recommendations", {}).get("capacity_class", "unknown"))
    )
    capacity_notes.append(
        "Conservative detected-host parallel-worker recommendation: "
        + str(capacity.get("recommendations", {}).get("max_parallel_agent_calls", "unknown"))
    )

    return {
        "purpose": (
            "Deterministic preflight for questions the operator may not know to ask. "
            "The product analyst must inspect these categories, answer anything discoverable from current repo evidence, "
            "infer reversible conventional details, and create blocking decisions only for unresolved high-impact choices."
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
                "hardware/runtime requirements cannot be inferred safely and affect whether the product can work",
            ],
            "do_not_block_for": [
                "cosmetic preferences with conventional defaults",
                "implementation details that can be changed later",
                "questions answerable by inspecting the repository",
                "questions whose recommended reversible option is safe to adopt",
            ],
        },
    }
