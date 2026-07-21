from __future__ import annotations

import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from .adapters.factory import build_adapter
from .assets import asset_path
from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .errors import ConfigurationError
from .gates import gates_from_config
from .gbrain_setup import gbrain_setup_status
from .project import git_root
from .runner import CommandRunner
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
EXPLICIT_EXTERNAL_MEMORY_TERMS = (
    "gbrain",
    "brain page",
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


def _term_pattern(term: str) -> re.Pattern[str]:
    """Match a signal as a phrase/token instead of as an arbitrary substring.

    This keeps `book` from matching `bookkeeping` while still matching punctuation,
    plural prose around phrases, and case-insensitive user text.
    """
    escaped = re.escape(term)
    left = r"(?<![A-Za-z0-9_])" if term and term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9_])" if term and term[-1].isalnum() else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


def _mentions(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _term_pattern(term).search(text)]


def _repo_document_examples(
    repo: Path,
    *,
    limit: int = 5,
    scan_limit: int = 2000,
) -> list[str]:
    examples: list[str] = []
    scanned = 0
    repo = repo.resolve()
    for current, dirs, files in os.walk(repo, topdown=True, followlinks=False):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in SCAN_SKIP_PARTS and not (Path(current) / name).is_symlink()
        )
        for name in sorted(files):
            if scanned >= scan_limit or len(examples) >= limit:
                return examples
            path = Path(current) / name
            if path.is_symlink():
                continue
            try:
                mode = path.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if not stat.S_ISREG(mode):
                continue
            try:
                relative = path.relative_to(repo)
            except ValueError:
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


def _document_lane_items(
    repo: Path,
    config: dict[str, Any],
    brief_text: str,
) -> list[dict[str, Any]]:
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
                    f"({', '.join(repo_examples[:3])}); configure document_analysis_command if this run needs to understand them"
                ),
                next_command,
                required=False,
                severity="warning",
            )
        ]
    return []


def helper_skill_items() -> list[dict[str, Any]]:
    roots: list[Path] = []
    for root in [
        token_mode_skills_dir(),
        Path.home() / ".codex" / "skills",
        Path.home() / ".agents" / "skills",
    ]:
        expanded = root.expanduser()
        if expanded not in roots:
            roots.append(expanded)
    items: list[dict[str, Any]] = []
    for skill in sorted(CORE_HELPER_SKILLS):
        candidates = [root / skill / "SKILL.md" for root in roots]
        existing = [path for path in candidates if path.is_file()]
        items.append(
            _item(
                f"skill-pack:{skill}",
                bool(existing),
                str(existing[0]) if existing else "missing",
                "manageroo skills reconcile --apply",
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


def _selected_agent_item(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    adapter_name = str(config["agent"]["adapter"])
    next_command = (
        f"Install or authenticate {config['agent'].get('executable', adapter_name)}, or run "
        "`manageroo agent preset generic`."
    )
    try:
        adapter = build_adapter(
            config,
            CommandRunner(log_root=repo / PROJECT_DIR / "cache" / "agent-doctor-logs"),
        )
        doctor = adapter.doctor(repo)
    except Exception as exc:
        return _item(
            "selected agent",
            False,
            f"doctor could not run for {adapter_name}: {type(exc).__name__}: {exc}",
            next_command,
        )
    ok = bool(doctor.get("ok"))
    if ok:
        detail = f"doctor ok: {doctor.get('adapter', adapter_name)}"
        version = doctor.get("version")
        if version:
            detail += f" {version}"
        return _item("selected agent", True, detail)
    detail = f"doctor failed for {doctor.get('adapter', adapter_name)}"
    if doctor.get("error"):
        detail += f": {doctor['error']}"
    missing = doctor.get("missing_required_flags")
    if missing:
        detail += f"; missing required flags: {', '.join(missing)}"
    return _item("selected agent", False, detail, next_command)


def _check_strength_item(gates: list[Any]) -> dict[str, Any] | None:
    if not gates:
        return None
    compile_terms = ("compileall", "py_compile", "tsc", "typecheck", "syntax")
    only_compile = True
    for gate in gates:
        argv = " ".join(str(part).lower() for part in gate.argv)
        if not any(term in argv for term in compile_terms):
            only_compile = False
            break
    if not only_compile:
        return _item("check strength", True, "checks include more than compile-only smoke")
    return _item(
        "check strength",
        False,
        "compile-only check configured; useful smoke proof, but weak product evidence",
        "manageroo checks add product-demo -- COMMAND",
        required=False,
        severity="warning",
    )


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
                f"manageroo init --agent auto {repo}",
            )
        )
        if config_path.exists():
            try:
                config = load_config(repo)
            except Exception as exc:
                items.append(_item("config parse", False, str(exc), "Fix .manageroo/config.toml"))
        items.append(
            _item(
                "product brief",
                brief_path.is_file() and not brief_is_template(brief_path),
                "ready" if brief_path.exists() and not brief_is_template(brief_path) else "missing or still template",
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

    if config and repo:
        items.append(_selected_agent_item(repo, config))
        gates = gates_from_config(config)
        items.append(
            _item(
                "checks",
                bool(gates),
                ", ".join(gate.id for gate in gates) if gates else "no verification gates configured",
                "manageroo checks suggest --apply-first",
            )
        )
        strength = _check_strength_item(gates)
        if strength:
            items.append(strength)
        items.extend(_document_lane_items(repo, config, brief_text))

    gbrain = gbrain_setup_status()
    gbrain_ok = bool(gbrain.get("ok") and gbrain.get("status", {}).get("source_count", 0) > 0)
    external_memory_requested = bool(_mentions(brief_text, EXPLICIT_EXTERNAL_MEMORY_TERMS))
    gbrain_required = require_gbrain or external_memory_requested
    gbrain_next = (
        "manageroo gbrain-setup --source-id my-project --path /absolute/path/to/repo --apply --sync"
        if not gbrain_ok
        else "Connect `gbrain serve` to the selected agent if not already wired."
    )
    items.append(
        _item(
            "gbrain",
            gbrain_ok,
            (
                "brief explicitly asks for external GBrain/knowledge-base context and sources are mapped"
                if external_memory_requested and gbrain_ok
                else "sources mapped"
                if gbrain_ok
                else "brief explicitly asks for external GBrain/knowledge-base context, but GBrain is not installed, unhealthy, or has no mapped sources"
                if external_memory_requested
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