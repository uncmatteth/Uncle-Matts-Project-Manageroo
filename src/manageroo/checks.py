from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .detector import detect_gates
from .errors import ConfigurationError
from .gates import gates_from_config
from .policy import CommandPolicy
from .util import atomic_write_text

_GATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


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
    if not _GATE_ID_RE.fullmatch(gate_id):
        raise ValueError("Check id may contain only letters, digits, dots, underscores, and hyphens.")
    kind = str(kind).strip()
    if not _GATE_ID_RE.fullmatch(kind):
        raise ValueError("Check kind may contain only letters, digits, dots, underscores, and hyphens.")
    if not argv:
        raise ValueError(f"Command is required. Run `{PUBLIC_COMMAND} checks suggest` for repo-aware options.")
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ValueError(f"Command is required. Run `{PUBLIC_COMMAND} checks suggest` for repo-aware options.")

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
    text = config_path.read_text(encoding="utf-8")
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
        "next_command": shlex.join([PUBLIC_COMMAND, "ready"]),
    }


def list_check_gates(repo: Path) -> dict[str, Any]:
    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.exists():
        raise ConfigurationError(f"Missing {config_path}. Run `{PUBLIC_COMMAND} init` first.")
    gates = [gate.__dict__ for gate in gates_from_config(load_config(repo))]
    return {"ok": True, "config": str(config_path), "gates": gates}


def _command_text(argv: list[str]) -> str:
    return shlex.join([str(item) for item in argv])


def _suggestion(repo: Path, gate: dict[str, Any], reason: str) -> dict[str, Any]:
    argv = list(gate["argv"])
    return {
        "id": gate["id"],
        "kind": gate.get("kind", "check"),
        "argv": argv,
        "reason": reason,
        "add_command": shlex.join([PUBLIC_COMMAND, "checks", "add", str(gate["id"]), "--", *[str(item) for item in argv]]),
        "repo": str(repo),
    }


def _python_compile_fallback(repo: Path) -> dict[str, Any] | None:
    has_python = any(
        path.suffix == ".py"
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        for path in repo.rglob("*.py")
    )
    if not has_python:
        return None
    return _suggestion(
        repo,
        {"id": "python-compile", "kind": "check", "argv": ["python3", "-m", "compileall", "."]},
        "Safe starter check: catches Python syntax errors when no test command was found.",
    )


def suggest_check_gates(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    detected = detect_gates(repo)
    suggestions = [_suggestion(repo, gate, "Detected from repository files and package scripts.") for gate in detected]
    if not suggestions:
        fallback = _python_compile_fallback(repo)
        if fallback:
            suggestions.append(fallback)
    return {
        "ok": True,
        "repo": str(repo),
        "suggestions": suggestions,
        "next_command": suggestions[0]["add_command"] if suggestions else shlex.join([
            PUBLIC_COMMAND, "checks", "add", "smoke", "--", "COMMAND_THAT_PROVES_THE_PROJECT_WORKS"
        ]),
        "note": f"Pick one command the repo can really run. Add it, then run `{PUBLIC_COMMAND} ready` again.",
    }


def add_first_suggested_check_gate(repo: Path) -> dict[str, Any]:
    report = suggest_check_gates(repo)
    suggestions = report.get("suggestions", [])
    if not suggestions:
        return {"ok": False, "repo": report["repo"], "reason": "No automatic check suggestion was found.", "next_command": report["next_command"]}
    skipped: list[dict[str, str]] = []
    for suggestion in suggestions:
        try:
            added = add_check_gate(repo, gate_id=suggestion["id"], argv=list(suggestion["argv"]), kind=suggestion.get("kind", "check"))
        except ValueError as exc:
            if "already exists" not in str(exc):
                raise
            skipped.append({"id": suggestion["id"], "reason": str(exc)})
            continue
        return {"ok": True, "repo": report["repo"], "selected": suggestion, "added": added, "skipped": skipped, "next_command": added["next_command"]}
    return {"ok": False, "repo": report["repo"], "reason": "All automatic check suggestions are already configured.", "skipped": skipped, "next_command": shlex.join([PUBLIC_COMMAND, "checks", "list"])}


def format_add_check_gate(report: dict[str, Any]) -> str:
    command = _command_text(report["argv"])
    return f"CHECK ADDED\nID: {report['id']}\nCommand: {command}\nConfig: {report['config']}\nNext: {report['next_command']}\n"


def format_check_gate_list(report: dict[str, Any]) -> str:
    lines = ["CHECKS"]
    gates = report.get("gates", [])
    if not gates:
        lines.append("ACTION none configured")
    for gate in gates:
        lines.append(f"OK {gate['id']}: {_command_text(gate['argv'])}")
    return "\n".join(lines) + "\n"


def format_check_gate_suggestions(report: dict[str, Any]) -> str:
    lines = ["CHECK SUGGESTIONS", f"Repo: {report['repo']}"]
    suggestions = report.get("suggestions", [])
    if not suggestions:
        lines.append("ACTION no automatic suggestion found")
        lines.append("Add a command your repo can really run, for example a test, build, or lint command.")
    for item in suggestions:
        lines.append(f"OK {item['id']}: {_command_text(item['argv'])}")
        lines.append(f"  why: {item['reason']}")
        lines.append(f"  add: {item['add_command']}")
    if report.get("next_command"):
        lines.append(f"Next: {report['next_command']}")
    return "\n".join(lines) + "\n"


def format_applied_check_suggestion(report: dict[str, Any]) -> str:
    if not report.get("ok"):
        return f"CHECK SUGGESTION NOT APPLIED\nReason: {report['reason']}\nNext: {report['next_command']}\n"
    added = report["added"]
    command = _command_text(added["argv"])
    return f"CHECK SUGGESTION APPLIED\nID: {added['id']}\nCommand: {command}\nConfig: {added['config']}\nNext: {report['next_command']}\n"
