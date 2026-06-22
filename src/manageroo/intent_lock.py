from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .errors import ConfigurationError
from .project import git_root
from .util import atomic_write_json, atomic_write_text, read_json, sha256_file, sha256_text, utc_now

INTENT_DIR = "intent"
INTENT_LOCK_NAME = "INTENT-LOCK.json"
INTENT_LOCK_MARKDOWN_NAME = "INTENT-LOCK.md"

_CONFIDENCE_PATTERN = re.compile(
    r"\b(best|smartest|perfect|100%\s*(done|complete|ready)|complete|ready|finished)\b",
    re.IGNORECASE,
)


def intent_root(repo: Path) -> Path:
    return repo / PROJECT_DIR / INTENT_DIR


def intent_lock_path(repo: Path) -> Path:
    return intent_root(repo) / INTENT_LOCK_NAME


def intent_lock_markdown_path(repo: Path) -> Path:
    return intent_root(repo) / INTENT_LOCK_MARKDOWN_NAME


def _clean(value: str) -> str:
    return " ".join(str(value).strip().split())


def _clean_items(values: list[str] | tuple[str, ...] | None) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = _clean(value)
        key = _normalize(cleaned)
        if cleaned and key not in seen:
            items.append(cleaned)
            seen.add(key)
    return items


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _bullets(values: list[str], fallback: str = "None recorded.") -> list[str]:
    if not values:
        return [f"- {fallback}"]
    return [f"- {value}" for value in values]


def _lock_markdown(lock: dict[str, Any]) -> str:
    lines = [
        "# Intent Lock",
        "",
        "This file is the repo-local truth surface for long-running AI work.",
        "Chat compaction, handoffs, and agent summaries must preserve these items.",
        "",
        "## Current Intent",
        "",
        lock.get("want") or "None recorded.",
        "",
        "## Required Outcomes",
        "",
        *_bullets(lock.get("outcomes", [])),
        "",
        "## Must Not Happen",
        "",
        *_bullets(lock.get("must_not", [])),
        "",
        "## Proof Required",
        "",
        *_bullets(lock.get("proof", [])),
        "",
        "## Latest Corrections",
        "",
        *_bullets(lock.get("corrections", [])),
        "",
        "## Rejected Ideas",
        "",
        *_bullets(lock.get("rejected", [])),
        "",
        "## Scope Boundaries",
        "",
        *_bullets(lock.get("scopes", [])),
        "",
        "## Open Questions",
        "",
        *_bullets(lock.get("questions", [])),
        "",
        "## Anti-BS Rule",
        "",
        "- Do not claim best, smartest, perfect, complete, ready, or 100% done unless the evidence is listed here or in the current run report.",
        "- If evidence is missing, say it is a recommendation or partial status.",
        "- Current disk, repo, command output, and locked artifacts beat memory and old chat.",
        "",
    ]
    return "\n".join(lines)


def _lock_payload(
    repo: Path,
    *,
    want: str = "",
    outcomes: list[str] | None = None,
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
    corrections: list[str] | None = None,
    rejected: list[str] | None = None,
    questions: list[str] | None = None,
    scopes: list[str] | None = None,
    source: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "repo": str(repo),
        "source": _clean(source) or "operator",
        "want": _clean(want),
        "outcomes": _clean_items(outcomes),
        "must_not": _clean_items(must_not),
        "proof": _clean_items(proof),
        "corrections": _clean_items(corrections),
        "rejected": _clean_items(rejected),
        "questions": _clean_items(questions),
        "scopes": _clean_items(scopes),
        "audit_policy": {
            "strict_phrase_preservation": True,
            "required_categories": [
                "want",
                "outcomes",
                "must_not",
                "proof",
                "corrections",
                "rejected",
                "scopes",
                "questions",
            ],
            "confidence_claims_require_evidence": True,
        },
    }


