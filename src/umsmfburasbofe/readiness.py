from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from .assets import asset_path
from .branding import PROJECT_DIR
from .config import load_config
from .errors import ConfigurationError
from .gates import gates_from_config
from .gbrain_setup import gbrain_setup_status
from .project import git_root
from .token_modes import CORE_HELPER_SKILLS, token_mode_skills_dir


def _item(
    name: str,
    ok: bool,
    detail: str,
    next_command: str = "",
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
        "next": next_command,
        "required": required,
    }


def helper_skill_items() -> list[dict[str, Any]]:
    roots = []
    for root in [
        token_mode_skills_dir(),
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
    ]:
        expanded = root.expanduser()
        if expanded not in roots:
            roots.append(expanded)
    items = []
    for skill in sorted(CORE_HELPER_SKILLS):
        candidates = [root / skill / "SKILL.md" for root in roots]
        existing = [path for path in candidates if path.is_file()]
        items.append(
            _item(
                f"helper:{skill}",
                bool(existing),
                str(existing[0]) if existing else "missing",
                "umsmfburasbofe skills install",
            )
        )
    return items


def brief_is_template(path: Path) -> bool:
    if not path.exists():
        return False
    template = asset_path("templates/PRODUCT-BRIEF.md").read_text(encoding="utf-8").strip()
    current = path.read_text(encoding="utf-8", errors="replace").strip()
    return current == template


def readiness(repo_path: Path, *, require_gbrain: bool = False) -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        _item(
            "python",
            sys.version_info >= (3, 11),
            sys.version.split()[0],
            "Install Python 3.11+",
        ),
        _item(
            "git",
            shutil.which("git") is not None,
            shutil.which("git") or "not found",
            "Install Git",
        ),
        *helper_skill_items(),
    ]
    repo: Path | None = None
    try:
        repo = git_root(repo_path)
        items.append(_item("target repo", True, str(repo)))
    except ConfigurationError as exc:
        items.append(
            _item("target repo", False, str(exc), "Run inside an existing Git repository.")
        )

    config: dict[str, Any] | None = None
    if repo:
        config_path = repo / PROJECT_DIR / "config.toml"
        brief_path = repo / PROJECT_DIR / "PRODUCT-BRIEF.md"
        items.append(
            _item(
                "project config",
                config_path.is_file(),
                str(config_path) if config_path.exists() else "missing",
                f"umsmfburasbofe init --agent codex {repo}",
            )
        )
        if config_path.exists():
            try:
                config = load_config(repo)
            except Exception as exc:
                items.append(
                    _item("config parse", False, str(exc), "Fix .umsmfburasbofe/config.toml")
                )
        items.append(
            _item(
                "product brief",
                brief_path.is_file() and not brief_is_template(brief_path),
                "ready"
                if brief_path.exists() and not brief_is_template(brief_path)
                else "missing or still template",
                "umsmfburasbofe brief --want \"Describe the result\" --force",
            )
        )

    if config:
        adapter = str(config["agent"]["adapter"])
        if adapter == "mock":
            items.append(_item("selected agent", True, "mock adapter"))
        elif adapter == "generic":
            template = config["agent"].get("argv_template", [])
            executable = template[0] if template else ""
            items.append(
                _item(
                    "selected agent",
                    bool(executable and shutil.which(executable)),
                    executable if executable else "generic argv_template missing",
                    "umsmfburasbofe agent preset codex",
                )
            )
        else:
            executable = str(config["agent"]["executable"])
            items.append(
                _item(
                    "selected agent",
                    shutil.which(executable) is not None,
                    executable,
                    (
                        f"Install or authenticate {executable}, or run "
                        "`umsmfburasbofe agent preset generic`."
                    ),
                )
            )
        gates = gates_from_config(config)
        items.append(
            _item(
                "checks",
                bool(gates),
                (
                    ", ".join(gate.id for gate in gates)
                    if gates
                    else "no verification gates configured"
                ),
                "Add a real check command, for example: "
                "`umsmfburasbofe checks add smoke -- npm test`",
            )
        )

    gbrain = gbrain_setup_status()
    gbrain_ok = bool(gbrain.get("ok") and gbrain.get("status", {}).get("source_count", 0) > 0)
    gbrain_next = (
        "umsmfburasbofe gbrain-setup --source-id my-project "
        "--path /absolute/path/to/repo --apply --sync"
        if not gbrain_ok
        else "Connect `gbrain serve` to the selected agent if not already wired."
    )
    items.append(
        _item(
            "gbrain",
            gbrain_ok,
            "sources mapped" if gbrain_ok else "not installed, unhealthy, or no mapped sources",
            gbrain_next,
            required=require_gbrain,
        )
    )

    required_items = [item for item in items if item.get("required", True)]
    ok = all(item["ok"] for item in required_items)
    next_commands = [item["next"] for item in items if not item["ok"] and item.get("next")]
    return {
        "ok": ok,
        "status": "READY TO RUN" if ok else "NOT READY",
        "repo": str(repo) if repo else None,
        "items": items,
        "next_commands": next_commands,
    }


def format_readiness(report: dict[str, Any], *, include_next: bool = True) -> str:
    lines = [report["status"], ""]
    for item in report["items"]:
        label = "OK" if item["ok"] else "ACTION"
        if not item.get("required", True) and not item["ok"]:
            label = "OPTIONAL"
        lines.append(f"{label} {item['name']}: {item['detail']}")
    if include_next and report.get("next_commands"):
        lines.extend(["", "Next:"])
        lines.append(report["next_commands"][0])
    return "\n".join(lines) + "\n"
