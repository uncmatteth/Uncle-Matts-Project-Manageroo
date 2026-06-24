from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .adapters.factory import build_adapter
from .assets import asset_path
from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .config import load_config
from .errors import ConfigurationError
from .integrations import ExternalCommandIntegration
from .gates import gates_from_config
from .gbrain_scope import gbrain_query_payload, gbrain_source_scope, scope_gbrain_search_record
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


def document_lane_required(brief_text: str) -> bool:
    return bool(_mentions(brief_text, DOCUMENT_REQUEST_TERMS))


def _path_scopes_repo(source_path: str, repo: Path | None) -> bool:
    if not source_path or repo is None:
        return False
    try:
        source = Path(source_path).expanduser().resolve(strict=False)
        repo_path = repo.expanduser().resolve(strict=False)
    except OSError:
        return False
    return source == repo_path


def _gbrain_repo_sources(gbrain: dict[str, Any], repo: Path | None) -> list[dict[str, Any]]:
    status = gbrain.get("status", {})
    sources = status.get("sources", [])
    if not isinstance(sources, list):
        return []
    matches: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        path = (
            source.get("path")
            or source.get("local_path")
            or source.get("source_path")
            or ""
        )
        if _path_scopes_repo(str(path), repo):
            matches.append(source)
    return matches


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
                "manageroo skills reconcile --apply",
                required=True,
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


def _resolve_configured_executable(command: Any, repo: Path) -> str | None:
    if not isinstance(command, str) or not command:
        return None
    path_candidate = Path(command).expanduser()
    has_path_separator = os.sep in command or (os.altsep is not None and os.altsep in command)
    if path_candidate.is_absolute() or has_path_separator:
        resolved = path_candidate if path_candidate.is_absolute() else repo / path_candidate
        return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None
    return shutil.which(command)


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _path_is_inside_without_following_symlink(path: Path, parent: Path) -> bool:
    try:
        path.absolute().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _operator_owned_executable_problem(
    path: Path,
    repo: Path,
    *,
    reject_symlink: bool = False,
) -> str:
    if _path_is_inside_without_following_symlink(path, repo) or _path_is_inside(path, repo):
        return "executable must be operator-owned outside the target repo, not repo-controlled"
    if reject_symlink and path.is_symlink():
        return "probe executable cannot be a symlink"
    return ""


READINESS_PROBE_INTERPRETERS = {
    "bash",
    "bun",
    "cmd",
    "dash",
    "deno",
    "env",
    "fish",
    "node",
    "npx",
    "perl",
    "php",
    "powershell",
    "pwsh",
    "python",
    "python3",
    "ruby",
    "sh",
    "zsh",
}
READINESS_PROBE_INTERPRETER_PREFIXES = (
    "node",
    "perl",
    "php",
    "python",
    "ruby",
)
READINESS_PROBE_WINDOWS_SCRIPT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".ps1",
    ".psm1",
}
READINESS_PROBE_WINDOWS_EXECUTABLE_SUFFIXES = {
    ".com",
    ".exe",
}


def _launcher_name(command_path: Path) -> str:
    name = command_path.name.lower()
    suffix = command_path.suffix.lower()
    if suffix in READINESS_PROBE_WINDOWS_EXECUTABLE_SUFFIXES:
        return name[: -len(suffix)]
    return name


def _trusted_probe_command_problem(
    probe_path: Path,
    args: list[Any],
    repo: Path,
) -> str:
    return _configured_stack_command_problem(
        probe_path,
        args,
        repo,
        _readiness_probe_values(repo),
        subject="trusted readiness probe",
    )