def capture_intent_lock(
    repo_path: Path,
    *,
    want: str = "",
    outcomes: list[str] | None = None,
    must_not: list[str] | None = None,
    proof: list[str] | None = None,
    corrections: list[str] | None = None,
    rejected: list[str] | None = None,
    questions: list[str] | None = None,
    scopes: list[str] | None = None,
    source: str = "",
    force: bool = False,
) -> dict[str, Any]:
    repo = git_root(repo_path)
    path = intent_lock_path(repo)
    if path.exists() and not force:
        raise ConfigurationError(
            f"Intent lock already exists: {path}. Use `--force` only when replacing the current locked intent."
        )
    lock = _lock_payload(
        repo,
        want=want,
        outcomes=outcomes,
        must_not=must_not,
        proof=proof,
        corrections=corrections,
        rejected=rejected,
        questions=questions,
        scopes=scopes,
        source=source,
    )
    atomic_write_json(path, lock)
    markdown_path = intent_lock_markdown_path(repo)
    atomic_write_text(markdown_path, _lock_markdown(lock))
    return {
        "ok": True,
        "repo": str(repo),
        "path": str(path),
        "markdown_path": str(markdown_path),
        "lock_hash": sha256_file(path),
        "next_command": f"{PUBLIC_COMMAND} compact audit {repo} --summary SUMMARY.md",
        "lock": lock,
    }


def read_intent_lock(repo_path: Path) -> dict[str, Any]:
    repo = git_root(repo_path)
    path = intent_lock_path(repo)
    if not path.exists():
        return {
            "ok": False,
            "repo": str(repo),
            "path": str(path),
            "error": "No intent lock exists yet.",
            "next_command": f'{PUBLIC_COMMAND} intent capture {repo} --want "..." --must-not "..." --proof "..."',
        }
    lock = read_json(path)
    return {
        "ok": True,
        "repo": str(repo),
        "path": str(path),
        "markdown_path": str(intent_lock_markdown_path(repo)),
        "lock_hash": sha256_file(path),
        "lock": lock,
    }


def _required_phrases(lock: dict[str, Any]) -> list[dict[str, str]]:
    phrases: list[dict[str, str]] = []
    want = _clean(lock.get("want", ""))
    if want:
        phrases.append({"category": "want", "text": want})
    for category in ["outcomes", "must_not", "proof", "corrections", "rejected", "scopes", "questions"]:
        for value in lock.get(category, []) or []:
            cleaned = _clean(value)
            if cleaned:
                phrases.append({"category": category, "text": cleaned})
    return phrases


def _confidence_warnings(summary_text: str) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for match in _CONFIDENCE_PATTERN.finditer(summary_text):
        phrase = match.group(0)
        warnings.append(
            {
                "code": "confidence_claim",
                "text": phrase,
                "detail": "Avoid best/smartest/perfect/ready claims unless current evidence is listed.",
            }
        )
    return warnings


