from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .project_memory import ensure_project_memory
from .util import atomic_write_json, read_json, safe_repo_relative, utc_now

LEARNING_SCHEMA_VERSION = 1
RISK_RANK = {"low": 1, "medium": 2, "high": 3}


def learning_root(repo: Path) -> Path:
    return repo / PROJECT_DIR / "cache" / "learning"


def pending_root(repo: Path) -> Path:
    return learning_root(repo) / "pending"


def _fingerprint(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _card_id(card: dict[str, Any]) -> str:
    identity = [card["title"], card["destination"], card["recommendation"]]
    if card.get("category") == "project-memory" and card.get("apply_kind") == "project_memory_note":
        identity.append(str(card.get("run_id") or "unknown-run"))
    return f"{card['category']}-{_fingerprint(*identity)}"


def _base_card(
    *,
    run_id: str,
    category: str,
    title: str,
    destination: str,
    recommendation: str,
    evidence: list[str],
    risk: str,
    priority: int,
    apply_policy: str,
    apply_kind: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card = {
        "schema_version": LEARNING_SCHEMA_VERSION,
        "id": "",
        "run_id": run_id,
        "category": category,
        "title": title,
        "destination": destination,
        "recommendation": recommendation,
        "evidence": [item for item in evidence if item],
        "risk": risk,
        "priority": priority,
        "apply_policy": apply_policy,
        "apply_kind": apply_kind,
        "payload": payload or {},
        "status": "pending",
        "created_at": utc_now(),
    }
    card["id"] = _card_id(card)
    return card


def generate_learning_cards(
    *,
    repo: Path,
    result: dict[str, Any],
    inventory: dict[str, Any] | None = None,
    external_intelligence: dict[str, Any] | None = None,
    external_review_repair: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    run_id = str(result.get("run_id") or "unknown-run")
    cards: list[dict[str, Any]] = []
    status = str(result.get("status") or "UNKNOWN")
    evidence_paths = result.get("evidence_paths", {}) if isinstance(result.get("evidence_paths"), dict) else {}
    run_root = str(evidence_paths.get("run_root") or "")
    if status == "COMPLETE":
        files_changed = result.get("files_changed", [])
        summary = str(result.get("product_summary") or "MANAGEROO run completed.")
        cards.append(_base_card(
            run_id=run_id,
            category="project-memory",
            title="Record the completed run in project memory",
            destination="project-memory",
            recommendation="Add a short operator note so future agents know this run completed and where the evidence lives.",
            evidence=[
                f"run {run_id} completed",
                f"changed files: {len(files_changed) if isinstance(files_changed, list) else 0}",
                f"run evidence: {run_root}",
            ],
            risk="low",
            priority=80,
            apply_policy="approval_required",
            apply_kind="project_memory_note",
            payload={
                "notes": [f"Learning note: {summary} Run {run_id} completed. Evidence: {run_root or 'run artifacts'}."],
                "proof": [f"MANAGEROO run {run_id} completed."],
            },
        ))
    else:
        cards.append(_base_card(
            run_id=run_id,
            category="blocker",
            title="Review blocked run and decide the next repair",
            destination="future-backlog",
            recommendation="Keep this blocker as a pending learning item until the operator or agent turns it into a concrete fix, check, or skill.",
            evidence=[
                f"run {run_id} ended with status {status}",
                f"{result.get('error_type', 'Error')}: {result.get('error', '')}".strip(),
                f"run evidence: {run_root}",
            ],
            risk="medium",
            priority=90,
            apply_policy="manual_only",
            apply_kind="none",
        ))

    risks = result.get("risks", [])
    if isinstance(risks, list) and risks:
        cards.append(_base_card(
            run_id=run_id,
            category="future-backlog",
            title="Turn remaining run risks into follow-up work",
            destination="future-backlog",
            recommendation="Review the remaining risks and make a separate scoped issue, brief, or skill if they repeat.",
            evidence=[f"run risk: {risk}" for risk in risks[:8]] + [f"run evidence: {run_root}"],
            risk="medium", priority=70, apply_policy="manual_only", apply_kind="none",
        ))

    failed_optional: list[Any] = []
    if external_intelligence:
        summary = external_intelligence.get("summary", {})
        if isinstance(summary, dict):
            candidate = summary.get("failed_optional", [])
            if isinstance(candidate, list):
                failed_optional = candidate
    if failed_optional:
        cards.append(_base_card(
            run_id=run_id,
            category="tool-lane",
            title="Fix optional repo intelligence tools that failed",
            destination="config-or-installer",
            recommendation="Check the configured GBrain/GitNexus command lane before relying on external repo intelligence in future runs.",
            evidence=[f"failed optional tool: {item}" for item in failed_optional] + [f"run evidence: {run_root}"],
            risk="medium", priority=65, apply_policy="manual_only", apply_kind="none",
        ))

    if external_review_repair:
        summary = external_review_repair.get("summary", {})
        failed = summary.get("failed", []) if isinstance(summary, dict) else []
        if failed:
            cards.append(_base_card(
                run_id=run_id,
                category="review-repair-lane",
                title="Fix command-owned review/repair lane failure",
                destination="config-or-installer",
                recommendation="Do not freehand this repair. Fix the configured AUTOREVIEW or Clawpatch command and rerun the lane.",
                evidence=[f"failed command-owned lane: {item}" for item in failed] + [f"run evidence: {run_root}"],
                risk="medium", priority=85, apply_policy="manual_only", apply_kind="none",
            ))

    summary = inventory.get("summary", {}) if isinstance(inventory, dict) else {}
    content_kinds = summary.get("content_kinds", {}) if isinstance(summary, dict) else {}
    if isinstance(content_kinds, dict) and int(content_kinds.get("media", 0) or 0) > 0:
        cards.append(_base_card(
            run_id=run_id,
            category="tool-lane",
            title="Consider a visual evidence lane for media-heavy work",
            destination="config-or-installer",
            recommendation="This repo contains media. If the requested work depends on visual understanding, configure a visual evidence command lane before trusting the run.",
            evidence=[f"media files detected: {content_kinds.get('media')}", f"inventory artifact: {run_root}/artifacts/discovery/inventory.json" if run_root else ""],
            risk="medium", priority=60, apply_policy="manual_only", apply_kind="none",
        ))
    if isinstance(content_kinds, dict) and int(content_kinds.get("prose", 0) or 0) > 0:
        cards.append(_base_card(
            run_id=run_id,
            category="tool-lane",
            title="Consider a document/prose lane for long-writing work",
            destination="config-or-installer",
            recommendation="This repo contains prose. If the requested work depends on exact long-document edits, use bounded line ranges or configure a document lane.",
            evidence=[f"prose files detected: {content_kinds.get('prose')}", f"inventory artifact: {run_root}/artifacts/discovery/inventory.json" if run_root else ""],
            risk="medium", priority=55, apply_policy="manual_only", apply_kind="none",
        ))
    return sorted(cards, key=lambda item: (-int(item["priority"]), RISK_RANK.get(str(item["risk"]), 99), item["id"]))


def save_pending_learning_cards(repo: Path, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = pending_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    for card in cards:
        path = root / f"{safe_repo_relative(card['id'])}.json"
        if path.exists():
            existing = read_json(path)
            if existing.get("status") != "pending":
                continue
            card = {
                **existing,
                "recurrence_count": int(existing.get("recurrence_count", 1)) + 1,
                "last_seen_run_id": card.get("run_id"),
                "last_seen_at": utc_now(),
                "evidence": sorted(set([*existing.get("evidence", []), *card.get("evidence", [])])),
            }
        else:
            card = {**card, "recurrence_count": 1, "last_seen_run_id": card.get("run_id"), "last_seen_at": card.get("created_at")}
        atomic_write_json(path, card)
        saved.append({**card, "path": str(path)})
    return saved


def list_learning_cards(repo: Path, status: str = "pending") -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    root = pending_root(repo)
    if not root.exists():
        return []
    for path in sorted(root.glob("*.json")):
        item = read_json(path)
        if status != "all" and item.get("status") != status:
            continue
        cards.append({**item, "path": str(path)})
    return sorted(cards, key=lambda item: (-int(item.get("priority", 0)), RISK_RANK.get(str(item.get("risk")), 99), item["id"]))


def get_learning_card(repo: Path, card_id: str) -> dict[str, Any]:
    path = pending_root(repo) / f"{safe_repo_relative(card_id)}.json"
    if not path.exists():
        return {"ok": False, "card_id": card_id, "error": "Learning card was not found.", "next_command": f"{PUBLIC_COMMAND} learning list"}
    return {"ok": True, "card": {**read_json(path), "path": str(path)}}


def apply_learning_card(repo: Path, card_id: str, *, approve: bool = False) -> dict[str, Any]:
    loaded = get_learning_card(repo, card_id)
    if not loaded["ok"]:
        return loaded
    card = loaded["card"]
    if card.get("status") != "pending":
        return {"ok": False, "card_id": card_id, "error": f"Card is {card.get('status')}, not pending."}
    if not approve:
        return {
            "ok": False,
            "card_id": card_id,
            "requires_approval": True,
            "risk": card.get("risk"),
            "recommendation": card.get("recommendation"),
            "next_command": f"{PUBLIC_COMMAND} learning apply {card_id} --approve",
        }
    if card.get("apply_kind") != "project_memory_note":
        return {"ok": False, "card_id": card_id, "error": "This learning card is manual-only. No automatic apply is available.", "apply_kind": card.get("apply_kind")}
    payload = card.get("payload", {})
    memory_update = ensure_project_memory(repo, notes=payload.get("notes", []), proof=payload.get("proof", []))
    card = {**card, "status": "applied", "applied_at": utc_now(), "applied_to": memory_update["path"]}
    atomic_write_json(Path(card["path"]), card)
    return {"ok": True, "card": card, "project_memory_update": memory_update}


def format_learning_cards(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "No learning cards found.\n"
    lines = ["Learning cards:"]
    for card in cards:
        lines.append(f"- {card['id']} [{card.get('risk', 'unknown')} risk, priority {card.get('priority', 0)}] {card.get('title', '')}")
        lines.append(f"  destination: {card.get('destination', 'unknown')}")
        lines.append(f"  next: {PUBLIC_COMMAND} learning show {card['id']}")
    return "\n".join(lines) + "\n"


def format_learning_card(card: dict[str, Any]) -> str:
    lines = [
        f"Learning card: {card['id']}", f"Status: {card.get('status', 'unknown')}",
        f"Risk: {card.get('risk', 'unknown')}", f"Priority: {card.get('priority', 0)}",
        f"Destination: {card.get('destination', 'unknown')}", "", card.get("title", ""), "",
        card.get("recommendation", ""), "", "Evidence:",
    ]
    lines.extend(f"- {item}" for item in card.get("evidence", []))
    lines.extend(["", f"Apply policy: {card.get('apply_policy', 'unknown')}"])
    if card.get("apply_kind") == "project_memory_note":
        lines.append(f"Next: {PUBLIC_COMMAND} learning apply {card['id']} --approve")
    else:
        lines.append("Next: inspect this manual-only card and decide the scoped follow-up.")
    return "\n".join(lines) + "\n"
