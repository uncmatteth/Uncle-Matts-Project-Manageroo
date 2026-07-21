from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .adapters.factory import build_adapter
from .branding import PROJECT_DIR
from .config import load_config
from .gates import gates_from_config
from .policy import CommandPolicy
from .runner import CommandRunner


def _resolve_gate_executable(repo: Path, value: str) -> str | None:
    candidate = str(value)
    if os.sep in candidate or (os.altsep and os.altsep in candidate):
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = repo / path
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None
    return shutil.which(candidate)


def doctor(repo: Path) -> dict:
    repo = repo.expanduser().resolve()
    config = load_config(repo)
    runner = CommandRunner(repo / PROJECT_DIR / "doctor-logs")
    adapter = build_adapter(config, runner)
    checks: list[dict] = []

    checks.append({"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version})
    git = shutil.which("git")
    checks.append({"name": "git", "ok": bool(git), "detail": git or "not found"})

    adapter_check = adapter.doctor(repo)
    checks.append({"name": "agent-adapter", "ok": bool(adapter_check.get("ok")), "detail": adapter_check})

    gates = gates_from_config(config)
    checks.append({
        "name": "verification-gates",
        "ok": bool(gates),
        "detail": [gate.id for gate in gates] if gates else "none configured",
    })

    command_policy = CommandPolicy(tuple(config["safety"]["allowed_programs"]))
    for gate in gates:
        try:
            command_policy.validate(gate.argv)
            executable = _resolve_gate_executable(repo, gate.argv[0])
            checks.append({
                "name": f"gate:{gate.id}",
                "ok": executable is not None,
                "detail": {"argv": gate.argv, "executable": executable},
            })
        except Exception as exc:
            checks.append({"name": f"gate:{gate.id}", "ok": False, "detail": str(exc)})

    context = config["context"]
    usable = int(context["max_input_tokens"]) - int(context["reserve_output_tokens"])
    checks.append({
        "name": "context-budget",
        "ok": usable > 0 and int(context["map_chunk_tokens"]) <= usable,
        "detail": {
            "max_input_tokens": context["max_input_tokens"],
            "reserve_output_tokens": context["reserve_output_tokens"],
            "usable_tokens": usable,
            "map_chunk_tokens": context["map_chunk_tokens"],
        },
    })

    obsidian = config["integrations"].get("obsidian_vault")
    checks.append({
        "name": "obsidian-optional",
        "ok": True,
        "detail": "disabled" if not obsidian else (
            "available" if Path(obsidian).expanduser().is_dir() else "configured path missing"
        ),
        "required": False,
    })

    return {
        "ok": all(item["ok"] for item in checks if item.get("required", True)),
        "repo": str(repo),
        "checks": checks,
    }
