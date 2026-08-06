from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .gbrain_setup import summarize_gbrain_config, summarize_sync_status
from .stack_update import (
    AUTOREVIEW_COMMIT,
    AUTOREVIEW_REFERENCE,
    CLAWPATCH_PACKAGE,
    CLAWPATCH_REFERENCE,
    GBRAIN_COMMIT,
    GBRAIN_REFERENCE,
    GITNEXUS_PACKAGE,
    GITNEXUS_REFERENCE,
    MANAGEROO_SKILLS_REFERENCE,
)
from .assets import asset_path
from .token_modes import CORE_HELPER_SKILLS, _skill_tree_sha256
from .util import redact_text
from .trufflehog import TRUFFLEHOG_REFERENCE, TRUFFLEHOG_VERSION

WhichFn = Callable[[str], str | None]
RunnerFn = Callable[[list[str], int], dict]
GBRAIN_PINNED_SOURCE = f"github:garrytan/gbrain#{GBRAIN_COMMIT}"


def run_probe(argv: list[str], timeout_seconds: int = 30) -> dict:
    try:
        completed = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "argv": argv,
            "output": stdout,
            "stdout": stdout,
            "stderr": completed.stderr or "",
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "ok": False,
            "exit_code": 124,
            "argv": argv,
            "output": stdout,
            "stdout": stdout,
            "stderr": stderr + "\nTIMEOUT",
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "argv": argv,
            "output": "",
            "stdout": "",
            "stderr": str(exc),
        }


def _safe_probe_record(probe: dict | None) -> dict | None:
    if probe is None:
        return None
    record = {
        "ok": bool(probe.get("ok")),
        "exit_code": probe.get("exit_code"),
        "argv": [redact_text(str(item)) for item in probe.get("argv", [])],
    }
    if not probe.get("ok"):
        record["output"] = redact_text(
            str(probe.get("stdout", probe.get("output", "")))
        )[:2000]
    if probe.get("stderr"):
        record["stderr"] = redact_text(str(probe.get("stderr")))[:2000]
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
                f"bun install -g {GBRAIN_PINNED_SOURCE}",
                "gbrain init --pglite",
                "gbrain doctor --json",
            ],
            reference=GBRAIN_REFERENCE,
        )

    config_probe = runner([path, "config", "show"], 30)
    sync_probe = runner([path, "status", "--json", "--section", "sync"], 60)
    doctor_probe = runner([path, "doctor", "--json"], 60)
    config = (
        summarize_gbrain_config(config_probe.get("stdout", config_probe.get("output", "")))
        if config_probe.get("ok")
        else {}
    )
    sync = (
        summarize_sync_status(sync_probe.get("stdout", sync_probe.get("output", "")))
        if sync_probe.get("ok")
        else {
            "ok": False,
            "parsed": False,
            "healthy": False,
            "error": redact_text(
                str(
                    sync_probe.get("stderr")
                    or sync_probe.get("stdout", sync_probe.get("output"))
                    or "gbrain status failed"
                )
            ),
        }
    )
    next_commands: list[str] = []
    if not config:
        next_commands.append("gbrain config show")
    if not doctor_probe.get("ok"):
        next_commands.append("gbrain doctor --json")
    if not sync.get("healthy"):
        next_commands.append("gbrain status --json --section sync")
    if sync.get("parsed") and sync.get("source_count", 0) == 0:
        next_commands.extend([
            "gbrain sources list",
            "gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder",
            "gbrain sync --source YOUR_SOURCE_ID --json --yes",
        ])
    configured = bool(config and doctor_probe.get("ok") and sync.get("healthy") and sync.get("source_count", 0) > 0)
    detail_bits = []
    if config.get("engine"):
        detail_bits.append(f"engine={config['engine']}")
    if config.get("embedding_model"):
        detail_bits.append(f"embedding={config['embedding_model']}")
    if sync.get("parsed"):
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
        "reference": GBRAIN_REFERENCE,
        "pinned_commit": GBRAIN_COMMIT,
    }


