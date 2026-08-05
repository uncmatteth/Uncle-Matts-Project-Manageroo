from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config_lock import config_mutation_lock
from .errors import ConfigurationError
from .intent_audit_policy import (
    _NEGATION_IN_CLAUSE,
    _NONAFFIRMATIVE_CLAIM_STATE,
    _inside_quoted_span,
)
from .project import git_root
from .util import atomic_write_json, atomic_write_text, sha256_bytes, sha256_file, sha256_text, utc_now

INTENT_DIR = "intent"
INTENT_LOCK_NAME = "INTENT-LOCK.json"
INTENT_LOCK_MARKDOWN_NAME = "INTENT-LOCK.md"
_LOCK_STRING_FIELDS = ("created_at", "repo", "source", "want")
_LOCK_LIST_FIELDS = (
    "outcomes", "must_not", "proof", "corrections", "rejected", "scopes", "questions",
)
_LOCK_REQUIRED_CATEGORIES = ("want", *_LOCK_LIST_FIELDS)

# Confidence warnings are for absolute quality/completion claims, not ordinary domain text
# such as "ready queue", "complete record", or a locked outcome that happens to use "ready".
_CONFIDENCE_PATTERN = re.compile(
    r"\b(?:best|smartest|perfect|guaranteed\s+(?:complete|ready|finished)|100%\s*(?:done|complete|ready|finished)|fully\s+(?:complete|finished|verified|production[- ]ready)|production[- ]ready)\b",
    re.IGNORECASE,
)


def intent_root(repo: Path) -> Path:
    return repo / PROJECT_DIR / INTENT_DIR


def intent_lock_path(repo: Path) -> Path:
    return intent_root(repo) / INTENT_LOCK_NAME


def intent_lock_markdown_path(repo: Path) -> Path:
    return intent_root(repo) / INTENT_LOCK_MARKDOWN_NAME


def render_next_command(*arguments: str | Path) -> str:
    return shlex.join([PUBLIC_COMMAND, *(str(argument) for argument in arguments)])


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
        "# Intent Lock", "", "This file is the repo-local truth surface for long-running AI work.",
        "Chat compaction, handoffs, and agent summaries must preserve these items.", "",
        "## Current Intent", "", lock.get("want") or "None recorded.", "",
        "## Required Outcomes", "", *_bullets(lock.get("outcomes", [])), "",
        "## Must Not Happen", "", *_bullets(lock.get("must_not", [])), "",
        "## Proof Required", "", *_bullets(lock.get("proof", [])), "",
        "## Latest Corrections", "", *_bullets(lock.get("corrections", [])), "",
        "## Rejected Ideas", "", *_bullets(lock.get("rejected", [])), "",
        "## Scope Boundaries", "", *_bullets(lock.get("scopes", [])), "",
        "## Open Questions", "", *_bullets(lock.get("questions", [])), "",
        "## Anti-BS Rule", "",
        "- Do not claim best, smartest, perfect, guaranteed complete, production-ready, or 100% done unless affirmative evidence is listed here or in the current run report.",
        "- Ordinary uses of words such as ready, complete, or finished are not automatically completion claims.",
        "- If evidence is missing, say it is a recommendation or partial status.",
        "- Current disk, repo, command output, and locked artifacts beat memory and old chat.", "",
    ]
    return "\n".join(lines)


def _lock_payload(repo: Path, *, want: str = "", outcomes: list[str] | None = None, must_not: list[str] | None = None, proof: list[str] | None = None, corrections: list[str] | None = None, rejected: list[str] | None = None, questions: list[str] | None = None, scopes: list[str] | None = None, source: str = "") -> dict[str, Any]:
    return {
        "schema_version": 1, "created_at": utc_now(), "repo": str(repo), "source": _clean(source) or "operator",
        "want": _clean(want), "outcomes": _clean_items(outcomes), "must_not": _clean_items(must_not),
        "proof": _clean_items(proof), "corrections": _clean_items(corrections), "rejected": _clean_items(rejected),
        "questions": _clean_items(questions), "scopes": _clean_items(scopes),
        "audit_policy": {
            "strict_phrase_preservation": True,
            "required_categories": ["want", "outcomes", "must_not", "proof", "corrections", "rejected", "scopes", "questions"],
            "confidence_claims_require_evidence": True,
        },
    }


