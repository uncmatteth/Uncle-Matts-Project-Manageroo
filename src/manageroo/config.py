from __future__ import annotations

import copy
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

from .branding import FULL_ACRONYM, PROJECT_DIR, PUBLIC_COMMAND
from .config_lock import config_mutation_lock
from .errors import ConfigurationError
from .util import atomic_write_text


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "apply_on_success": True,
        "max_repair_cycles": 0,
        "max_plan_review_cycles": 0,
        "require_demonstration": True,
        "require_clawpatch_release_sweep": False,
    },
    "agent": {
        "adapter": "auto",
        "candidates": ["codex", "claude-code", "gemini"],
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
        "max_worker_attempts": 0,
        "parallel_mapping": True,
        "parallel_review": True,
    },
    "capabilities": {
        "enabled": True,
        "max_selected": 4,
        "max_prompt_chars": 24000,
    },
    "budget": {"max_total_worker_calls": 80, "max_runtime_minutes": 240},
    "safety": {
        "allowed_programs": [
            "python", "python3", "node", "npm", "npm.cmd", "pnpm", "yarn", "bun",
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
    "auto": {"adapter": "auto", "candidates": ["codex", "claude-code", "gemini"], "timeout_seconds": 3600},
    "codex": {"adapter": "codex", "executable": "codex", "model": "", "timeout_seconds": 3600},
    "mock": {"adapter": "mock", "executable": "python", "model": "", "timeout_seconds": 3600},
    "generic": {
        "adapter": "generic",
        "executable": "YOUR_AGENT",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "file_path",
        "argv_template": ["YOUR_AGENT", "--prompt-file", "{prompt}", "--schema", "{schema}", "--output", "{output}"],
    },
    "claude-code": {
        "adapter": "generic",
        "executable": "claude",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "stdin",
        "argv_template": ["claude", "-p", "Follow the complete Manageroo assignment provided on stdin. Return only the requested JSON object."],
        "sandbox_read_only_argv": ["--permission-mode", "plan"],
        "sandbox_workspace_write_argv": ["--permission-mode", "acceptEdits"],
        "doctor_argv": ["claude", "--help"],
        "required_help_flags": ["--permission-mode"],
    },
    "gemini": {
        "adapter": "generic",
        "executable": "gemini",
        "model": "",
        "timeout_seconds": 3600,
        "prompt_transport": "stdin",
        "argv_template": ["gemini", "-p", "Follow the complete Manageroo assignment provided on stdin. Return only the requested JSON object."],
        "sandbox_read_only_argv": ["--approval-mode=plan"],
        "sandbox_workspace_write_argv": ["--approval-mode=auto_edit"],
        "doctor_argv": ["gemini", "--help"],
        "required_help_flags": ["--approval-mode", "--prompt"],
    },
}

_AGENT_KEYS = [
    "adapter", "executable", "model", "timeout_seconds", "candidates", "prompt_transport",
    "argv_template", "sandbox_read_only_argv", "sandbox_workspace_write_argv", "doctor_argv", "required_help_flags",
]


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
    return json.dumps(str(value), ensure_ascii=False)


def _agent_block(preset_name: str, timeout_seconds: int | None = None) -> str:
    preset = agent_preset(preset_name)
    if timeout_seconds is not None:
        preset["timeout_seconds"] = timeout_seconds
    lines = ["[agent]"]
    for key in _AGENT_KEYS:
        if key in preset:
            lines.append(f"{key} = {_toml_value(preset[key])}")
    return "\n".join(lines)


def replace_agent_block(text: str, preset_name: str) -> str:
    try:
        original = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Cannot replace agent preset in invalid TOML: {exc}") from exc

    lines = text.splitlines()
    replacement = _agent_block(preset_name).splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == "[agent]"]
    if not starts:
        updated = "\n".join([*replacement, "", *lines]).rstrip() + "\n"
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Agent preset would produce invalid TOML: {exc}") from exc
        return updated

    expected_agent = agent_preset(preset_name)
    original_without_agent = {key: value for key, value in original.items() if key != "agent"}
    for start in starts:
        for end in range(start + 1, len(lines) + 1):
            if end < len(lines) and not lines[end].lstrip().startswith("["):
                continue
            updated = "\n".join(
                [*lines[:start], *replacement, "", *lines[end:]]
            ).rstrip() + "\n"
            try:
                parsed = tomllib.loads(updated)
            except tomllib.TOMLDecodeError:
                continue
            if parsed.get("agent") != expected_agent:
                continue
            parsed_without_agent = {
                key: value for key, value in parsed.items() if key != "agent"
            }
            if parsed_without_agent == original_without_agent:
                return updated

    raise ConfigurationError("Could not safely locate the complete [agent] TOML table")


def config_template(agent: str, gates: list[dict[str, Any]]) -> str:
    lines = [
        f"# {FULL_ACRONYM} project configuration.",
        "# Generated deterministically. Edit product policy only; agents must not edit this file.",
        "",
        "[project]",
        "apply_on_success = true",
        "max_repair_cycles = 0",
        "max_plan_review_cycles = 0",
        "require_demonstration = true",
        "require_clawpatch_release_sweep = false",
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
        "max_worker_attempts = 0",
        "parallel_mapping = true",
        "parallel_review = true",
        "",
        "[capabilities]",
        "enabled = true",
        "max_selected = 4",
        "max_prompt_chars = 24000",
        "",
        "[budget]",
        "max_total_worker_calls = 80",
        "max_runtime_minutes = 240",
        "",
        "[safety]",
        'allowed_programs = ["python", "python3", "node", "npm", "npm.cmd", "pnpm", "yarn", "bun", "cargo", "go", "dotnet", "mvn", "gradle", "gradlew", "make"]',
        "block_agent_commits = true",
        "require_source_unchanged_before_apply = true",
        "",
        "[integrations]",
        'obsidian_vault = ""',
        f"obsidian_export_folder = {_toml_value(FULL_ACRONYM)}",
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
        lines.extend([
            "[[verification.gates]]",
            f"id = {_toml_value(gate['id'])}",
            f"kind = {_toml_value(gate['kind'])}",
            "required = true" if gate.get("required", True) else "required = false",
            f"timeout_seconds = {int(gate.get('timeout_seconds', 1800))}",
            f"argv = {_toml_value(list(gate['argv']))}",
            "",
        ])
    return "\n".join(lines)


def write_config(repo: Path, agent: str, gates: list[dict[str, Any]]) -> Path:
    path = repo / PROJECT_DIR / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with config_mutation_lock(path):
        if not path.exists():
            atomic_write_text(path, config_template(agent, gates))
    return path


def apply_agent_preset(repo: Path, preset_name: str) -> dict[str, Any]:
    path = repo / PROJECT_DIR / "config.toml"
    with config_mutation_lock(path):
        if not path.exists():
            raise ConfigurationError(f"Missing {path}. Run `{PUBLIC_COMMAND} init` first.")
        updated = replace_agent_block(path.read_text(encoding="utf-8"), preset_name)
        atomic_write_text(path, updated)
    return {"repo": str(repo), "config": str(path), "preset": preset_name, "agent": agent_preset(preset_name)}


def executable_exists(config: dict[str, Any]) -> bool:
    agent = config["agent"]
    adapter = agent["adapter"]
    if adapter == "mock":
        return True
    if adapter == "auto":
        return any(
            shutil.which(str(agent_preset(str(name)).get("executable") or ""))
            for name in agent.get("candidates", [])
        )
    return shutil.which(str(agent.get("executable") or "")) is not None
