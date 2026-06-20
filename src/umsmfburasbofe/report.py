from __future__ import annotations

from pathlib import Path

from .branding import FULL_NAME
from typing import Any

from .util import atomic_write_text


def build_report(data: dict[str, Any]) -> str:
    lines = [
        f"# {FULL_NAME} — Delivery Report",
        "",
        f"**Run:** `{data['run_id']}`",
        f"**Status:** **{data['status']}**",
        f"**Mode:** `{data.get('mode', 'unknown')}`",
        "",
        "## Product outcome",
        "",
        data.get("product_summary", "No product summary was produced."),
        "",
        "## Observable acceptance",
        "",
    ]
    outcomes = data.get("acceptance", [])
    if outcomes:
        lines.extend(f"- {'✓' if item.get('passed') else '✗'} {item.get('description')}" for item in outcomes)
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
    for gate in data.get("gates", []):
        result = gate.get("result", {})
        lines.append(
            f"- {'✓' if result.get('exit_code') == 0 else '✗'} "
            f"`{' '.join(result.get('argv', gate.get('gate', {}).get('argv', [])))}`"
        )
    lines.extend(["", "## Independent review", ""])
    review = data.get("review", {})
    lines.append(f"- Status: **{review.get('status', 'not-run')}**")
    lines.append(f"- Blocking findings: {sum(1 for item in review.get('findings', []) if item.get('blocking'))}")
    lines.extend(["", "## Files changed", ""])
    files = data.get("files_changed", [])
    lines.extend(f"- `{item}`" for item in files) if files else lines.append("- None.")
    lines.extend(["", "## Remaining risks", ""])
    risks = data.get("risks", [])
    lines.extend(f"- {item}" for item in risks) if risks else lines.append("- None recorded.")
    lines.extend(["", "## Evidence locations", ""])
    for key, value in data.get("evidence_paths", {}).items():
        lines.append(f"- **{key}:** `{value}`")
    lines.append("")
    return "\n".join(lines)


def write_report(path: Path, data: dict[str, Any]) -> str:
    markdown = build_report(data)
    atomic_write_text(path, markdown)
    return markdown
