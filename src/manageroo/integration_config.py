from __future__ import annotations

import json
import re
import shutil
import tomllib
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import DEFAULT_CONFIG, load_config
from .config_lock import config_mutation_lock
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
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(value: str) -> str:
    return value if _BARE_KEY_RE.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    if isinstance(value, dict):
        raise TypeError("Nested integration dictionaries must be emitted as TOML tables.")
    return json.dumps(str(value), ensure_ascii=False)


def _ordered_keys(values: dict[str, Any]) -> list[str]:
    known = [key for key in INTEGRATION_ORDER if key in values]
    known.extend(sorted(key for key in values if key not in INTEGRATION_ORDER))
    return known


def _render_table(lines: list[str], path: list[str], values: dict[str, Any]) -> None:
    lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
    for key in _ordered_keys(values):
        value = values[key]
        if isinstance(value, dict):
            continue
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    for key in _ordered_keys(values):
        value = values[key]
        if not isinstance(value, dict):
            continue
        lines.append("")
        _render_table(lines, [*path, key], value)


def _integrations_block(values: dict[str, Any]) -> str:
    lines: list[str] = []
    _render_table(lines, ["integrations"], values)
    return "\n".join(lines)


def _is_integrations_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return False
    inner = stripped.strip("[]").strip()
    return inner == "integrations" or inner.startswith("integrations.") or inner.startswith('"integrations".')


def replace_integrations_block(text: str, values: dict[str, Any]) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    inserted = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if _is_integrations_header(line):
                if not inserted:
                    kept.extend(_integrations_block(values).splitlines())
                    kept.append("")
                    inserted = True
                skipping = True
                continue
            skipping = False
        if not skipping:
            kept.append(line)
    if not inserted:
        if kept and any(line.strip() for line in kept):
            kept.extend(["", *_integrations_block(values).splitlines()])
        else:
            kept.extend(_integrations_block(values).splitlines())
    updated = "\n".join(kept).rstrip() + "\n"
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Refusing to write invalid integration configuration: {exc}") from exc
    return updated


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
    records: list[dict[str, Any]] = []

    def mutate() -> tuple[dict[str, Any], bool]:
        config = load_config(repo)
        values = dict(DEFAULT_CONFIG["integrations"])
        values.update(config.get("integrations", {}))
        records.clear()
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
                records.append({"name": "gbrain", "installed": True, "path": installed, "status": "configured" if changed else "kept"})
            else:
                records.append({"name": "gbrain", "installed": False, "status": "missing", "next": "Install GBrain."})
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
                records.append({"name": "gitnexus", "installed": True, "path": installed, "status": "configured" if changed else "kept"})
            else:
                records.append({"name": "gitnexus", "installed": False, "status": "missing", "next": "Install GitNexus."})
        changed = any(record["status"] == "configured" for record in records)
        return values, changed

    if apply:
        with config_mutation_lock(config_path):
            values, changed = mutate()
            if changed:
                updated = replace_integrations_block(config_path.read_text(encoding="utf-8"), values)
                atomic_write_text(config_path, updated)
    else:
        values, changed = mutate()
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
