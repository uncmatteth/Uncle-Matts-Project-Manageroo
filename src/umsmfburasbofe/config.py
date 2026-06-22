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
        "argv_template": ["claude", "-p", "{prompt}"],
    },
    "gemini": {
        "adapter": "generic",
        "executable": "gemini",
        "model": "",
        "timeout_seconds": 3600,
        "argv_template": ["gemini", "-p", "{prompt}"],
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
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(str(value))


def _agent_block(preset_name: str, timeout_seconds: int | None = None) -> str:
    preset = agent_preset(preset_name)
    if timeout_seconds is not None:
        preset["timeout_seconds"] = timeout_seconds
    lines = ["[agent]"]
    for key in ["adapter", "executable", "model", "timeout_seconds", "argv_template"]:
        if key in preset:
            lines.append(f"{key} = {_toml_value(preset[key])}")
    return "\n".join(lines)


def replace_agent_block(text: str, preset_name: str) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == "[agent]"), None)
    if start is None:
        return _agent_block(preset_name) + "\n\n" + text.rstrip() + "\n"
    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith("["):
        end += 1
    replacement = _agent_block(preset_name).splitlines()
    return "\n".join([*lines[:start], *replacement, "", *lines[end:]]).rstrip() + "\n"


def config_template(agent: str, gates: list[dict[str, Any]]) -> str:
    lines = [
        f"# {FULL_ACRONYM} Ultimate Remix All-Star Booty of Fire Edition project configuration.",
        "# Generated deterministically. Edit product policy only; agents must not edit this file.",
        "",
        "[project]",
        "apply_on_success = true",
        "max_repair_cycles = 2",
        "max_plan_review_cycles = 2",
        "require_demonstration = true",
        "",
        _agent_block(agent),
        "",
        "[context]",
        "max_input_tokens = 60000",
        "reserve_output_tokens = 12000",
        "chars_per_token = 3.5",
        "max_single_file_tokens = 18000",
        "map_chunk_tokens = 32000",
        "",
        "[orchestration]",
        "max_parallel_agent_calls = 4",
        "parallel_mapping = true",
        "parallel_review = true",
        "",
        "[safety]",
        'allowed_programs = ["python", "python3", "node", "npm", "pnpm", "yarn", "bun", "cargo", "go", "dotnet", "mvn", "gradle", "gradlew", "make"]',
        "block_agent_commits = true",
        "require_source_unchanged_before_apply = true",
        "",
        "[integrations]",
        'obsidian_vault = ""',
        f'obsidian_export_folder = "{FULL_ACRONYM}"',
        "gbrain_search_command = []",
        "gbrain_capture_command = []",
        "gitnexus_analyze_command = []",
        "gitnexus_query_command = []",
        "document_analysis_command = []",
        "autoreview_command = []",
        "clawpatch_command = []",
        "",
    ]
    for gate in gates:
        lines.extend(
            [
                "[[verification.gates]]",
                f'id = "{gate["id"]}"',
                f'kind = "{gate["kind"]}"',
                "required = true" if gate.get("required", True) else "required = false",
                f"timeout_seconds = {int(gate.get('timeout_seconds', 1800))}",
                "argv = [" + ", ".join(json.dumps(item) for item in gate["argv"]) + "]",
                "",
            ]
        )
    return "\n".join(lines)


def write_config(repo: Path, agent: str, gates: list[dict[str, Any]]) -> Path:
    path = repo / PROJECT_DIR / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_text(path, config_template(agent, gates))
    return path


def apply_agent_preset(repo: Path, preset_name: str) -> dict[str, Any]:
    path = repo / PROJECT_DIR / "config.toml"
    if not path.exists():
        raise ConfigurationError(f"Missing {path}. Run `{PUBLIC_COMMAND} init` first.")
    updated = replace_agent_block(path.read_text(encoding="utf-8", errors="replace"), preset_name)
    atomic_write_text(path, updated)
    return {
        "repo": str(repo),
        "config": str(path),
        "preset": preset_name,
        "agent": agent_preset(preset_name),
    }


def executable_exists(config: dict[str, Any]) -> bool:
    adapter = config["agent"]["adapter"]
    if adapter == "mock":
        return True
    return shutil.which(config["agent"]["executable"]) is not None
