from __future__ import annotations

from pathlib import Path

from .branding import PROJECT_DIR
from .util import atomic_write_text


def _bullets(items: list[str], fallback: str) -> list[str]:
    values = [item.strip() for item in items if item.strip()]
    return [f"- {item}" for item in values] if values else [f"- {fallback}"]


def build_product_brief(
    *,
    want: str,
    audience: str = "",
    outcomes: list[str] | None = None,
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
    stop_rule: str = "",
    later: list[str] | None = None,
) -> str:
    want = want.strip()
    if not want:
        raise ValueError("Brief needs --want or an interactive answer for what you want.")
    outcomes = outcomes or []
    must_not = must_not or []
    proof = proof or []
    later = later or []
    lines = [
        "# Product brief",
        "",
        "## What I want",
        "",
        want,
        "",
        "## Loop shape",
        "",
        "- `goal`: keep working until a verifiable outcome is true, then stop.",
        "",
        "## Who it is for",
        "",
        audience.strip() or "The people or systems that use this repo.",
        "",
        "## Required outcomes",
        "",
        *_bullets(outcomes, "Turn the request above into working product behavior."),
        "",
        "## Must not happen",
        "",
        *_bullets(must_not, "Do not break existing working behavior."),
        "",
        "## Complete means",
        "",
        *_bullets(proof, "Run the repo's configured checks and report the result."),
        "- The final report says what changed, what was checked, and what is still unknown.",
        "",
        "## Budget and stop rules",
        "",
        f"- {stop_rule.strip() or 'Stop after two failed repair passes and report the blocker.'}",
        "- Stop if the same fix fails twice.",
        "- Stop if the work flip-flops between incompatible approaches.",
        "",
        "## Existing product",
        "",
        "Use the current Git repository as the source of truth. Preserve unrelated behavior.",
        "",
        "## Ideas that may belong later",
        "",
        *_bullets(later, "No future ideas captured yet."),
        "",
    ]
    return "\n".join(lines)


def default_brief_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / "PRODUCT-BRIEF.md"


def write_product_brief(path: Path, markdown: str, *, force: bool = False) -> Path:
    if path.exists() and not force:
        raise ValueError(f"Refusing to overwrite existing brief without --force: {path}")
    atomic_write_text(path, markdown)
    return path
