#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manageroo.branding import FULL_NAME, print_banner, status_line  # noqa: E402
from manageroo.chiptune import ThemePlayback, play_once  # noqa: E402
from manageroo.credits import format_special_thanks  # noqa: E402
from manageroo.install_status import summarize_external_tools, uninstall_plan  # noqa: E402
from manageroo.token_modes import CORE_HELPER_SKILLS, install_core_helper_skills, set_token_mode  # noqa: E402
from manageroo.util import atomic_write_json  # noqa: E402

# Manageroo releases pin every third-party source that this installer can execute or copy.
# Updating one of these pins is a source change that goes through Manageroo's own release proof.
CODEX_NPM_PACKAGE = "@openai/codex@0.144.4"
GBRAIN_COMMIT = "3cc34c92eec2540ef36d2513eff8d4e4bf73bad9"
GBRAIN_INSTALL_SOURCE = f"github:garrytan/gbrain#{GBRAIN_COMMIT}"
GBRAIN_AGENT_INSTALL_PROTOCOL_URL = (
    f"https://raw.githubusercontent.com/garrytan/gbrain/{GBRAIN_COMMIT}/INSTALL_FOR_AGENTS.md"
)
GBRAIN_LOCAL_INSTALL_REFERENCE = f"https://github.com/garrytan/gbrain/tree/{GBRAIN_COMMIT}"
GITNEXUS_VERSION = "1.6.9"
GITNEXUS_NPM_PACKAGE = f"gitnexus@{GITNEXUS_VERSION}"
GITNEXUS_REFERENCE = "https://github.com/abhigyanpatwari/GitNexus"
OPENCLAW_AGENT_SKILLS_REPO = "https://github.com/openclaw/agent-skills.git"
OPENCLAW_AGENT_SKILLS_COMMIT = "c4ab5e7f999cf504890986322473d3e7afd373af"
AUTOREVIEW_REFERENCE = (
    "https://github.com/openclaw/agent-skills/tree/"
    f"{OPENCLAW_AGENT_SKILLS_COMMIT}/skills/autoreview"
)
PNPM_PACKAGE = "pnpm@11.1.2"
CLAWPATCH_VERSION = "0.7.1"
CLAWPATCH_PACKAGE = f"clawpatch@{CLAWPATCH_VERSION}"
CLAWPATCH_REFERENCE = "https://github.com/openclaw/clawpatch"
OBSIDIAN_HELP_URL = "https://obsidian.md/help/install"


def run(
    argv: list[str],
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    *,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    status_line("RUN", shlex.join([str(item) for item in argv]))
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        env=process_env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        shell=False,
    )
    if capture and result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        raise SystemExit(result.returncode)
    return result