def audit_compaction_text(
    repo_path: Path,
    summary_text: str,
    *,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    repo = git_root(repo_path)
    lock_report = read_intent_lock(repo)
    if not lock_report.get("ok"):
        return {
            "ok": False,
            "status": "blocked",
            "repo": str(repo),
            "lock_path": lock_report["path"],
            "summary_path": str(summary_path.resolve()) if summary_path else "",
            "summary_hash": sha256_text(summary_text),
            "missing": [{"category": "intent_lock", "text": "No intent lock exists yet."}],
            "warnings": [],
            "next_command": lock_report["next_command"],
        }
    lock = lock_report["lock"]
    normalized_summary = _normalize(summary_text)
    missing = [
        item
        for item in _required_phrases(lock)
        if _normalize(item["text"]) not in normalized_summary
    ]
    warnings = _confidence_warnings(summary_text)
    ok = not missing
    return {
        "ok": ok,
        "status": "passed" if ok else "blocked",
        "repo": str(repo),
        "lock_path": lock_report["path"],
        "lock_hash": lock_report["lock_hash"],
        "summary_path": str(summary_path.resolve()) if summary_path else "",
        "summary_hash": sha256_text(summary_text),
        "missing": missing,
        "warnings": warnings,
        "checked_categories": sorted({item["category"] for item in _required_phrases(lock)}),
        "next_command": (
            f"{PUBLIC_COMMAND} intent show {repo}"
            if missing
            else f"{PUBLIC_COMMAND} run --repo {repo} --apply"
        ),
    }


def audit_compaction_file(repo_path: Path, summary_path: Path) -> dict[str, Any]:
    path = summary_path.resolve()
    text = path.read_text(encoding="utf-8", errors="replace")
    return audit_compaction_text(repo_path, text, summary_path=path)


def save_compaction_checkpoint(repo_path: Path, summary_path: Path) -> dict[str, Any]:
    repo = git_root(repo_path)
    summary = summary_path.resolve()
    audit = audit_compaction_file(repo, summary)
    checkpoint_root = intent_root(repo) / "checkpoints"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    stem = f"{utc_now().replace(':', '').replace('+', 'Z')}-{summary.stem}"
    copied_summary = checkpoint_root / f"{stem}.md"
    copied_audit = checkpoint_root / f"{stem}.audit.json"
    shutil.copyfile(summary, copied_summary)
    atomic_write_json(copied_audit, audit)
    audit["checkpoint_path"] = str(copied_summary)
    audit["checkpoint_audit_path"] = str(copied_audit)
    return audit


def pinned_context_block(repo_path: Path) -> dict[str, Any]:
    report = read_intent_lock(repo_path)
    if not report.get("ok"):
        return report
    lock = report["lock"]
    lines = [
        "# Pinned Intent Context",
        "",
        "Keep this block near the beginning and end of long-running agent packets.",
        "Do not compress away these exact items.",
        "",
    ]
    for item in _required_phrases(lock):
        lines.append(f"- {item['category']}: {item['text']}")
    text = "\n".join(lines) + "\n"
    return {
        "ok": True,
        "repo": report["repo"],
        "path": report["path"],
        "content": text,
        "content_hash": sha256_text(text),
    }


def format_intent_lock(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        lines = ["INTENT LOCK: MISSING", f"Path: {report.get('path', '')}"]
        if report.get("error"):
            lines.append(f"Error: {report['error']}")
        if report.get("next_command"):
            lines.append(f"Next: {report['next_command']}")
        return "\n".join(lines) + "\n"
    lock = report.get("lock", {})
    lines = [
        "INTENT LOCK",
        f"Path: {report['path']}",
        f"Hash: {report.get('lock_hash', '')}",
        "",
        f"Want: {lock.get('want') or 'None recorded.'}",
        "",
        "Must not:",
        *_bullets(lock.get("must_not", [])),
        "",
        "Proof:",
        *_bullets(lock.get("proof", [])),
        "",
        "Corrections:",
        *_bullets(lock.get("corrections", [])),
        "",
        "Rejected:",
        *_bullets(lock.get("rejected", [])),
    ]
    return "\n".join(lines) + "\n"


def format_compaction_audit(report: dict[str, Any]) -> str:
    title = "COMPACTION AUDIT: PASSED" if report.get("ok") else "COMPACTION AUDIT: BLOCKED"
    lines = [
        title,
        f"Intent lock: {report.get('lock_path', '')}",
    ]
    if report.get("summary_path"):
        lines.append(f"Summary: {report['summary_path']}")
    lines.append("")
    missing = report.get("missing", [])
    if missing:
        lines.append("Missing locked truth:")
        for item in missing:
            lines.append(f"- MISSING {item.get('category')}: {item.get('text')}")
    else:
        lines.append("Missing locked truth: none")
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "Warnings:"])
        for item in warnings:
            lines.append(f"- WARNING {item.get('code')}: {item.get('text')}")
    if report.get("checkpoint_path"):
        lines.extend(["", f"Checkpoint: {report['checkpoint_path']}"])
    if report.get("next_command"):
        lines.extend(["", f"Next: {report['next_command']}"])
    return "\n".join(lines) + "\n"
