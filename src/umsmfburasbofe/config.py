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
        "autoreview_command": [],
        "clawpatch_command": [],
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
        "[agent]",
        f'adapter = "{agent}"',
        f'executable = "{agent if agent != "mock" else "python"}"',
        'model = ""',
        "timeout_seconds = 3600",
        "",
        "[context]",
        "max_input_tokens = 60000",
        "reserve_output_tokens = 12000",
        "chars_per_token = 3.5",
        "max_single_file_tokens = 18000",
        "map_chunk_tokens = 32000",
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


def executable_exists(config: dict[str, Any]) -> bool:
    adapter = config["agent"]["adapter"]
    if adapter == "mock":
        return True
    return shutil.which(config["agent"]["executable"]) is not None