def _publish_lock_pair(path: Path, lock: dict[str, Any]) -> Path:
    markdown_path = path.with_name(INTENT_LOCK_MARKDOWN_NAME)
    transaction = Path(tempfile.mkdtemp(prefix=".intent-lock-", dir=str(path.parent)))
    staged = {
        path: transaction / path.name,
        markdown_path: transaction / markdown_path.name,
    }
    backups: dict[Path, Path] = {}
    publication_started = False
    try:
        atomic_write_json(staged[path], lock)
        atomic_write_text(staged[markdown_path], _lock_markdown(lock))
        for visible in staged:
            if visible.exists():
                backup = transaction / f"{visible.name}.previous"
                shutil.copy2(visible, backup)
                backups[visible] = backup
        publication_started = True
        for visible, candidate in staged.items():
            os.replace(candidate, visible)
    except BaseException as exc:
        rollback_errors: list[OSError] = []
        if publication_started:
            for visible in reversed(tuple(staged)):
                try:
                    backup = backups.get(visible)
                    if backup is not None and backup.exists():
                        os.replace(backup, visible)
                    elif visible not in backups:
                        visible.unlink(missing_ok=True)
                except OSError as rollback_exc:
                    rollback_errors.append(rollback_exc)
        if rollback_errors:
            raise ConfigurationError(
                f"Intent lock publication failed and rollback was incomplete. "
                f"Recoverable files remain in {transaction}."
            ) from exc
        shutil.rmtree(transaction, ignore_errors=True)
        raise
    shutil.rmtree(transaction, ignore_errors=True)
    return markdown_path


def _read_lock_snapshot(path: Path) -> tuple[Any, str]:
    snapshot = path.read_bytes()
    return json.loads(snapshot.decode("utf-8")), sha256_bytes(snapshot)


def _invalid_intent_lock(repo: Path, path: Path, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "repo": str(repo),
        "path": str(path),
        "error": f"INTENT-LOCK.json is invalid: {detail}",
        "next_command": render_next_command(
            "intent", "capture", repo, "--want", "...", "--must-not", "...",
            "--proof", "...", "--force",
        ),
    }


def _validate_intent_lock_payload(lock: dict[str, Any]) -> str | None:
    if type(lock.get("schema_version")) is not int or lock["schema_version"] != 1:
        return "schema_version must be the integer 1"
    for field in _LOCK_STRING_FIELDS:
        if not isinstance(lock.get(field), str):
            return f"{field} must be a string"
    for field in _LOCK_LIST_FIELDS:
        values = lock.get(field)
        if not isinstance(values, list):
            return f"{field} must be a list of strings"
        for index, value in enumerate(values):
            if not isinstance(value, str):
                return f"{field}[{index}] must be a string"
    policy = lock.get("audit_policy")
    if not isinstance(policy, dict):
        return "audit_policy must be a JSON object"
    for field in ("strict_phrase_preservation", "confidence_claims_require_evidence"):
        if not isinstance(policy.get(field), bool):
            return f"audit_policy.{field} must be a boolean"
    categories = policy.get("required_categories")
    if not isinstance(categories, list) or any(not isinstance(item, str) for item in categories):
        return "audit_policy.required_categories must be a list of strings"
    if categories != list(_LOCK_REQUIRED_CATEGORIES):
        return "audit_policy.required_categories must list every supported category in schema order"
    return None