def tree_hash(root: Path) -> str:
    root = root.resolve()
    digest = hashlib.sha256()
    excluded = {".git", ".venv", "__pycache__", "dist", "build"}
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def command_version(executable: str) -> str:
    path = shutil.which(executable)
    if not path:
        return "not installed"
    try:
        result = subprocess.run(
            [path, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=30,
        )
        return (result.stdout or "").strip() or f"exit {result.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"


def _safe_cmd_value(path: Path) -> str:
    text = str(path)
    if any(character in text for character in ('"', "\r", "\n")):
        raise SystemExit(f"Installer path contains characters unsafe for a Windows command launcher: {text!r}")
    return text


def install_launcher(bin_dir: Path, python: Path, app_root: Path, prefix: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        launcher = bin_dir / "manageroo.cmd"
        launcher.write_text(
            f'@set "PYTHONPATH={_safe_cmd_value(app_root)}"\r\n'
            f'@set "MANAGEROO_PREFIX={_safe_cmd_value(prefix)}"\r\n'
            f'@"{_safe_cmd_value(python)}" -m manageroo %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / "manageroo"
        app_value = shlex.quote(str(app_root))
        prefix_value = shlex.quote(str(prefix))
        python_value = shlex.quote(str(python))
        launcher.write_text(
            "#!/bin/sh\n"
            f"export PYTHONPATH={app_value}${{PYTHONPATH:+:$PYTHONPATH}}\n"
            f"export MANAGEROO_PREFIX={prefix_value}\n"
            f"exec {python_value} -m manageroo \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


def prepend_tool_paths() -> None:
    candidates = [
        Path.home() / ".local" / "bin",
        Path.home() / ".local" / "share" / "pnpm",
        Path.home() / ".pnpm-global" / "bin",
        Path.home() / ".bun" / "bin",
        Path.home() / "bin",
    ]
    if os.name == "nt":
        if os.environ.get("APPDATA"):
            candidates.insert(0, Path(os.environ["APPDATA"]) / "npm")
        if os.environ.get("LOCALAPPDATA"):
            candidates.insert(0, Path(os.environ["LOCALAPPDATA"]) / "pnpm")
    os.environ["PATH"] = os.pathsep.join(
        [*(str(item) for item in candidates if item.exists()), os.environ.get("PATH", "")]
    )


def _ensure_node_npm() -> str | None:
    npm = shutil.which("npm")
    if npm:
        return npm
    if os.name == "nt" and shutil.which("winget"):
        run(
            [
                shutil.which("winget") or "winget",
                "install",
                "--id",
                "OpenJS.NodeJS.LTS",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            capture=False,
        )
        prepend_tool_paths()
        common_npm = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd"
        return shutil.which("npm") or (str(common_npm) if common_npm.exists() else None)
    return None


def install_codex_latest(downloads: list[dict]) -> dict:
    """Install the Codex version pinned by this Manageroo release.

    The historical function name is retained for CLI/test compatibility; it no longer
    resolves npm's mutable `latest` tag.
    """
    before = command_version("codex")
    status_line("CODEX", f"current: {before}")
    npm = _ensure_node_npm()
    if not npm:
        raise SystemExit(
            "Codex installation requires Node.js/npm. Manageroo will not download and execute an unverified shell installer. "
            "Install Node.js LTS, then rerun with --install-codex."
        )
    run([npm, "install", "-g", CODEX_NPM_PACKAGE], cwd=Path.home(), capture=False)
    downloads.append(
        {
            "tool": "codex",
            "method": npm,
            "source": CODEX_NPM_PACKAGE,
            "immutable": True,
            "previous_version": before,
        }
    )
    prepend_tool_paths()
    after = command_version("codex")
    status_line("CODEX", after, ok=after != "not installed")
    return {"path": shutil.which("codex"), "version": after, "source": CODEX_NPM_PACKAGE}


def optional_run(
    argv: list[str],
    downloads: list[dict],
    tool: str,
    source: str,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> dict:
    try:
        run(argv, cwd=cwd, env=env, capture=False)
    except SystemExit as exc:
        return {
            "ok": False,
            "argv": argv,
            "source": source,
            "cwd": str(cwd),
            "error": f"exit {exc.code}",
        }
    downloads.append(
        {
            "tool": tool,
            "method": argv[0],
            "source": source,
            "argv": argv,
            "cwd": str(cwd),
            "immutable": _source_is_immutable(source),
        }
    )
    return {"ok": True, "argv": argv, "source": source}


def _source_is_immutable(source: str) -> bool:
    lowered = source.lower()
    if "@latest" in lowered:
        return False
    if source.startswith("github:") or source.startswith("git+"):
        return "#" in source and len(source.rsplit("#", 1)[-1]) >= 12
    if "github.com/" in source and source.endswith(".git"):
        return False
    if "@" in source and not source.startswith("http"):
        version = source.rsplit("@", 1)[-1]
        return bool(version and version != "latest")
    return True


def probe_command(argv: list[str], cwd: Path = Path.home(), timeout: int = 30) -> dict:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "argv": argv,
            "output": (result.stdout or "").strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "argv": argv, "error": str(exc), "output": ""}


def run_interactive_action(argv: list[str], *, cwd: Path = Path.home()) -> dict:
    status_line("RUN", shlex.join(argv))
    try:
        result = subprocess.run(argv, cwd=str(cwd), shell=False)
    except OSError as exc:
        return {"ok": False, "argv": argv, "error": str(exc)}
    return {"ok": result.returncode == 0, "argv": argv, "exit_code": result.returncode}


def guidance(tool: str, reason: str, commands: list[str], url: str | None = None) -> dict:
    status_line(tool.upper(), reason)
    if commands:
        print("  Next commands:")
        for command in commands:
            print(f"    {command}")
    if url:
        print(f"  Reference: {url}")
    return {
        "name": tool,
        "installed": False,
        "configured": False,
        "guidance": reason,
        "next_commands": commands,
        "reference": url,
    }


def safe_probe_record(probe: dict | None) -> dict | None:
    if probe is None:
        return None
    return {key: probe[key] for key in ("ok", "exit_code", "argv", "error") if key in probe}


def parse_gbrain_config(output: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line or not line.startswith("  "):
            continue
        key, value = line.strip().split(":", 1)
        config[key.strip()] = value.strip()
    return config


def summarize_gbrain_sync(output: str) -> dict:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"parse_error": "status output was not JSON"}
    sync = payload.get("sync") if isinstance(payload, dict) else None
    if not isinstance(sync, dict) or not isinstance(sync.get("sources"), list):
        return {"parse_error": "status output did not include sync sources"}
    sources = sync["sources"]
    coverages = [
        float(source["embedding_coverage_pct"])
        for source in sources
        if isinstance(source, dict) and source.get("embedding_coverage_pct") is not None
    ]
    return {
        "sources": len(sources),
        "chunks_total": sum(
            int(source.get("chunks_total") or 0) for source in sources if isinstance(source, dict)
        ),
        "chunks_unembedded": sum(
            int(source.get("chunks_unembedded") or 0) for source in sources if isinstance(source, dict)
        ),
        "embedding_coverage_min_pct": min(coverages) if coverages else None,
        "unacknowledged_failures": sync.get("unacknowledged_failures"),
    }


def install_gbrain(downloads: list[dict], lane: str = "local") -> dict:
    cwd = Path.home()
    prepend_tool_paths()
    before = command_version("gbrain")
    if lane == "skip":
        return {
            "name": "gbrain",
            "installed": before != "not installed",
            "configured": False,
            "skipped": True,
            "reason": "GBrain stack lane skipped by installer option.",
            "version": before,
            "path": shutil.which("gbrain"),
            "lane": "skip",
            "reference": GBRAIN_LOCAL_INSTALL_REFERENCE,
        }
    installed_before = before != "not installed"
    install_result = None
    if not installed_before:
        if lane == "official":
            return guidance(
                "gbrain",
                "Official GBrain agent-supervised install lane selected. Manageroo will not guess credentials, models, source mapping, or recurring jobs.",
                [
                    f"Open the pinned official guide: {GBRAIN_AGENT_INSTALL_PROTOCOL_URL}",
                    "Afterward run: gbrain doctor --json",
                    "Then rerun: manageroo stack-status",
                ],
                GBRAIN_AGENT_INSTALL_PROTOCOL_URL,
            ) | {
                "lane": "official-agent-protocol",
                "official_protocol_url": GBRAIN_AGENT_INSTALL_PROTOCOL_URL,
            }
        bun = shutil.which("bun")
        if not bun:
            return guidance(
                "gbrain",
                "Bun is required before GBrain can be installed by this installer.",
                [
                    "Install Bun from https://bun.sh/",
                    f"bun install -g {GBRAIN_INSTALL_SOURCE}",
                    "gbrain init --pglite",
                    "gbrain doctor --json",
                ],
                GBRAIN_LOCAL_INSTALL_REFERENCE,
            )
        install_result = optional_run(
            [bun, "install", "-g", GBRAIN_INSTALL_SOURCE],
            downloads,
            "gbrain",
            GBRAIN_INSTALL_SOURCE,
            cwd=cwd,
        )
        prepend_tool_paths()
    gbrain = shutil.which("gbrain")
    init_result = None
    doctor_result = None
    config_probe = None
    sync_probe = None
    config_summary: dict[str, str] = {}
    sync_summary: dict = {}
    if gbrain:
        if not installed_before:
            init_result = optional_run(
                [gbrain, "init", "--pglite"],
                downloads,
                "gbrain-init",
                GBRAIN_INSTALL_SOURCE,
                cwd=cwd,
            )
            optional_run(
                [gbrain, "skillpack", "scaffold", "--all"],
                downloads,
                "gbrain-skillpack",
                GBRAIN_INSTALL_SOURCE,
                cwd=cwd,
            )
        doctor_result = probe_command([gbrain, "doctor", "--json"], cwd=cwd, timeout=60)
        config_probe = probe_command([gbrain, "config", "show"], cwd=cwd)
        sync_probe = probe_command([gbrain, "status", "--json", "--section", "sync"], cwd=cwd)
        config_summary = parse_gbrain_config(config_probe.get("output", "")) if config_probe.get("ok") else {}
        sync_summary = summarize_gbrain_sync(sync_probe.get("output", "")) if sync_probe.get("ok") else {}
    after = command_version("gbrain")
    config_ok = bool(config_probe and config_probe.get("ok") and config_summary)
    sync_ok = bool(sync_probe and sync_probe.get("ok") and "parse_error" not in sync_summary)
    doctor_ok = bool(doctor_result and doctor_result.get("ok"))
    next_commands: list[str] = []
    if after != "not installed" and not doctor_ok:
        next_commands.append("gbrain doctor --json")
    if after != "not installed" and not sync_ok:
        next_commands.append("gbrain status --json --section sync")
    if sync_ok and sync_summary.get("sources", 0) == 0:
        next_commands.extend(
            [
                "gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder",
                "gbrain sync --source YOUR_SOURCE_ID --json --yes",
            ]
        )
    return {
        "name": "gbrain",
        "lane": "existing-inspected" if installed_before else "local-cli",
        "installed": after != "not installed",
        "configured": bool(
            after != "not installed"
            and doctor_ok
            and (
                (installed_before and config_ok and sync_ok)
                or (not installed_before and init_result and init_result.get("ok"))
            )
        ),
        "version": after,
        "path": shutil.which("gbrain"),
        "install_result": install_result,
        "init_result": init_result,
        "doctor_result": safe_probe_record(doctor_result),
        "config_probe": safe_probe_record(config_probe),
        "sync_probe": safe_probe_record(sync_probe),
        "config_summary": config_summary,
        "sync_summary": sync_summary,
        "next_commands": next_commands,
        "guidance_commands": [
            "Connect `gbrain serve` to the selected agent when external memory is needed."
        ],
        "reference": GBRAIN_LOCAL_INSTALL_REFERENCE,
        "pinned_commit": GBRAIN_COMMIT,
    }


def install_gitnexus(downloads: list[dict]) -> dict:
    before = command_version("gitnexus")
    npm = _ensure_node_npm()
    if before == "not installed" and not npm:
        return guidance(
            "gitnexus",
            "Node.js/npm is required before GitNexus can be installed.",
            ["Install Node.js LTS", f"npm install -g {GITNEXUS_NPM_PACKAGE}", "gitnexus setup"],
            GITNEXUS_REFERENCE,
        )
    install_result = None
    if before == "not installed" and npm:
        install_result = optional_run(
            [npm, "install", "-g", GITNEXUS_NPM_PACKAGE],
            downloads,
            "gitnexus",
            GITNEXUS_NPM_PACKAGE,
            cwd=Path.home(),
        )
        prepend_tool_paths()
    after = command_version("gitnexus")
    return {
        "name": "gitnexus",
        "installed": after != "not installed",
        "configured": False,
        "version": after,
        "path": shutil.which("gitnexus"),
        "install_result": install_result,
        "next_commands": ["gitnexus setup"] if after != "not installed" else [f"npm install -g {GITNEXUS_NPM_PACKAGE}"],
        "reference": GITNEXUS_REFERENCE,
        "pinned_version": GITNEXUS_VERSION,
    }


def _backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.manageroo-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.manageroo-backup-{stamp}-{index}")
        index += 1
    return candidate


def _run_checked(argv: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError((result.stdout or "").strip() or f"Command failed: {shlex.join(argv)}")
    return result


def _checkout_pinned_git_source(
    *,
    git: str,
    repository: str,
    commit: str,
    destination: Path,
) -> dict:
    """Clone and verify an immutable Git commit before any downloaded content is copied."""
    _run_checked([git, "clone", "--no-checkout", repository, str(destination)], cwd=destination.parent)
    _run_checked([git, "checkout", "--detach", commit], cwd=destination)
    resolved = _run_checked([git, "rev-parse", "HEAD"], cwd=destination).stdout.strip().lower()
    if resolved != commit.lower():
        raise RuntimeError(f"Pinned Git source verification failed: expected {commit}, received {resolved}")
    return {"repository": repository, "commit": commit, "resolved_commit": resolved}


def install_autoreview(downloads: list[dict], prefix: Path) -> dict:
    del prefix  # kept for backwards-compatible call shape
    candidates = [
        Path.home() / ".agents" / "skills" / "autoreview",
        Path.home() / ".codex" / "skills" / "autoreview",
    ]
    existing = next((path for path in candidates if (path / "scripts" / "autoreview").exists()), None)
    if existing:
        return {
            "name": "autoreview",
            "installed": True,
            "configured": True,
            "path": str(existing / "scripts" / "autoreview"),
            "reference": AUTOREVIEW_REFERENCE,
        }
    git = shutil.which("git")
    if not git:
        return guidance(
            "autoreview",
            "Git is required to install AUTOREVIEW.",
            ["Install Git, then rerun the Manageroo installer."],
            AUTOREVIEW_REFERENCE,
        )
    destination = candidates[0]
    with tempfile.TemporaryDirectory(prefix="manageroo-autoreview-install-") as temp:
        checkout = Path(temp) / "agent-skills"
        try:
            verification = _checkout_pinned_git_source(
                git=git,
                repository=OPENCLAW_AGENT_SKILLS_REPO,
                commit=OPENCLAW_AGENT_SKILLS_COMMIT,
                destination=checkout,
            )
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            return {
                "name": "autoreview",
                "installed": False,
                "configured": False,
                "error": f"Pinned AUTOREVIEW source could not be checked out: {exc}",
                "reference": AUTOREVIEW_REFERENCE,
            }
        source = checkout / "skills" / "autoreview"
        if (
            not (source / "SKILL.md").is_file()
            or source.is_symlink()
            or any(path.is_symlink() for path in source.rglob("*"))
        ):
            return {
                "name": "autoreview",
                "installed": False,
                "configured": False,
                "error": "Pinned AUTOREVIEW source could not be validated.",
                "reference": AUTOREVIEW_REFERENCE,
            }
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.rename(_backup_path(destination))
        shutil.copytree(source, destination)
        downloads.append(
            {
                "tool": "autoreview",
                "method": "git",
                "source": f"{OPENCLAW_AGENT_SKILLS_REPO}#{OPENCLAW_AGENT_SKILLS_COMMIT}",
                "repository": OPENCLAW_AGENT_SKILLS_REPO,
                "commit": OPENCLAW_AGENT_SKILLS_COMMIT,
                "resolved_commit": verification["resolved_commit"],
                "immutable": True,
            }
        )
    script = destination / "scripts" / "autoreview"
    return {
        "name": "autoreview",
        "installed": script.exists(),
        "configured": script.exists(),
        "path": str(script),
        "reference": AUTOREVIEW_REFERENCE,
        "pinned_commit": OPENCLAW_AGENT_SKILLS_COMMIT,
    }


def ensure_pnpm(downloads: list[dict]) -> str | None:
    pnpm = shutil.which("pnpm")
    npm = _ensure_node_npm()
    if not pnpm and npm:
        result = optional_run(
            [npm, "install", "-g", PNPM_PACKAGE],
            downloads,
            "pnpm",
            PNPM_PACKAGE,
            cwd=Path.home(),
        )
        if not result.get("ok"):
            return None
        prepend_tool_paths()
        pnpm = shutil.which("pnpm")
    return pnpm


def check_clawpatch_codex_provider(login_mode: str) -> dict:
    codex = shutil.which("codex")
    if not codex:
        return {
            "name": "codex-provider",
            "ok": False,
            "next_commands": [
                "Install Codex if Clawpatch should use its codex provider.",
                "codex login",
                "clawpatch doctor",
            ],
            "reason": "Codex CLI is unavailable.",
        }
    status_probe = probe_command([codex, "login", "status"], cwd=Path.home(), timeout=30)
    login_result = None
    if not status_probe.get("ok") and login_mode != "skip":
        should_run = login_mode == "run"
        if login_mode == "ask" and sys.stdin.isatty():
            should_run = input(
                "Clawpatch's codex provider needs Codex login. Run `codex login` now? [Y/n]: "
            ).strip().lower() not in {"n", "no", "skip"}
        if should_run:
            login_result = run_interactive_action([codex, "login"])
            status_probe = probe_command([codex, "login", "status"], cwd=Path.home(), timeout=30)
    return {
        "name": "codex-provider",
        "ok": bool(status_probe.get("ok")),
        "path": codex,
        "status_probe": safe_probe_record(status_probe),
        "login_result": login_result,
        "next_commands": [] if status_probe.get("ok") else ["codex login", "clawpatch doctor"],
    }


def install_clawpatch(downloads: list[dict], codex_login_mode: str = "ask") -> dict:
    before = command_version("clawpatch")
    install_result = None
    if before == "not installed":
        pnpm = ensure_pnpm(downloads)
        if not pnpm:
            return guidance(
                "clawpatch",
                "pnpm is required before Clawpatch can be installed.",
                [f"npm install -g {PNPM_PACKAGE}", f"pnpm add -g {CLAWPATCH_PACKAGE}", "clawpatch doctor"],
                CLAWPATCH_REFERENCE,
            )
        install_result = optional_run(
            [pnpm, "add", "-g", CLAWPATCH_PACKAGE],
            downloads,
            "clawpatch",
            CLAWPATCH_PACKAGE,
            cwd=Path.home(),
        )
        prepend_tool_paths()
    clawpatch = shutil.which("clawpatch")
    doctor_result = (
        optional_run(
            [clawpatch, "doctor"],
            downloads,
            "clawpatch-doctor",
            CLAWPATCH_PACKAGE,
            cwd=Path.home(),
        )
        if clawpatch
        else None
    )
    codex_provider = check_clawpatch_codex_provider(codex_login_mode)
    after = command_version("clawpatch")
    next_commands = list(codex_provider.get("next_commands", []))
    if (
        after != "not installed"
        and not (doctor_result and doctor_result.get("ok"))
        and "clawpatch doctor" not in next_commands
    ):
        next_commands.append("clawpatch doctor")
    return {
        "name": "clawpatch",
        "installed": after != "not installed",
        "configured": bool(doctor_result and doctor_result.get("ok") and codex_provider.get("ok")),
        "version": after,
        "path": clawpatch,
        "install_result": install_result,
        "doctor_result": doctor_result,
        "codex_provider": codex_provider,
        "next_commands": next_commands,
        "reference": CLAWPATCH_REFERENCE,
        "pinned_version": CLAWPATCH_VERSION,
    }


def install_obsidian(downloads: list[dict], method: str) -> dict:
    before = command_version("obsidian")
    if before != "not installed":
        return {
            "name": "obsidian",
            "installed": True,
            "configured": True,
            "version": before,
            "path": shutil.which("obsidian"),
            "reference": OBSIDIAN_HELP_URL,
        }
    system = platform.system().lower()
    candidates: list[list[str]] = []
    if method in {"auto", "winget"} and system == "windows" and shutil.which("winget"):
        candidates.append(
            [
                shutil.which("winget") or "winget",
                "install",
                "--id",
                "Obsidian.Obsidian",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        )
    elif method in {"auto", "brew"} and system == "darwin" and shutil.which("brew"):
        candidates.append([shutil.which("brew") or "brew", "install", "--cask", "obsidian"])
    elif method in {"auto", "flatpak"} and system == "linux" and shutil.which("flatpak"):
        candidates.append(
            [
                shutil.which("flatpak") or "flatpak",
                "install",
                "--user",
                "-y",
                "flathub",
                "md.obsidian.Obsidian",
            ]
        )
    elif (
        method in {"auto", "snap"}
        and system == "linux"
        and shutil.which("snap")
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    ):
        candidates.append([shutil.which("snap") or "snap", "install", "obsidian", "--classic"])
    if candidates:
        result = optional_run(
            candidates[0],
            downloads,
            "obsidian",
            "operator-selected-os-package-manager",
            cwd=Path.home(),
        )
        after = command_version("obsidian")
        return {
            "name": "obsidian",
            "installed": after != "not installed" or result.get("ok"),
            "configured": after != "not installed" or result.get("ok"),
            "version": after,
            "path": shutil.which("obsidian"),
            "install_result": result,
            "reference": OBSIDIAN_HELP_URL,
        }
    return guidance(
        "obsidian",
        "No supported automatic Obsidian installer was available.",
        ["Install Obsidian from https://obsidian.md/download"],
        OBSIDIAN_HELP_URL,
    )


def install_recommended_stack(
    downloads: list[dict],
    obsidian_method: str,
    prefix: Path,
    gbrain_lane: str,
    clawpatch_codex_login: str,
) -> list[dict]:
    return [
        install_gbrain(downloads, gbrain_lane),
        install_gitnexus(downloads),
        install_autoreview(downloads, prefix),
        install_clawpatch(downloads, clawpatch_codex_login),
        install_obsidian(downloads, obsidian_method),
    ]


def choose_token_mode(selection: str) -> str:
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "off"
    print("Token mode: 1) off  2) caveman  3) Uncle Matt's Caveman Curse")
    return {"2": "caveman", "3": "curse"}.get(input("Choose 1, 2, or 3 [1]: ").strip(), "off")


def choose_skill_pack_mode(selection: str, skip_flag: bool) -> str:
    if skip_flag:
        return "skip"
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "install"
    return (
        "skip"
        if input("Install Manageroo's portable core agent skill pack? [Y/n]: ").strip().lower()
        in {"n", "no", "skip"}
        else "install"
    )


def choose_stack_mode(selection: str, install_flag: bool, skip_flag: bool) -> str:
    if install_flag:
        return "install"
    if skip_flag:
        return "skip"
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "skip"
    print("Recommended surrounding stack:")
    print("  - GBrain external knowledge lane")
    print("  - GitNexus repository/code-graph intelligence")
    print("  - AUTOREVIEW review helper")
    print("  - Clawpatch review and repair loop")
    print("  - Obsidian notes")
    return (
        "skip"
        if input("Install and guide this stack now? [Y/n]: ").strip().lower()
        in {"n", "no", "skip"}
        else "install"
    )


def choose_gbrain_lane(selection: str) -> str:
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "local"
    print("GBrain setup lane: 1) local  2) official agent-supervised protocol  3) skip")
    return {"2": "official", "3": "skip"}.get(input("Choose 1, 2, or 3 [1]: ").strip(), "local")


def choose_project_discovery_mode(selection: str) -> str:
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "skip"
    return (
        "skip"
        if input("Run guided project setup now? [Y/n]: ").strip().lower() in {"n", "no", "skip"}
        else "add"
    )


def choose_stack_doctor_mode(selection: str) -> str:
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "skip"
    return (
        "skip"
        if input("Run the read-only smart stack doctor now? [Y/n]: ").strip().lower()
        in {"n", "no", "skip"}
        else "run"
    )


def print_next_commands() -> None:
    print("\nNext commands:")
    for command in [
        "manageroo --version",
        "manageroo self-test",
        "manageroo skills list",
        "manageroo stack-status",
        "manageroo stack-doctor",
        "manageroo repair-install --no-apply",
        "manageroo projects --add",
        "manageroo next",
    ]:
        print(f"  {command}")


def print_lane_explainer() -> None:
    print("\nHow Manageroo fits together:")
    print("  - Manageroo owns run truth, planning, scope, verification, review, evidence, repair, and completion.")
    print("  - GitNexus is first-class recommended repository intelligence when installed and configured.")
    print("  - GBrain is an external durable knowledge lane when explicitly relevant.")
    print("  - AUTOREVIEW and Clawpatch are command-owned review/repair lanes, not freehand AI repair prompts.")
    print("  - Host skills may be used when relevant but remain host-owned unless they are in Manageroo's portable core.")


def _assert_download_sources_immutable(downloads: list[dict]) -> None:
    unsafe = [
        str(item.get("source") or "")
        for item in downloads
        if item.get("source")
        and item.get("source") != "operator-selected-os-package-manager"
        and not item.get("immutable", _source_is_immutable(str(item.get("source") or "")))
    ]
    if unsafe:
        raise SystemExit(
            "Installer refused mutable third-party source records: " + ", ".join(sorted(set(unsafe)))
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Install {FULL_NAME}")
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local" / "share" / "manageroo")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-codex", action="store_true")
    parser.add_argument("--skip-codex", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stack", choices=["ask", "skip", "install"], default="ask")
    parser.add_argument("--install-stack", action="store_true")
    parser.add_argument("--skip-stack", action="store_true")
    parser.add_argument(
        "--obsidian-method",
        choices=["auto", "guide", "flatpak", "snap", "brew", "winget"],
        default="auto",
    )
    parser.add_argument("--gbrain-lane", choices=["ask", "local", "official", "skip"], default="ask")
    parser.add_argument("--clawpatch-codex-login", choices=["ask", "run", "skip"], default="ask")
    parser.add_argument("--token-mode", choices=["ask", "off", "caveman", "curse"], default="ask")
    parser.add_argument("--project-discovery", choices=["ask", "pick", "add", "skip"], default="ask")
    parser.add_argument("--stack-doctor", choices=["ask", "run", "skip"], default="ask")
    parser.add_argument("--skill-pack", choices=["ask", "install", "skip"], default="ask")
    parser.add_argument("--skip-skill-pack", action="store_true")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args()

    if args.install_stack and args.skip_stack:
        raise SystemExit("--install-stack and --skip-stack conflict. Choose one.")
    if args.skip_skill_pack and args.skill_pack == "install":
        raise SystemExit("--skip-skill-pack conflicts with --skill-pack install.")

    banner_ticker = print_banner(animation=not args.no_animation, persistent_rainbow=True)
    if banner_ticker:
        atexit.register(banner_ticker.stop)
    print(f"Installing {FULL_NAME}\n")
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    if shutil.which("git") is None:
        raise SystemExit("Git is required.")

    downloads: list[dict] = []
    external_tools: list[dict] = []
    with ThemePlayback(cue="install", enabled=not args.no_music, variant=69):
        prefix = args.prefix.expanduser().resolve()
        venv_root = prefix / "venv"
        app_root = prefix / "app"
        prefix.mkdir(parents=True, exist_ok=True)
        token_mode = choose_token_mode(args.token_mode)
        source_env = {"PYTHONPATH": str(ROOT / "src")}
        if not args.skip_tests:
            run([sys.executable, "-m", "compileall", "-q", "src"], env=source_env)
            run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], env=source_env)

        token_mode_record = set_token_mode(token_mode, install_skills=token_mode != "off")
        skill_pack_mode = choose_skill_pack_mode(args.skill_pack, args.skip_skill_pack)
        helper_skills_record = (
            {
                "skipped": True,
                "reason": "Portable core skill pack skipped.",
                "install_later": "manageroo skills reconcile --apply",
                "recommended_skills": sorted(CORE_HELPER_SKILLS),
            }
            if skill_pack_mode == "skip"
            else install_core_helper_skills()
        )

        if args.install_codex and not args.skip_codex:
            external_tools.append({"name": "codex", **install_codex_latest(downloads)})
        else:
            external_tools.append(
                {
                    "name": "codex",
                    "path": shutil.which("codex"),
                    "version": command_version("codex"),
                    "skipped": True,
                    "reason": "Codex is an adapter choice, not a core requirement.",
                }
            )

        stack_mode = choose_stack_mode(args.stack, args.install_stack, args.skip_stack)
        if stack_mode == "install":
            external_tools.extend(
                install_recommended_stack(
                    downloads,
                    args.obsidian_method,
                    prefix,
                    choose_gbrain_lane(args.gbrain_lane),
                    args.clawpatch_codex_login,
                )
            )
        else:
            external_tools.append(
                {
                    "name": "recommended-stack",
                    "skipped": True,
                    "reason": "Stack install skipped. Rerun with --install-stack to install or guide GBrain, GitNexus, AUTOREVIEW, Clawpatch, and Obsidian.",
                }
            )

        _assert_download_sources_immutable(downloads)
        stack_summary = summarize_external_tools(external_tools)
        for item in stack_summary["items"]:
            state = "OK" if item["installed"] and not item["needs_action"] else "ACTION"
            print(f"  {state} {item['name']}")
            for command in item.get("next_commands", []):
                print(f"    next: {command}")

        if not venv_root.exists():
            venv.EnvBuilder(with_pip=False, clear=False).create(venv_root)
        if app_root.exists():
            shutil.rmtree(app_root)
        shutil.copytree(ROOT / "src", app_root, symlinks=False)
        python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            raise SystemExit(f"Virtual-environment Python is missing: {python}")
        launcher = install_launcher(args.bin_dir.expanduser().resolve(), python, app_root, prefix)
        installed_env = {"PYTHONPATH": str(app_root)}
        version = run([str(python), "-m", "manageroo", "--version"], cwd=prefix, env=installed_env)
        self_test_output = (
            "skipped by release smoke"
            if args.skip_self_test
            else run([str(python), "-m", "manageroo", "self-test"], cwd=prefix, env=installed_env).stdout.strip()
        )

        lock = {
            "product": FULL_NAME,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "source_root": str(ROOT),
            "source_tree_sha256": tree_hash(ROOT),
            "installed_app_sha256": tree_hash(app_root),
            "python": sys.version,
            "platform": platform.platform(),
            "prefix": str(prefix),
            "launcher": str(launcher),
            "manageroo_version_output": version.stdout.strip(),
            "self_test_output": self_test_output,
            "token_mode": token_mode_record,
            "helper_skills": helper_skills_record,
            "external_tools": external_tools,
            "stack_summary": stack_summary,
            "uninstall_plan": uninstall_plan(prefix, args.bin_dir.expanduser().resolve()),
            "network_downloads": downloads,
            "dependency_policy": (
                "Manageroo is the portable controller. Executable or copied third-party sources selected by this installer are pinned by the Manageroo release; operating-system package-manager installs remain explicit operator-selected lanes. GitNexus is first-class recommended repository intelligence in the full stack; GBrain, AUTOREVIEW, Clawpatch, and Obsidian are surrounding lanes. External tools never replace Manageroo completion authority."
            ),
        }
        atomic_write_json(prefix / "install-lock.json", lock)

    status_line("INSTALLED", str(launcher), ok=True)
    if str(args.bin_dir.expanduser().resolve()) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {args.bin_dir.expanduser().resolve()} to PATH, then open a new terminal.")
    if not args.no_music:
        play_once(cue="success", variant=69)
    if choose_stack_doctor_mode(args.stack_doctor) == "run":
        optional_run(
            [str(python), "-m", "manageroo", "stack-doctor"],
            downloads,
            "stack-doctor",
            "manageroo-local-installed-code",
            cwd=Path.home(),
            env=installed_env,
        )
    project_mode = choose_project_discovery_mode(args.project_discovery)
    if project_mode in {"pick", "add"}:
        optional_run(
            [
                str(python),
                "-m",
                "manageroo",
                "projects",
                "--add" if project_mode == "add" else "--pick",
            ],
            downloads,
            "project-discovery",
            "manageroo-local-installed-code",
            cwd=Path.home(),
            env=installed_env,
        )
    print_next_commands()
    print_lane_explainer()
    print("\n" + format_special_thanks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
