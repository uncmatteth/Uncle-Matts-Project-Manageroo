from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from .assets import asset_path
from .branding import PROJECT_DIR, PUBLIC_COMMAND
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
    severity: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
        "next": next_command,
        "required": required,
        "severity": severity or ("required" if required else "optional"),
    }


DOCUMENT_REQUEST_TERMS = (
    "pdf",
    "transcript",
    "screenshot",
    "image",
    "picture",
    "photo",
    "audio",
    "video",
    "voice note",
    "manuscript",
    "novel",
    "book",
    "chapter",
    "long prose",
    "long document",
    "exact wording",
    "exact text",
    "exact replacement",
    "byte-for-byte",
    "do not paraphrase",
    "don't paraphrase",
    "preserve exact",
)
MEMORY_REQUEST_TERMS = (
    "gbrain",
    "brain page",
    "project memory",
    "use memory",
    "from memory",
    "existing memory",
    "past context",
    "prior decision",
    "prior decisions",
    "previous decision",
    "previous decisions",
    "obsidian",
    "knowledge base",
)
DOCUMENT_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".heic",
    ".mp3",
    ".wav",
    ".m4a",
    ".mp4",
    ".mov",
    ".avi",
}
PROSE_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}
SCAN_SKIP_PARTS = {
    ".git",
    ".manageroo",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


def _read_text_if_present(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _mentions(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _repo_document_examples(repo: Path, *, limit: int = 5, scan_limit: int = 2000) -> list[str]:
    examples: list[str] = []
    scanned = 0
    for path in repo.rglob("*"):
        if scanned >= scan_limit or len(examples) >= limit:
            break
        try:
            relative = path.relative_to(repo)
        except ValueError:
            continue
        if any(part in SCAN_SKIP_PARTS for part in relative.parts):
            continue
        if not path.is_file():
            continue
        scanned += 1
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_SUFFIXES:
            examples.append(relative.as_posix())
            continue
        if suffix in PROSE_SUFFIXES:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size >= 100_000:
                examples.append(relative.as_posix())
    return examples


def _document_lane_items(repo: Path, config: dict[str, Any], brief_text: str) -> list[dict[str, Any]]:
    requested_terms = _mentions(brief_text, DOCUMENT_REQUEST_TERMS)
    repo_examples = _repo_document_examples(repo)
    command = config.get("integrations", {}).get("document_analysis_command", [])
    configured = bool(command)
    next_command = (
        "Configure [integrations].document_analysis_command in "
        ".manageroo/config.toml, then rerun `manageroo ready`. "
        "See docs/DOCUMENT_LANE.md."
    )
    if requested_terms:
        if configured:
            return [
                _item(
                    "document/prose lane",
                    True,
                    "brief asks for document/prose/media/exact-text handling and document_analysis_command is configured",
                )
            ]
        return [
            _item(
                "document/prose lane",
                False,
                (
                    "brief asks for document/prose/media/exact-text handling "
                    f"({', '.join(requested_terms[:4])}), but document_analysis_command is empty"
                ),
                next_command,
                required=True,
            )
        ]
    if repo_examples and not configured:
        return [
            _item(
                "document/prose lane",
                False,
                (
                    "repo contains document/media files "
                    f"({', '.join(repo_examples[:3])}); configure document_analysis_command "
                    "if this run needs to understand them"
                ),
                next_command,
                required=False,
                severity="warning",
            )
        ]
    return []


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
                f"skill-pack:{skill}",
                bool(existing),
                str(existing[0]) if existing else "missing",
                "manageroo skills install",
                required=False,
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
            _item(
                "target repo",
                False,
                str(exc),
                "Run inside an existing Git repository, or create a new one with "
                "`manageroo solo /path/to/new-product --create --want \"Describe it\"`.",
            )
        )

    config: dict[str, Any] | None = None
    brief_text = ""
    if repo:
        config_path = repo / PROJECT_DIR / "config.toml"
        brief_path = repo / PROJECT_DIR / "PRODUCT-BRIEF.md"
        memory_path = repo / PROJECT_DIR / "PROJECT-MEMORY.md"
        items.append(
            _item(
                "project config",
                config_path.is_file(),
                str(config_path) if config_path.exists() else "missing",
                f"manageroo init --agent codex {repo}",
            )
        )
        if config_path.exists():
            try:
                config = load_config(repo)
            except Exception as exc:
                items.append(
                    _item("config parse", False, str(exc), "Fix .manageroo/config.toml")
                )
        items.append(
            _item(
                "product brief",
                brief_path.is_file() and not brief_is_template(brief_path),
                "ready"
                if brief_path.exists() and not brief_is_template(brief_path)
                else "missing or still template",
                "manageroo brief --want \"Describe the result\" --force",
            )
        )
        brief_text = _read_text_if_present(brief_path)
        items.append(
            _item(
                "project memory",
                memory_path.is_file(),
                str(memory_path) if memory_path.exists() else "missing",
                f"{PUBLIC_COMMAND} memory init {repo}",
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
                    "manageroo agent preset codex",
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
                        "`manageroo agent preset generic`."
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
                "manageroo checks suggest --apply-first",
            )
        )
        items.extend(_document_lane_items(repo, config, brief_text))

    gbrain = gbrain_setup_status()
    gbrain_ok = bool(gbrain.get("ok") and gbrain.get("status", {}).get("source_count", 0) > 0)
    memory_requested = bool(_mentions(brief_text, MEMORY_REQUEST_TERMS))
    gbrain_required = require_gbrain or memory_requested
    gbrain_next = (
        "manageroo gbrain-setup --source-id my-project "
        "--path /absolute/path/to/repo --apply --sync"
        if not gbrain_ok
        else "Connect `gbrain serve` to the selected agent if not already wired."
    )
    items.append(
        _item(
            "gbrain",
            gbrain_ok,
            (
                "brief asks for memory/GBrain and sources are mapped"
                if memory_requested and gbrain_ok
                else "sources mapped"
                if gbrain_ok
                else "brief asks for memory/GBrain, but GBrain is not installed, unhealthy, or has no mapped sources"
                if memory_requested
                else "not installed, unhealthy, or no mapped sources"
            ),
            gbrain_next,
            required=gbrain_required,
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
        if not item["ok"] and item.get("severity") == "warning":
            label = "WARN"
        elif not item.get("required", True) and not item["ok"]:
            label = "OPTIONAL"
        lines.append(f"{label} {item['name']}: {item['detail']}")
    if include_next and report.get("next_commands"):
        lines.extend(["", "Next:"])
        lines.append(report["next_commands"][0])
    return "\n".join(lines) + "\n"