def capture_intent_lock(repo_path: Path, *, want: str = "", outcomes: list[str] | None = None, must_not: list[str] | None = None, proof: list[str] | None = None, corrections: list[str] | None = None, rejected: list[str] | None = None, questions: list[str] | None = None, scopes: list[str] | None = None, source: str = "", force: bool = False) -> dict[str, Any]:
    repo = git_root(repo_path)
    path = intent_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with config_mutation_lock(path):
        if path.exists() and not force:
            raise ConfigurationError(f"Intent lock already exists: {path}. Use `--force` only when replacing the current locked intent.")
        lock = _lock_payload(repo, want=want, outcomes=outcomes, must_not=must_not, proof=proof, corrections=corrections, rejected=rejected, questions=questions, scopes=scopes, source=source)
        markdown_path = _publish_lock_pair(path, lock)
        lock, lock_hash = _read_lock_snapshot(path)
    return {"ok": True, "repo": str(repo), "path": str(path), "markdown_path": str(markdown_path), "lock_hash": lock_hash, "next_command": render_next_command("compact", "audit", repo, "--summary", "SUMMARY.md"), "lock": lock}


def read_intent_lock(repo_path: Path) -> dict[str, Any]:
    repo = git_root(repo_path)
    path = intent_lock_path(repo)
    if not path.exists():
        return {"ok": False, "repo": str(repo), "path": str(path), "error": "No intent lock exists yet.", "next_command": render_next_command("intent", "capture", repo, "--want", "...", "--must-not", "...", "--proof", "...")}
    lock, lock_hash = _read_lock_snapshot(path)
    if not isinstance(lock, dict):
        return _invalid_intent_lock(repo, path, "top-level value must be a JSON object")
    problem = _validate_intent_lock_payload(lock)
    if problem:
        return _invalid_intent_lock(repo, path, problem)
    return {"ok": True, "repo": str(repo), "path": str(path), "markdown_path": str(intent_lock_markdown_path(repo)), "lock_hash": lock_hash, "lock": lock}


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
    def is_affirmative(match: re.Match[str]) -> bool:
        start, end = match.span()
        clause_start = max(summary_text.rfind(delimiter, 0, start) for delimiter in ".!?;:\n") + 1
        following_boundaries = [
            boundary
            for delimiter in ".!?;:\n"
            if (boundary := summary_text.find(delimiter, end)) >= 0
        ]
        clause_end = min(following_boundaries) if following_boundaries else len(summary_text)
        clause = summary_text[clause_start:clause_end]
        relative_start = start - clause_start
        relative_end = end - clause_start
        if _inside_quoted_span(clause, relative_start, relative_end):
            return False
        prefix = summary_text[clause_start:start]
        suffix = summary_text[end:clause_end]
        suffix_state = re.sub(
            r"^\s*(?:(?:is|was|remains?)\s+)?", "", suffix, flags=re.IGNORECASE
        ).lstrip(" ,-–—")
        return not (
            _NEGATION_IN_CLAUSE.search(prefix)
            or _NEGATION_IN_CLAUSE.match(suffix_state)
            or _NONAFFIRMATIVE_CLAIM_STATE.search(suffix)
        )

    return [
        {"code": "confidence_claim", "text": match.group(0), "detail": "Avoid absolute quality or completion claims unless current evidence is listed."}
        for match in _CONFIDENCE_PATTERN.finditer(summary_text)
        if is_affirmative(match)
    ]


def audit_compaction_text(repo_path: Path, summary_text: str, *, summary_path: Path | None = None) -> dict[str, Any]:
    repo = git_root(repo_path)
    lock_report = read_intent_lock(repo)
    if not lock_report.get("ok"):
        return {"ok": False, "status": "blocked", "repo": str(repo), "lock_path": lock_report["path"], "summary_path": str(summary_path.resolve()) if summary_path else "", "summary_hash": sha256_text(summary_text), "missing": [{"category": "intent_lock", "text": lock_report["error"]}], "warnings": [], "next_command": lock_report["next_command"]}
    lock = lock_report["lock"]
    normalized_summary = _normalize(summary_text)
    missing = [item for item in _required_phrases(lock) if _normalize(item["text"]) not in normalized_summary]
    warnings = _confidence_warnings(summary_text)
    ok = not missing
    return {
        "ok": ok, "status": "passed" if ok else "blocked", "repo": str(repo), "lock_path": lock_report["path"],
        "lock_hash": lock_report["lock_hash"], "summary_path": str(summary_path.resolve()) if summary_path else "",
        "summary_hash": sha256_text(summary_text), "missing": missing, "warnings": warnings,
        "checked_categories": sorted({item["category"] for item in _required_phrases(lock)}),
        "next_command": render_next_command("intent", "show", repo) if missing else render_next_command("run", "--repo", repo, "--apply"),
    }


