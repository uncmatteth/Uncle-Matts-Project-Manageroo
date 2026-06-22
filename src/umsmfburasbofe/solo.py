from __future__ import annotations

from typing import Any

from .branding import PUBLIC_COMMAND
from .readiness import format_readiness


def solo_run_command(*, mode: str, apply_on_success: bool) -> str:
    apply_flag = "--apply" if apply_on_success else "--no-apply"
    return f"{PUBLIC_COMMAND} run --mode {mode} {apply_flag}"


def solo_next_command(
    readiness_report: dict[str, Any],
    integration_config: dict[str, Any],
    *,
    integration_guidance: list[dict[str, Any]] | None = None,
    mode: str,
    apply_on_success: bool,
    run_result: dict[str, Any] | None = None,
) -> str:
    if run_result and run_result.get("run_id"):
        return f"{PUBLIC_COMMAND} report {run_result['run_id']}"
    for item in readiness_report.get("items", []):
        if item.get("required", True) and not item.get("ok") and item.get("next"):
            return item["next"]
    if not integration_config.get("ok") and integration_config.get("next_command"):
        return integration_config["next_command"]
    for item in integration_guidance or []:
        if not item.get("ok") and item.get("next"):
            return item["next"]
    return solo_run_command(mode=mode, apply_on_success=apply_on_success)


def format_solo_report(payload: dict[str, Any]) -> str:
    lines = [
        "SOLO OPERATOR MODE",
        f"Repo: {payload['repo']}",
        f"Brief: {payload['brief']}",
        f"Agent: {payload['agent_name']}",
        f"Mode: {payload['mode']}",
        "",
        "What happened:",
    ]
    if payload.get("created_project"):
        created = payload["created_project"]
        lines.append(f"OK project repository {created.get('status', 'created')}")
    lines.extend(
        [
            "OK project initialized",
            "OK product brief written from your request",
        ]
    )
    if payload.get("installed_skills") == []:
        lines.append("OK skill pack install skipped by flag")
    else:
        lines.append("OK recommended skill pack installed or refreshed")
    if payload.get("integration_config", {}).get("records"):
        for record in payload["integration_config"]["records"]:
            label = "OK" if record.get("status") in {"configured", "kept"} else "ACTION"
            lines.append(f"{label} {record['name']}: {record['status']}")
    if payload.get("integration_guidance"):
        lines.append("")
        lines.append("Selected extras:")
        for item in payload["integration_guidance"]:
            label = "OK" if item.get("ok") else "ACTION"
            detail = item.get("detail", "")
            lines.append(f"{label} {item['name']}: {detail}")
    if payload.get("run_skipped_reason"):
        lines.append(f"ACTION run skipped: {payload['run_skipped_reason']}")
    if payload.get("run"):
        lines.append(f"OK run started: {payload['run'].get('run_id', 'unknown run')}")
    lines.extend(["", format_readiness(payload["readiness"], include_next=False).rstrip(), ""])
    lines.append(f"Next: {payload['next_command']}")
    return "\n".join(lines) + "\n"
