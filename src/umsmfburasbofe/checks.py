from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .errors import ConfigurationError
from .gates import gates_from_config
from .policy import CommandPolicy
from .util import atomic_write_text


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(str(value))


def add_check_gate(
    repo: Path,
    *,
    gate_id: str,
    argv: list[str],
    kind: str = "check",
    timeout_seconds: int = 1800,
    required: bool = True,
) -> dict[str, Any]:
    gate_id = gate_id.strip()
    if not gate_id:
        raise ValueError("Check id is required, for example: smoke")
    if not argv:
        raise ValueError(f"Command is required, for example: `{PUBLIC_COMMAND} checks add smoke -- npm test`")
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ValueError(f"Command is required, for example: `{PUBLIC_COMMAND} checks add smoke -- npm test`")

    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.exists():
        raise ConfigurationError(f"Missing {config_path}. Run `{PUBLIC_COMMAND} init` first.")
    config = load_config(repo)
    existing = {gate.id for gate in gates_from_config(config)}
    if gate_id in existing:
        raise ValueError(f"Check id already exists: {gate_id}")

    CommandPolicy(tuple(config["safety"]["allowed_programs"])).validate(argv)

    block = [
        "",
        "[[verification.gates]]",
        f"id = {_toml_value(gate_id)}",
        f"kind = {_toml_value(kind)}",
        f"required = {_toml_value(required)}",
        f"timeout_seconds = {int(timeout_seconds)}",
        f"argv = {_toml_value(argv)}",
        "",
    ]
    text = config_path.read_text(encoding="utf-8", errors="replace")
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write_text(config_path, text + "\n".join(block).lstrip("\n"))
    return {
        "ok": True,
        "id": gate_id,
        "kind": kind,
        "argv": argv,
        "required": required,
        "timeout_seconds": int(timeout_seconds),
        "config": str(config_path),
        "next_command": f"{PUBLIC_COMMAND} ready",
    }


def list_check_gates(repo: Path) -> dict[str, Any]:
    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.exists():
        raise ConfigurationError(f"Missing {config_path}. Run `{PUBLIC_COMMAND} init` first.")
    gates = [gate.__dict__ for gate in gates_from_config(load_config(repo))]
    return {"ok": True, "config": str(config_path), "gates": gates}


def format_add_check_gate(report: dict[str, Any]) -> str:
    command = " ".join(report["argv"])
    return (
        "CHECK ADDED\n"
        f"ID: {report['id']}\n"
        f"Command: {command}\n"
        f"Config: {report['config']}\n"
        f"Next: {report['next_command']}\n"
    )


def format_check_gate_list(report: dict[str, Any]) -> str:
    lines = ["CHECKS"]
    gates = report.get("gates", [])
    if not gates:
        lines.append("ACTION none configured")
    for gate in gates:
        lines.append(f"OK {gate['id']}: {' '.join(gate['argv'])}")
    return "\n".join(lines) + "\n"