def audit_compaction_file(repo_path: Path, summary_path: Path) -> dict[str, Any]:
    path = summary_path.resolve()
    return audit_compaction_text(repo_path, path.read_text(encoding="utf-8", errors="replace"), summary_path=path)


def save_compaction_checkpoint(repo_path: Path, summary_path: Path) -> dict[str, Any]:
    repo = git_root(repo_path)
    summary = summary_path.resolve()
    summary_text = summary.read_text(encoding="utf-8", errors="replace")
    audit = audit_compaction_text(repo, summary_text, summary_path=summary)
    checkpoint_root = intent_root(repo) / "checkpoints"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    stem = f"{utc_now().replace(':', '').replace('+', 'Z')}-{summary.stem}"
    copied_summary = checkpoint_root / f"{stem}.md"
    copied_audit = checkpoint_root / f"{stem}.audit.json"
    atomic_write_text(copied_summary, summary_text)
    if sha256_file(copied_summary) != audit["summary_hash"]:
        raise ConfigurationError("Compaction checkpoint hash does not match its audit.")
    atomic_write_json(copied_audit, audit)
    audit["checkpoint_path"] = str(copied_summary)
    audit["checkpoint_audit_path"] = str(copied_audit)
    return audit


def pinned_context_block(repo_path: Path) -> dict[str, Any]:
    report = read_intent_lock(repo_path)
    if not report.get("ok"):
        return report
    lines = ["# Pinned Intent Context", "", "Keep this block near the beginning and end of long-running agent packets.", "Do not compress away these exact items.", ""]
    for item in _required_phrases(report["lock"]):
        lines.append(f"- {item['category']}: {item['text']}")
    text = "\n".join(lines) + "\n"
    return {"ok": True, "repo": report["repo"], "path": report["path"], "content": text, "content_hash": sha256_text(text)}


def format_intent_lock(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        lines = ["INTENT LOCK: MISSING", f"Path: {report.get('path', '')}"]
        if report.get("error"):
            lines.append(f"Error: {report['error']}")
        if report.get("next_command"):
            lines.append(f"Next: {report['next_command']}")
        return "\n".join(lines) + "\n"
    lock = report.get("lock", {})
    lines = ["INTENT LOCK", f"Path: {report['path']}", f"Hash: {report.get('lock_hash', '')}", "", f"Want: {lock.get('want') or 'None recorded.'}", "", "Must not:", *_bullets(lock.get("must_not", [])), "", "Proof:", *_bullets(lock.get("proof", [])), "", "Corrections:", *_bullets(lock.get("corrections", [])), "", "Rejected:", *_bullets(lock.get("rejected", []))]
    return "\n".join(lines) + "\n"


def format_compaction_audit(report: dict[str, Any]) -> str:
    title = "COMPACTION AUDIT: PASSED" if report.get("ok") else "COMPACTION AUDIT: BLOCKED"
    lines = [title, f"Intent lock: {report.get('lock_path', '')}", f"Summary hash: {report.get('summary_hash', '')}"]
    for item in report.get("missing", []):
        lines.append(f"MISSING {item.get('category')}: {item.get('text')}")
    for item in report.get("warnings", []):
        lines.append(f"WARN {item.get('code')}: {item.get('text')} - {item.get('detail')}")
    if report.get("next_command"):
        lines.append(f"Next: {report['next_command']}")
    return "\n".join(lines) + "\n"