def _configured_stack_command_problem(
    command_path: Path,
    args: list[Any],
    repo: Path,
    values: dict[str, str],
    *,
    subject: str = "configured command",
) -> str:
    command_name = _launcher_name(command_path)
    if command_path.suffix.lower() in READINESS_PROBE_WINDOWS_SCRIPT_SUFFIXES:
        return f"{subject} executable cannot be a shell or interpreter launcher"
    if command_name in READINESS_PROBE_INTERPRETERS or command_name.startswith(
        READINESS_PROBE_INTERPRETER_PREFIXES
    ):
        return f"{subject} executable cannot be a shell or interpreter launcher"
    for arg in args:
        if not isinstance(arg, str) or not arg:
            continue
        try:
            formatted = arg.format(**values)
        except KeyError:
            formatted = arg
        candidate = Path(formatted).expanduser()
        has_path_separator = os.sep in formatted or (os.altsep is not None and os.altsep in formatted)
        path_like = candidate.is_absolute() or has_path_separator
        if not path_like:
            repo_relative = repo / formatted
            if repo_relative.exists():
                candidate = repo_relative
                path_like = True
        elif not candidate.is_absolute():
            candidate = repo / candidate
        if path_like and (
            _path_is_inside(candidate, repo)
            or _path_is_inside_without_following_symlink(candidate, repo)
        ):
            try:
                candidate.relative_to(repo / PROJECT_DIR / "cache" / "readiness-probes")
                continue
            except ValueError:
                return f"{subject} arguments cannot point at repo-controlled paths"
    return ""


def _readiness_probe_values(repo: Path) -> dict[str, str]:
    probe_dir = repo / PROJECT_DIR / "cache" / "readiness-probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    gitnexus_workspace = probe_dir / "gitnexus-workspace"
    gitnexus_workspace.mkdir(parents=True, exist_ok=True)
    (gitnexus_workspace / "README.md").write_text(
        "# Manageroo GitNexus readiness probe\n",
        encoding="utf-8",
    )
    if not (gitnexus_workspace / ".git").is_dir():
        for argv in (
            ["git", "init", "-q", "-b", "manageroo-readiness"],
            ["git", "config", "user.name", "MANAGEROO Readiness"],
            ["git", "config", "user.email", "manageroo-readiness@local.invalid"],
            ["git", "add", "README.md"],
            ["git", "commit", "-q", "-m", "MANAGEROO GitNexus readiness baseline"],
        ):
            subprocess.run(
                argv,
                cwd=gitnexus_workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=30,
                check=False,
            )
    files = {
        "brief_file": probe_dir / "PRODUCT-BRIEF.md",
        "inventory_file": probe_dir / "inventory.json",
        "obsidian_context_file": probe_dir / "obsidian-context.json",
        "external_context_file": probe_dir / "external-intelligence.json",
        "document_manifest_file": probe_dir / "document-manifest.json",
        "document_intelligence_file": probe_dir / "document-intelligence.json",
        "report_file": probe_dir / "FINAL-REPORT.md",
        "result_file": probe_dir / "final-result.json",
        "patch_file": probe_dir / "final.patch",
    }
    files["brief_file"].write_text("# Manageroo readiness probe\n", encoding="utf-8")
    files["inventory_file"].write_text('{"files":[]}\n', encoding="utf-8")
    files["obsidian_context_file"].write_text("[]\n", encoding="utf-8")
    files["external_context_file"].write_text('{"summary":{}}\n', encoding="utf-8")
    files["document_manifest_file"].write_text('{"summary":{}}\n', encoding="utf-8")
    files["document_intelligence_file"].write_text('{"summary":{}}\n', encoding="utf-8")
    files["report_file"].write_text("# Manageroo readiness probe\n", encoding="utf-8")
    files["result_file"].write_text('{"status":"READY_PROBE"}\n', encoding="utf-8")
    files["patch_file"].write_text("", encoding="utf-8")
    query = "manageroo readiness required command probe"
    return {
        "repo": str(repo),
        "source_repo": str(repo),
        "workspace": str(gitnexus_workspace),
        "run_root": str(probe_dir),
        "query": query,
        "gbrain_query_payload": gbrain_query_payload(query, {}),
        "document_state_dir": str(probe_dir / "document-state"),
        "status": "READY_PROBE",
        "summary": "manageroo readiness required command probe",
        "files_changed": "",
        **{key: str(path) for key, path in files.items()},
    }