def _gitnexus(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("gitnexus")
    if not path:
        return _missing(
            "gitnexus",
            "GitNexus command not found.",
            ["Install Node.js 22.18+", f"npm install -g {GITNEXUS_PACKAGE}", "gitnexus setup"],
            reference=GITNEXUS_REFERENCE,
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
        "reference": GITNEXUS_REFERENCE,
        "pinned_package": GITNEXUS_PACKAGE,
    }


def _trufflehog(which: WhichFn, runner: RunnerFn) -> dict:
    path = which("trufflehog")
    if not path:
        return _missing(
            "trufflehog",
            "TruffleHog command not found. AUTOREVIEW requires it for the pre-review secret scan.",
            ["Rerun the Manageroo installer with the recommended stack enabled."],
            reference=TRUFFLEHOG_REFERENCE,
        )
    version_probe = runner([path, "--version"], 30)
    configured = bool(version_probe.get("ok"))
    return {
        "name": "trufflehog",
        "status": "ok" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "path": path,
        "detail": f"version probe passed; Manageroo release pin is {TRUFFLEHOG_VERSION}" if configured else "installed; version probe failed",
        "next_commands": [] if configured else ["trufflehog --version"],
        "probes": {"version": _safe_probe_record(version_probe)},
        "reference": TRUFFLEHOG_REFERENCE,
        "pinned_version": TRUFFLEHOG_VERSION,
    }


def _autoreview(home: Path, trufflehog: dict) -> dict:
    candidates = [
        home / ".agents" / "skills" / "autoreview" / "scripts" / "autoreview",
        home / ".codex" / "skills" / "autoreview" / "scripts" / "autoreview",
    ]
    valid = [path for path in candidates if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK))]
    existing = valid[0] if valid else None
    malformed = [path for path in candidates if path.exists() and path not in valid]
    if not existing:
        detail = "AUTOREVIEW skill script not found in ~/.agents or ~/.codex."
        if malformed:
            detail = "AUTOREVIEW path exists but is not a runnable regular executable file: " + ", ".join(str(path) for path in malformed)
        return _missing(
            "autoreview",
            detail,
            [
                f"Reinstall or repair AUTOREVIEW from the pinned OpenClaw agent-skills commit {AUTOREVIEW_COMMIT}.",
                "manageroo stack-update autoreview --apply",
            ],
            reference=AUTOREVIEW_REFERENCE,
        )
    configured = bool(trufflehog.get("configured"))
    return {
        "name": "autoreview",
        "status": "ok" if configured else "needs_action",
        "installed": True,
        "configured": configured,
        "path": str(existing),
        "detail": (
            f"runnable script and TruffleHog dependency found at {existing}"
            if configured
            else f"runnable script found at {existing}, but required TruffleHog is not ready"
        ),
        "next_commands": [] if configured else list(trufflehog.get("next_commands") or []),
        "dependencies": {"trufflehog": trufflehog},
        "detected_locations": [str(path) for path in valid],
        "reference": AUTOREVIEW_REFERENCE,
        "pinned_commit": AUTOREVIEW_COMMIT,
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


def _clawpatch(which: WhichFn, runner: RunnerFn, codex: dict) -> dict:
    path = which("clawpatch")
    if not path:
        return _missing(
            "clawpatch",
            "Clawpatch command not found.",
            ["Install pnpm 11.1.2", f"pnpm add -g {CLAWPATCH_PACKAGE}", "clawpatch doctor"],
            reference=CLAWPATCH_REFERENCE,
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
        "reference": CLAWPATCH_REFERENCE,
        "pinned_package": CLAWPATCH_PACKAGE,
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


def _skills(home: Path) -> dict:
    roots = [home / ".agents" / "skills", home / ".codex" / "skills"]
    found: dict[str, str] = {}
    matching: list[str] = []
    differing: list[str] = []
    for name, asset in CORE_HELPER_SKILLS.items():
        candidate = next(
            (
                root / name
                for root in roots
                if (root / name / "SKILL.md").is_file()
                and not (root / name).is_symlink()
            ),
            None,
        )
        if candidate is None:
            continue
        found[name] = str(candidate)
        try:
            same = _skill_tree_sha256(candidate) == _skill_tree_sha256(
                asset_path(asset).parent
            )
        except (OSError, ValueError):
            same = False
        (matching if same else differing).append(name)

    missing = sorted(set(CORE_HELPER_SKILLS) - set(found))
    configured = not missing
    status = "ok" if configured and not differing else "warning" if configured else "needs_action"
    details = [f"{len(found)}/{len(CORE_HELPER_SKILLS)} core skills detected"]
    if differing:
        details.append(f"{len(differing)} host-owned or version-different")
    if missing:
        details.append(f"{len(missing)} missing")
    return {
        "name": "skills",
        "status": status,
        "installed": bool(found),
        "configured": configured,
        "detail": "; ".join(details),
        "next_commands": (
            ["manageroo stack-update skills --apply"] if missing or differing else []
        ),
        "detected": dict(sorted(found.items())),
        "matching_bundled": sorted(matching),
        "preserved_host_or_different": sorted(differing),
        "missing": missing,
        "reference": MANAGEROO_SKILLS_REFERENCE,
    }


def stack_doctor(
    *,
    which: WhichFn = shutil.which,
    runner: RunnerFn = run_probe,
    home: Path | None = None,
) -> dict:
    home = (home or Path.home()).expanduser()
    codex = _codex(which, runner)
    trufflehog = _trufflehog(which, runner)
    items = [
        _gbrain(which, runner),
        _gitnexus(which, runner),
        trufflehog,
        _autoreview(home, trufflehog),
        _clawpatch(which, runner, codex),
        _obsidian(which),
        _skills(home),
        codex,
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
