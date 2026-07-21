from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import DEFAULT_CONFIG, load_config
from .errors import ConfigurationError
from .util import atomic_write_text


GBRAIN_SEARCH_COMMAND = ["gbrain", "search", "{query}", "--json"]
GBRAIN_CAPTURE_COMMAND = ["gbrain", "capture", "--file", "{report_file}"]
GITNEXUS_ANALYZE_COMMAND = ["gitnexus", "analyze", "{repo}", "--json"]
GITNEXUS_QUERY_COMMAND = ["gitnexus", "query", "{query}", "--json"]

INTEGRATION_ORDER = [
    "obsidian_vault",
    "obsidian_export_folder",
    "gbrain_search_command",
    "gbrain_capture_command",
    "gitnexus_analyze_command",
    "gitnexus_query_command",
    "document_analysis_command",
    "autoreview_command",
    "clawpatch_command",
]


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(str(value))


def _integrations_block(values: dict[str, Any]) -> str:
    lines = ["[integrations]"]
    ordered_keys = [key for key in INTEGRATION_ORDER if key in values]
    ordered_keys.extend(sorted(key for key in values if key not in INTEGRATION_ORDER))
    for key in ordered_keys:
        lines.append(f"{key} = {_toml_value(values[key])}")
    return "\n".join(lines)


def replace_integrations_block(text: str, values: dict[str, Any]) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == "[integrations]"), None)
    block = _integrations_block(values).splitlines()
    if start is None:
        return text.rstrip() + "\n\n" + "\n".join(block) + "\n"
    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith("["):
        end += 1
    return "\n".join([*lines[:start], *block, "", *lines[end:]]).rstrip() + "\n"


def _next_command(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("status") == "missing":
            if record["name"] == "gbrain":
                return f"Install GBrain, then run `{PUBLIC_COMMAND} integrations configure`."
            if record["name"] == "gitnexus":
                return f"Install GitNexus, then run `{PUBLIC_COMMAND} integrations configure`."
    return f"{PUBLIC_COMMAND} ready"


def configure_integrations(
    repo: Path,
    *,
    gbrain: bool = True,
    gitnexus: bool = True,
    apply: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.exists():
        raise ConfigurationError(f"Missing {config_path}. Run `{PUBLIC_COMMAND} init` first.")
    config = load_config(repo)
    values = dict(DEFAULT_CONFIG["integrations"])
    # Preserve every existing key, including custom and forward-version integration
    # settings Manageroo does not currently know how to configure itself.
    values.update(config.get("integrations", {}))
    records: list[dict[str, Any]] = []

    if gbrain:
        installed = shutil.which("gbrain")
        if installed:
            changed = False
            if force or not values.get("gbrain_search_command"):
                values["gbrain_search_command"] = GBRAIN_SEARCH_COMMAND
                changed = True
            if force or not values.get("gbrain_capture_command"):
                values["gbrain_capture_command"] = GBRAIN_CAPTURE_COMMAND
                changed = True
            records.append(
                {
                    "name": "gbrain",
                    "installed": True,
                    "path": installed,
                    "status": "configured" if changed else "kept",
                }
            )
        else:
            records.append(
                {
                    "name": "gbrain",
                    "installed": False,
                    "status": "missing",
                    "next": "Install GBrain.",
                }
            )

    if gitnexus:
        installed = shutil.which("gitnexus")
        if installed:
            changed = False
            if force or not values.get("gitnexus_analyze_command"):
                values["gitnexus_analyze_command"] = GITNEXUS_ANALYZE_COMMAND
                changed = True
            if force or not values.get("gitnexus_query_command"):
                values["gitnexus_query_command"] = GITNEXUS_QUERY_COMMAND
                changed = True
            records.append(
                {
                    "name": "gitnexus",
                    "installed": True,
                    "path": installed,
                    "status": "configured" if changed else "kept",
                }
            )
        else:
            records.append(
                {
                    "name": "gitnexus",
                    "installed": False,
                    "status": "missing",
                    "next": "Install GitNexus.",
                }
            )

    changed = any(record["status"] == "configured" for record in records)
    if apply and changed:
        updated = replace_integrations_block(config_path.read_text(encoding="utf-8"), values)
        atomic_write_text(config_path, updated)
    ok = all(record["status"] != "missing" for record in records)
    return {
        "ok": ok,
        "applied": bool(apply and changed),
        "config": str(config_path),
        "records": records,
        "next_command": _next_command(records),
    }


def format_integration_config(report: dict[str, Any]) -> str:
    lines = ["INTEGRATIONS CONFIGURED" if report.get("ok") else "INTEGRATIONS NEED ACTION"]
    for record in report.get("records", []):
        lines.append(f"{record['name']}: {record['status']}")
    lines.append(f"Next: {report.get('next_command', f'{PUBLIC_COMMAND} ready')}")
    return "\n".join(lines) + "\n"