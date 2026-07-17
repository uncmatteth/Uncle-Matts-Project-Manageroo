from __future__ import annotations

import copy
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

from .branding import FULL_ACRONYM, PROJECT_DIR, PUBLIC_COMMAND
from .errors import ConfigurationError
from .util import atomic_write_text


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "apply_on_success": True,
        "max_repair_cycles": 2,
        "max_plan_review_cycles": 2,
        "require_demonstration": True,
    },
    "agent": {
        "adapter": "codex",
        "executable": "codex",
        "model": "",
        "timeout_seconds": 3600,
    },
    "context": {
        "max_input_tokens": 60000,
        "reserve_output_tokens": 12000,
        "chars_per_token": 3.5,
        "max_single_file_tokens": 18000,
        "map_chunk_tokens": 32000,
    },
    "orchestration": {
        "max_parallel_agent_calls": 4,
        "max_worker_attempts": 2,
        "parallel_mapping": True,
        "parallel_review": True,
    },
    "safety": {
        "allowed_programs": [
            "python", "python3", "node", "npm", "pnpm", "yarn", "bun",
            "cargo", "go", "dotnet", "mvn", "gradle", "gradlew", "make",
        ],
        "block_agent_commits": True,
        "require_source_unchanged_before_apply": True,
    },
    "verification": {"gates": []},
    "integrations": {
        "obsidian_vault": "",
        "obsidian_export_folder": FULL_ACRONYM,
        "gbrain_search_command": [],
        "gbrain_capture_command": [],
        "gitnexus_analyze_command": [],
        "gitnexus_query_command": [],
        "document_analysis_command": [],
        "autoreview_command": [],
        "clawpatch_command": [],
    },
}

AGENT_PRESETS: dict[str, dict[str, Any]] = {
    "codex": {
        "adapter": "codex",
        "executable": "codex",
        "model": "",
        "timeout_seconds": 3600,
    },
    "mock": {
        "adapter": "mock",
        "executable": "python",
        "model": "",
        "timeout_seconds": 3600,
    },
    "generic": {
        "adapter": "generic",
        "executable": "YOUR_AGENT",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "file_path",
        "argv_template": [
            "YOUR_AGENT",
            "--prompt-file",
            "{prompt}",
            "--schema",
            "{schema}",
            "--output",
            "{output}",
        ],
    },
    "claude-code": {
        "adapter": "generic",
        "executable": "claude",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "stdin",
        "argv_template": [
            "claude",
            "-p",
            "Follow the complete Manageroo assignment provided on stdin. Return only the requested JSON object.",
        ],
    },
    "gemini": {
        "adapter": "generic",
        "executable": "gemini",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "stdin",
        "argv_template": [
            "gemini",
            "-p",
            "Follow the complete Manageroo assignment provided on stdin. Return only the requested JSON object.",
        ],
    },
}


def _merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(repo: Path) -> dict[str, Any]:
    path = repo / PROJECT_DIR / "config.toml"
    if not path.exists():
        raise ConfigurationError(f"Missing {path}. Run `{PUBLIC_COMMAND} init` first.")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return _merge(DEFAULT_CONFIG, raw)


def agent_preset(name: str) -> dict[str, Any]:
    try:
        return copy.deepcopy(AGENT_PRESETS[name])
    except KeyError as exc:
        available = ", ".join(sorted(AGENT_PRESETS))
        raise ConfigurationError(f"Unknown agent preset {name!r}. Available: {available}") from exc


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(str(value))


def _render_agent_table(agent: dict[str, Any]) -> str:
    ordered = ["adapter", "executable", "model", "timeout_seconds", "prompt_transport", "argv_template"]
    lines = ["[agent]"]
    for key in ordered:
        if key in agent:
            lines.append(f"{key} = {_toml_value(agent[key])}")
    for key in sorted(set(agent) - set(ordered)):
        lines.append(f"{key} = {_toml_value(agent[key])}")
    return "\n".join(lines)


def apply_agent_preset(repo: Path, name: str) -> dict[str, Any]:
    path = repo / PROJECT_DIR / "config.toml"
    if not path.exists():
        raise ConfigurationError(f"Missing {path}. Run `{PUBLIC_COMMAND} init` first.")
    config = load_config(repo)
    selected = agent_preset(name)
    config["agent"] = selected

    text = path.read_text(encoding="utf-8")
    start = text.find("[agent]")
    if start == -1:
        rendered = text.rstrip() + "\n\n" + _render_agent_table(selected) + "\n"
    else:
        next_table = text.find("\n[", start + 1)
        end = len(text) if next_table == -1 else next_table + 1
        rendered = text[:start] + _render_agent_table(selected) + "\n" + text[end:]
    atomic_write_text(path, rendered)
    return {
        "ok": True,
        "name": name,
        "config_path": str(path),
        "agent": selected,
        "executable_found": bool(shutil.which(selected.get("executable", ""))),
    }
