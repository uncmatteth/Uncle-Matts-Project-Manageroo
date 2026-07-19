from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .gbrain_setup import summarize_gbrain_config, summarize_sync_status
from .util import redact_text

WhichFn = Callable[[str], str | None]
RunnerFn = Callable[[list[str], int], dict]


def run_probe(argv: list[str], timeout_seconds: int = 30) -> dict:
    try:
        completed = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout_seconds,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "argv": argv,
            "output": completed.stdout,
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {"ok": False, "exit_code": 124, "argv": argv, "output": output + "\nTIMEOUT"}
    except OSError as exc:
        return {"ok": False, "exit_code": 127, "argv": argv, "output": str(exc)}


def _safe_probe_record(probe: dict | None) -> dict | None:
    if probe is None:
        return None
    record = {
        "ok": bool(probe.get("ok")),
        "exit_code": probe.get("exit_code"),
        "argv": [redact_text(str(item)) for item in probe.get("argv", [])],
    }
    if not probe.get("ok"):
        record["output"] = redact_text(str(probe.get("output", "")))[:2000]
    return record


def _missing(name: str, detail: str, next_commands: list[str], *, reference: str = "") -> dict:
    return {
        "name": name,
        "status": "missing",
        "installed": False,
        "configured": False,
        "detail": detail,
        "next_commands": next_commands,
        "reference": reference,
    }