def _probe_configured_command(
    repo: Path,
    key: str,
    template: list[str],
    *,
    gbrain_source_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        values = _readiness_probe_values(repo)
        if key == "gbrain_search_command" and gbrain_source_item is not None:
            values = {
                **values,
                "gbrain_query_payload": gbrain_query_payload(values["query"], gbrain_source_item),
            }
        cwd = (
            Path(values["workspace"])
            if key in {"gitnexus_analyze_command", "gitnexus_status_command"}
            else repo
        )
        result = ExternalCommandIntegration(template, CommandRunner()).run(
            cwd=cwd,
            values=values,
            timeout_seconds=30,
        )
    except Exception as exc:
        return {
            "name": key,
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    if result is None:
        return {"name": key, "enabled": False, "ok": False}
    record = {
        "name": key,
        "enabled": True,
        "ok": result.passed,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "argv": result.argv,
    }
    if key == "gbrain_search_command" and record["ok"] and gbrain_source_item is not None:
        scoped = scope_gbrain_search_record(
            {
                "name": key,
                "enabled": True,
                "ok": True,
                "stdout": result.stdout or "",
            },
            gbrain_source_item,
            allow_empty=True,
        )
        if not scoped.get("ok"):
            record["ok"] = False
            record["error_type"] = scoped.get("error_type", "ValidationError")
            record["error"] = scoped.get(
                "error",
                "GBrain search output did not prove exact repo-source scope.",
            )
    return record


def _trusted_readiness_probe_template(key: str, template: list[str]) -> list[str]:
    if not template or template[0] not in {"gbrain", "gitnexus"}:
        return []
    if key == "gbrain_search_command":
        if template == ["gbrain", "call", "query", "{gbrain_query_payload}"]:
            return template
        return []
    if key == "gbrain_capture_command":
        if template == ["gbrain", "capture", "--file", "{report_file}"]:
            return ["gbrain", "capture", "--help"]
        return []
    if key == "gitnexus_analyze_command":
        if template == [
            "gitnexus",
            "analyze",
            "{workspace}",
            "--skip-agents-md",
            "--skip-skills",
        ]:
            return template
        return []
    if key == "gitnexus_status_command":
        if template == ["gitnexus", "status"]:
            return template
        return []
    return []


def _stack_command_item(
    repo: Path,
    config: dict[str, Any],
    name: str,
    lane: str,
    keys: tuple[str, ...],
    probe_keys: tuple[str, ...] | None = None,
    probe_command_key: str = "",
    gbrain_source_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    integrations = config.get("integrations", {})
    missing_templates = [key for key in keys if not integrations.get(key)]
    next_command = (
        "Run the installer stack lane or install/configure the missing tool, then rerun "
        f"`{PUBLIC_COMMAND} ready`."
    )
    if missing_templates:
        return _item(
            name,
            False,
            "required command templates are empty: " + ", ".join(missing_templates),
            f"{PUBLIC_COMMAND} integrations configure",
        )
    missing_executables = []
    unsafe_executables = []
    resolved = []
    for key in keys:
        template = integrations.get(key)
        command = template[0] if isinstance(template, list) and template else None
        path = _resolve_configured_executable(command, repo)
        if path:
            ownership_problem = _operator_owned_executable_problem(Path(path), repo)
            if ownership_problem:
                unsafe_executables.append(f"{key}: configured command {ownership_problem}")
            elif not _trusted_readiness_probe_template(key, list(template or [])):
                command_problem = _configured_stack_command_problem(
                    Path(path),
                    list(template[1:] if isinstance(template, list) else []),
                    repo,
                    _readiness_probe_values(repo),
                    subject="configured command",
                )
                if command_problem:
                    unsafe_executables.append(f"{key}: {command_problem}")
            resolved.append(f"{key}:{path}")
        else:
            missing_executables.append(key)
    if missing_executables:
        return _item(
            name,
            False,
            "configured command executable not found for: " + ", ".join(missing_executables),
            next_command,
        )
    if unsafe_executables:
        return _item(
            name,
            False,
            "configured command executable is unsafe: " + "; ".join(unsafe_executables),
            next_command,
        )
    detail = f"{lane} command templates resolve: " + ", ".join(resolved)
    if gbrain_source_item is not None and "gbrain_search_command" in keys:
        source_ids, source_paths = gbrain_source_scope(gbrain_source_item)
        if not gbrain_source_item.get("ok") or (not source_ids and not source_paths):
            return _item(
                name,
                False,
                detail
                + "; exact GBrain repo source is not mapped, so readiness did not execute the search probe",
                gbrain_source_item.get("next", next_command),
            )
    failed_probes = []
    unverified_probes = []
    keys_to_probe = probe_keys if probe_keys is not None else keys
    for key in keys_to_probe:
        template = integrations.get(key)
        probe_template = _trusted_readiness_probe_template(key, list(template or []))
        if not probe_template:
            unverified_probes.append(key)
            continue
        probe_executable = _resolve_configured_executable(probe_template[0], repo)
        if not probe_executable:
            failed_probes.append(f"{key}: probe executable not found")
            continue
        ownership_problem = _operator_owned_executable_problem(Path(probe_executable), repo)
        if ownership_problem:
            failed_probes.append(f"{key}: {ownership_problem}")
            continue
        probe_template = [probe_executable, *probe_template[1:]]
        record = _probe_configured_command(
            repo,
            key,
            probe_template,
            gbrain_source_item=gbrain_source_item,
        )
        if not record.get("ok"):
            detail = record.get("error")
            if not detail:
                detail = "timed out" if record.get("timed_out") else f"exit code {record.get('exit_code', 'unknown')}"
            failed_probes.append(f"{key}: {detail}")
    if failed_probes:
        return _item(
            name,
            False,
            "required command probe failed for: " + "; ".join(failed_probes),
            next_command,
        )
    if unverified_probes:
        trusted_probe = integrations.get(probe_command_key) if probe_command_key else None
        if isinstance(trusted_probe, list) and trusted_probe:
            probe_command = trusted_probe[0]
            probe_path = _resolve_configured_executable(probe_command, repo)
            if not probe_path:
                return _item(
                    name,
                    False,
                    detail
                    + "; configured trusted readiness probe executable not found for "
                    + probe_command_key,
                    next_command,
                )
            ownership_problem = _operator_owned_executable_problem(
                Path(probe_path),
                repo,
                reject_symlink=True,
            )
            if ownership_problem:
                return _item(
                    name,
                    False,
                    detail
                    + "; trusted readiness probe for "
                    + probe_command_key
                    + " is unsafe: "
                    + ownership_problem,
                    next_command,
                )
            probe_problem = _trusted_probe_command_problem(Path(probe_path), trusted_probe[1:], repo)
            if probe_problem:
                return _item(
                    name,
                    False,
                    detail
                    + "; trusted readiness probe for "
                    + probe_command_key
                    + " is unsafe: "
                    + probe_problem,
                    next_command,
                )
            probe_template = [probe_path, *trusted_probe[1:]]
            record = _probe_configured_command(repo, probe_command_key, probe_template)
            if record.get("ok"):
                return _item(
                    name,
                    True,
                    detail
                    + "; trusted readiness probe passed for custom required templates: "
                    + ", ".join(unverified_probes),
                )
            probe_detail = record.get("error")
            if not probe_detail:
                probe_detail = (
                    "timed out"
                    if record.get("timed_out")
                    else f"exit code {record.get('exit_code', 'unknown')}"
                )
            return _item(
                name,
                False,
                detail
                + "; trusted readiness probe failed for "
                + probe_command_key
                + f": {probe_detail}",
                next_command,
            )
        return _item(
            name,
            False,
            detail
            + "; readiness did not execute custom required command templates: "
            + ", ".join(unverified_probes)
            + (
                f". Configure the default required stack templates or set "
                f"{probe_command_key} to a non-mutating trusted probe."
                if probe_command_key
                else ". Configure the default required stack templates."
            ),
            next_command,
        )
    return _item(name, True, detail)


def stack_command_lane_items(
    repo: Path,
    config: dict[str, Any],
    *,
    gbrain_source_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        _stack_command_item(
            repo,
            config,
            "gbrain command lane",
            "gbrain",
            ("gbrain_search_command", "gbrain_capture_command"),
            probe_keys=("gbrain_search_command", "gbrain_capture_command"),
            probe_command_key="gbrain_readiness_probe_command",
            gbrain_source_item=gbrain_source_item,
        ),
        _stack_command_item(
            repo,
            config,
            "gitnexus command lane",
            "gitnexus",
            ("gitnexus_analyze_command", "gitnexus_status_command"),
            probe_command_key="gitnexus_readiness_probe_command",
        ),
    ]


def stack_capture_command_safety_item(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    return _stack_command_item(
        repo,
        config,
        "gbrain capture command",
        "gbrain capture",
        ("gbrain_capture_command",),
        probe_keys=(),
    )


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


def gbrain_repo_source_item(repo: Path | None, brief_text: str = "") -> dict[str, Any]:
    gbrain = gbrain_setup_status()
    gbrain_sources = _gbrain_repo_sources(gbrain, repo)
    gbrain_ok = bool(gbrain.get("ok") and gbrain_sources)
    memory_requested = bool(_mentions(brief_text, MEMORY_REQUEST_TERMS))
    gbrain_repo_hint = str(repo) if repo else "/absolute/path/to/repo"
    gbrain_next = (
        "manageroo gbrain-setup --source-id my-project "
        f"--path {gbrain_repo_hint} --apply --sync"
        if not gbrain_ok
        else "Connect `gbrain serve` to the selected agent if not already wired."
    )
    if gbrain_ok:
        source_labels = []
        for source in gbrain_sources[:3]:
            label = source.get("id") or source.get("name") or source.get("path") or "mapped source"
            source_labels.append(str(label))
        gbrain_detail = (
            "brief asks for memory/GBrain and repo-scoped source is mapped"
            if memory_requested
            else "repo-scoped source is mapped"
        )
        if source_labels:
            gbrain_detail += f": {', '.join(source_labels)}"
    elif repo is None and gbrain.get("ok") and gbrain.get("status", {}).get("source_count", 0) > 0:
        gbrain_detail = "GBrain has mapped sources, but no target repo is available to scope them"
    elif gbrain.get("ok") and gbrain.get("status", {}).get("source_count", 0) > 0:
        gbrain_detail = (
            "brief asks for memory/GBrain, but no mapped GBrain source matches this repo"
            if memory_requested
            else "GBrain has mapped sources, but none match this repo"
        )
    else:
        gbrain_detail = (
            "brief asks for memory/GBrain, but GBrain is not installed, unhealthy, or has no mapped sources"
            if memory_requested
            else "not installed, unhealthy, or no mapped sources"
        )
    item = _item(
        "gbrain",
        gbrain_ok,
        gbrain_detail,
        gbrain_next,
        required=True,
    )
    if gbrain_sources:
        item["matched_sources"] = [
            {
                key: source.get(key)
                for key in ("id", "name", "path")
                if source.get(key)
            }
            for source in gbrain_sources
            if isinstance(source, dict)
        ]
    return item


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

    gbrain_item = gbrain_repo_source_item(repo, brief_text)

    if config:
        items.append(_selected_agent_item(repo, config))
        items.extend(
            stack_command_lane_items(
                repo,
                config,
                gbrain_source_item=gbrain_item,
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
        strength = _check_strength_item(gates)
        if strength:
            items.append(strength)
        items.extend(_document_lane_items(repo, config, brief_text))

    items.append(gbrain_item)

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
