from __future__ import annotations

from pathlib import Path

from .branding import FULL_NAME
from typing import Any

from .util import atomic_write_text


def _blocking_count(review: dict[str, Any]) -> int:
    return sum(1 for item in review.get("findings", []) if item.get("blocking"))


def _yes_no_unknown(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _external_lane_summary(data: dict[str, Any]) -> dict[str, Any] | None:
    external = data.get("external_review_repair")
    if not isinstance(external, dict):
        return None
    summary = external.get("summary", {})
    return summary if isinstance(summary, dict) else None


def build_report(data: dict[str, Any]) -> str:
    review = data.get("review", {})
    gates = data.get("gates", [])
    files = data.get("files_changed", [])
    applied = data.get("applied_to_source")
    external_lane = _external_lane_summary(data)
    lines = [
        f"# {FULL_NAME} — Delivery Report",
        "",
        f"**Run:** `{data['run_id']}`",
        f"**Status:** **{data['status']}**",
        f"**Mode:** `{data.get('mode', 'unknown')}`",
        "",
        "## Plain English",
        "",
        f"- Result: **{data['status']}**",
        f"- Applied to source repo: {_yes_no_unknown(applied)}",
        f"- Files changed: {len(files)}",
        f"- Verification gates recorded: {len(gates)}",
        f"- Blocking review findings: {_blocking_count(review)}",
    ]
    if data.get("error"):
        lines.append(f"- Error: {data.get('error_type', 'Error')}: {data['error']}")
    lines.extend(
        [
            "",
            "## Product outcome",
            "",
            data.get("product_summary", "No product summary was produced."),
            "",
            "## Observable acceptance",
            "",
        ]
    )
    outcomes = data.get("acceptance", [])
    if outcomes:
        lines.extend(
            f"- {'✓' if item.get('passed') else '✗'} {item.get('description')}"
            for item in outcomes
        )
    else:
        lines.append("- No acceptance outcomes recorded.")
    lines.extend(["", "## Reuse decisions", ""])
    reuse = data.get("reuse", [])
    if reuse:
        for item in reuse:
            lines.append(
                f"- **{item.get('need', 'unknown')}** → {item.get('decision', 'unknown')}: "
                f"{item.get('candidate', 'n/a')}"
            )
    else:
        lines.append("- None recorded.")
    lines.extend(["", "## Verification", ""])
    if not gates:
        lines.append("- No verification gates recorded.")
    for gate in gates:
        result = gate.get("result", {})
        exit_code = result.get("exit_code", "unknown")
        lines.append(
            f"- {'✓' if result.get('exit_code') == 0 else '✗'} "
            f"`{' '.join(result.get('argv', gate.get('gate', {}).get('argv', [])))}` "
            f"(exit {exit_code})"
        )
    lines.extend(["", "## Independent review", ""])
    lines.append(f"- Status: **{review.get('status', 'not-run')}**")
    lines.append(f"- Blocking findings: {_blocking_count(review)}")
    if external_lane:
        lines.extend(["", "## Command-owned review/repair lanes", ""])
        lines.append(f"- Enabled: {', '.join(external_lane.get('enabled', [])) or 'none'}")
        lines.append(f"- Passed: {', '.join(external_lane.get('passed', [])) or 'none'}")
        lines.append(f"- Failed: {', '.join(external_lane.get('failed', [])) or 'none'}")
        lines.append(f"- Changed paths: {len(external_lane.get('changed_paths', []))}")
        lines.append("- AI freehand repair from AUTOREVIEW/Clawpatch findings: no")
    lines.extend(["", "## Files changed", ""])
    lines.extend(f"- `{item}`" for item in files) if files else lines.append("- None.")
    lines.extend(["", "## Remaining risks", ""])
    risks = data.get("risks", [])
    lines.extend(f"- {item}" for item in risks) if risks else lines.append("- None recorded.")
    lines.extend(["", "## Evidence locations", ""])
    evidence = data.get("evidence_paths", {})
    if not evidence:
        lines.append("- None recorded.")
    for key, value in evidence.items():
        lines.append(f"- **{key}:** `{value}`")
    lines.extend(["", "## Next inspection commands", ""])
    run_root = evidence.get("run_root")
    if run_root:
        lines.append(f"- `ls {run_root}`")
        lines.append(f"- `cat {run_root}/delivery/final-result.json`")
    else:
        lines.append("- No run root recorded.")
    lines.append("")
    return "\n".join(lines)


def write_report(path: Path, data: dict[str, Any]) -> str:
    markdown = build_report(data)
    atomic_write_text(path, markdown)
    return markdown