def _gbrain(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("gbrain")
    if not path:
        return _missing(
            "gbrain",
            "GBrain command not found.",
            [
                "Install Bun from https://bun.sh/",
                "bun install -g github:garrytan/gbrain",
                "gbrain init --pglite",
                "gbrain doctor --json",
            ],
            reference="https://github.com/garrytan/gbrain",
        )

    config_probe = runner([path, "config", "show"], 30)
    sync_probe = runner([path, "status", "--json", "--section", "sync"], 60)
    doctor_probe = runner([path, "doctor", "--json"], 60)
    config = summarize_gbrain_config(config_probe.get("output", "")) if config_probe.get("ok") else {}
    sync = (
        summarize_sync_status(sync_probe.get("output", ""))
        if sync_probe.get("ok")
        else {"ok": False, "error": redact_text(str(sync_probe.get("output") or "gbrain status failed"))}
    )
    next_commands: list[str] = []
    if not config:
        next_commands.append("gbrain config show")
    if not doctor_probe.get("ok"):
        next_commands.append("gbrain doctor --json")
    if not sync.get("ok"):
        next_commands.append("gbrain status --json --section sync")
    if sync.get("ok") and sync.get("source_count", 0) == 0:
        next_commands.extend([
            "gbrain sources list",
            "gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder",
            "gbrain sync --source YOUR_SOURCE_ID --json --yes",
        ])
    configured = bool(config and doctor_probe.get("ok") and sync.get("ok") and sync.get("source_count", 0) > 0)
    detail_bits = []
    if config.get("engine"):
        detail_bits.append(f"engine={config['engine']}")
    if config.get("embedding_model"):
        detail_bits.append(f"embedding={config['embedding_model']}")
    if sync.get("ok"):
        detail_bits.append(f"sources={sync.get('source_count', 0)}")
    if not detail_bits:
        detail_bits.append("installed; setup probes need attention")
    return {
        "name": "gbrain",
        "status": "ok" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "path": path,
        "detail": "; ".join(detail_bits),
        "next_commands": next_commands,
        "config_summary": config,
        "sync_summary": sync,
        "probes": {
            "config": _safe_probe_record(config_probe),
            "sync": _safe_probe_record(sync_probe),
            "doctor": _safe_probe_record(doctor_probe),
        },
        "reference": "https://github.com/garrytan/gbrain",
    }


def _gitnexus(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("gitnexus")
    if not path:
        return _missing(
            "gitnexus",
            "GitNexus command not found.",
            ["Install Node.js 18+", "npm install -g gitnexus", "gitnexus setup"],
            reference="https://github.com/nxpatterns/gitnexus",
        )
    version_probe = runner([path, "--version"], 30)
    configured = bool(version_probe.get("ok"))
    return {
        "name": "gitnexus",
        "status": "warning" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "path": path,
        "detail": (
            "installed; setup probe is not authoritative, run `gitnexus setup` if your agent cannot see it"
            if configured
            else "installed; version probe failed, run `gitnexus setup`"
        ),
        "next_commands": ["gitnexus setup"] if not configured else [],
        "probes": {"version": _safe_probe_record(version_probe)},
        "reference": "https://github.com/nxpatterns/gitnexus",
    }


def _autoreview(home: Path) -> dict:
    candidates = [
        home / ".agents" / "skills" / "autoreview" / "scripts" / "autoreview",
        home / ".codex" / "skills" / "autoreview" / "scripts" / "autoreview",
    ]
    existing = next((path for path in candidates if path.exists()), None)
    if not existing:
        return _missing(
            "autoreview",
            "AUTOREVIEW skill script not found in ~/.agents or ~/.codex.",
            [
                "git clone https://github.com/openclaw/agent-skills.git",
                "mkdir -p ~/.agents/skills",
                "cp -R agent-skills/skills/autoreview ~/.agents/skills/autoreview",
            ],
            reference="https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
        )
    return {
        "name": "autoreview",
        "status": "ok",
        "installed": True,
        "configured": True,
        "path": str(existing),
        "detail": f"found at {existing}",
        "next_commands": [],
        "detected_locations": [str(path) for path in candidates if path.exists()],
        "reference": "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
    }


def _codex(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("codex")
    if not path:
        return _missing(
            "codex",
            "Codex CLI not found. This is optional unless the selected agent or Clawpatch provider needs it.",
            ["Install Codex only if this machine should use Codex.", "codex login"],
            reference="https://chatgpt.com/codex",
        ) | {"optional": True}
    status_probe = runner([path, "login", "status"], 30)
    configured = bool(status_probe.get("ok"))
    return {
        "name": "codex",
        "status": "ok" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "optional": True,
        "path": path,
        "detail": "login ready" if configured else "installed; login not ready",
        "next_commands": [] if configured else ["codex login"],
        "probes": {"login": _safe_probe_record(status_probe)},
        "reference": "https://chatgpt.com/codex",
    }


def _clawpatch(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("clawpatch")
    codex = _codex(which, runner)
    if not path:
        return _missing(
            "clawpatch",
            "Clawpatch command not found.",
            ["npm install -g pnpm", "pnpm add -g clawpatch", "clawpatch doctor"],
            reference="https://github.com/openclaw/clawpatch",
        )
    doctor_probe = runner([path, "doctor"], 60)
    next_commands: list[str] = []
    if not doctor_probe.get("ok"):
        next_commands.append("clawpatch doctor")
    if codex.get("status") == "needs_action":
        next_commands.extend(codex.get("next_commands", []))
    configured = bool(doctor_probe.get("ok") and codex.get("configured"))
    return {
        "name": "clawpatch",
        "status": "ok" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "path": path,
        "detail": "doctor and codex provider ready" if configured else "installed; doctor or codex provider needs attention",
        "next_commands": next_commands,
        "probes": {"doctor": _safe_probe_record(doctor_probe), "codex_provider": codex},
        "project_commands": ["clawpatch init", "clawpatch map", "clawpatch review --limit 3 --jobs 3"],
        "reference": "https://github.com/openclaw/clawpatch",
    }


def _obsidian(which: WhichFn) -> dict:
    path = which("obsidian")
    if not path:
        return _missing(
            "obsidian",
            "Obsidian command not found.",
            ["Install Obsidian from https://obsidian.md/download"],
            reference="https://obsidian.md/download",
        )
    return {
        "name": "obsidian",
        "status": "ok",
        "installed": True,
        "configured": True,
        "path": path,
        "detail": "command available",
        "next_commands": [],
        "reference": "https://obsidian.md/download",
    }


def stack_doctor(
    *,
    which: WhichFn = shutil.which,
    runner: RunnerFn = run_probe,
    home: Path | None = None,
) -> dict:
    home = (home or Path.home()).expanduser()
    items = [
        _gbrain(which, runner),
        _gitnexus(which, runner),
        _autoreview(home),
        _clawpatch(which, runner),
        _obsidian(which),
        _codex(which, runner),
    ]
    needs_action = [
        item
        for item in items
        if item.get("status") in {"missing", "needs_action"} and not item.get("optional")
    ]
    return {
        "ok": True,
        "ready": not needs_action,
        "executes_changes": False,
        "counts": {
            "items": len(items),
            "configured": sum(1 for item in items if item.get("configured")),
            "needs_action": len(needs_action),
            "missing": sum(1 for item in items if item.get("status") == "missing"),
        },
        "items": items,
    }


def format_stack_doctor(report: dict) -> str:
    lines = [
        "SMART STACK DOCTOR",
        "",
        "This is read-only. It did not install, rewrite, log in, map folders, or remove anything.",
        f"Ready: {'yes' if report.get('ready') else 'no'}",
        "",
        "Stack tools:",
    ]
    for item in report.get("items", []):
        label = "OK" if item.get("status") == "ok" else "WARN" if item.get("status") == "warning" else "ACTION"
        optional = " optional" if item.get("optional") else ""
        lines.append(f"- {label} {item['name']}{optional}: {item.get('detail', '')}")
        for command in item.get("next_commands", []):
            lines.append(f"  next: {command}")
    lines.extend(["", "To let the installer guide missing pieces later:", "  ./install.sh --install-stack"])
    return "\n".join(lines) + "\n"
