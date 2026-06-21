#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from umsmfburasbofe.branding import FULL_NAME, print_banner, status_line  # noqa: E402
from umsmfburasbofe.chiptune import ThemePlayback, play_once  # noqa: E402
from umsmfburasbofe.install_status import summarize_external_tools, uninstall_plan  # noqa: E402
from umsmfburasbofe.token_modes import set_token_mode  # noqa: E402

CODEX_INSTALL_URL = "https://chatgpt.com/codex/install.sh"
GBRAIN_INSTALL_SOURCE = "github:garrytan/gbrain"
GITNEXUS_NPM_PACKAGE = "gitnexus"
LOOP_LIBRARY_SKILL_SOURCE = "Forward-Future/loop-library"
OBSIDIAN_HELP_URL = "https://obsidian.md/help/install"
OPENCLAW_AGENT_SKILLS_REPO = "https://github.com/openclaw/agent-skills.git"
AUTOREVIEW_SKILL_SOURCE = "openclaw/agent-skills:skills/autoreview"
CLAWPATCH_PACKAGE = "clawpatch"


def run(
    argv: list[str],
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    *,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    status_line("RUN", " ".join(argv))
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
    digest = hashlib.sha256()
    excluded = {".git", ".venv", "__pycache__", "dist", "build"}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(part in excluded for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
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


def install_launcher(bin_dir: Path, python: Path, app_root: Path, prefix: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        launcher = bin_dir / "umsmfburasbofe.cmd"
        launcher.write_text(
            f'@set "PYTHONPATH={app_root}"\r\n'
            f'@set "UMSMFBURASBOFE_PREFIX={prefix}"\r\n'
            f'@"{python}" -m umsmfburasbofe %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / "umsmfburasbofe"
        launcher.write_text(
            "#!/bin/sh\n"
            f'export PYTHONPATH="{app_root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
            f'export UMSMFBURASBOFE_PREFIX="{prefix}"\n'
            f'exec "{python}" -m umsmfburasbofe "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return launcher


def install_codex_latest(downloads: list[dict]) -> dict:
    before = command_version("codex")
    status_line("CODEX", f"current: {before}")

    if os.name == "nt":
        npm = shutil.which("npm")
        if not npm:
            winget = shutil.which("winget")
            if not winget:
                raise SystemExit(
                    "Codex is not installed and neither npm nor winget is available. "
                    "Install Node.js LTS, then rerun."
                )
            run(
                [
                    winget,
                    "install",
                    "--id",
                    "OpenJS.NodeJS.LTS",
                    "-e",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
                capture=False,
            )
            common_npm = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd"
            npm = shutil.which("npm") or (str(common_npm) if common_npm.exists() else None)
        if not npm:
            raise SystemExit("Node.js installation completed, but npm could not be located.")
        run([npm, "install", "-g", "@openai/codex@latest"], capture=False)
        downloads.append(
            {
                "tool": "codex",
                "method": "npm",
                "source": "@openai/codex@latest",
                "previous_version": before,
            }
        )
    else:
        with tempfile.TemporaryDirectory(prefix="umsmfburasbofe-codex-") as temp:
            installer = Path(temp) / "codex-install.sh"
            request = urllib.request.Request(
                CODEX_INSTALL_URL,
                headers={"User-Agent": f"{FULL_NAME} installer"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = response.read()
            except Exception as exc:
                raise SystemExit(f"Unable to download the official Codex installer: {exc}") from exc
            if not payload.startswith(b"#!"):
                raise SystemExit("The Codex installer response was not a shell script; refusing to execute it.")
            installer.write_bytes(payload)
            installer.chmod(0o700)
            digest = hashlib.sha256(payload).hexdigest()
            status_line("CODEX", f"official installer sha256={digest[:16]}…")
            run(
                ["sh", str(installer)],
                env={"CODEX_NON_INTERACTIVE": "1"},
                capture=False,
            )
            downloads.append(
                {
                    "tool": "codex",
                    "method": "official-standalone-installer",
                    "source": CODEX_INSTALL_URL,
                    "sha256": digest,
                    "previous_version": before,
                }
            )

    candidate_dirs = [
        Path.home() / ".local" / "bin",
        Path.home() / ".codex" / "bin",
        Path.home() / "bin",
    ]
    if os.name == "nt" and os.environ.get("APPDATA"):
        candidate_dirs.insert(0, Path(os.environ["APPDATA"]) / "npm")
    os.environ["PATH"] = os.pathsep.join(
        [*(str(item) for item in candidate_dirs), os.environ.get("PATH", "")]
    )
    after = command_version("codex")
    status_line("CODEX", after, ok=after != "not installed")
    return {"path": shutil.which("codex"), "version": after}


def optional_run(
    argv: list[str], downloads: list[dict], tool: str, source: str, cwd: Path = ROOT
) -> dict:
    try:
        run(argv, cwd=cwd, capture=False)
    except SystemExit as exc:
        return {
            "ok": False,
            "argv": argv,
            "source": source,
            "cwd": str(cwd),
            "error": f"exit {exc.code}",
        }
    downloads.append({"tool": tool, "method": argv[0], "source": source, "argv": argv, "cwd": str(cwd)})
    return {"ok": True, "argv": argv, "source": source}


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


def backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.umsmfburasbofe-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.umsmfburasbofe-backup-{stamp}-{index}")
        index += 1
    return candidate


def symlink_violations(root: Path) -> list[str]:
    return [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_symlink()
    ]


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


def install_gbrain(downloads: list[dict]) -> dict:
    cwd = Path.home()
    before = command_version("gbrain")
    status_line("GBRAIN", f"current: {before}")
    installed = before != "not installed"
    install_result: dict | None = None
    if not installed:
        bun = shutil.which("bun")
        if not bun:
            return guidance(
                "gbrain",
                "Bun is required before GBrain can be installed by this installer.",
                [
                    "Install Bun from https://bun.sh/",
                    f"bun install -g {GBRAIN_INSTALL_SOURCE}",
                    "gbrain init --pglite",
                    "gbrain doctor",
                ],
                "https://github.com/garrytan/gbrain/blob/master/docs/INSTALL.md",
            )
        install_result = optional_run(
            [bun, "install", "-g", GBRAIN_INSTALL_SOURCE],
            downloads,
            "gbrain",
            GBRAIN_INSTALL_SOURCE,
            cwd=cwd,
        )
        installed = install_result["ok"]
        prepend_tool_paths()
    gbrain = shutil.which("gbrain")
    init_result = None
    scaffold_result = None
    doctor_result = None
    if gbrain:
        init_result = optional_run(
            [gbrain, "init", "--pglite"], downloads, "gbrain", "gbrain init --pglite", cwd=cwd
        )
        scaffold_result = optional_run(
            [gbrain, "skillpack", "scaffold", "--all"],
            downloads,
            "gbrain",
            "gbrain skillpack scaffold --all",
            cwd=cwd,
        )
        doctor_result = optional_run([gbrain, "doctor"], downloads, "gbrain", "gbrain doctor", cwd=cwd)
    after = command_version("gbrain")
    status_line("GBRAIN", after, ok=after != "not installed")
    return {
        "name": "gbrain",
        "installed": after != "not installed",
        "configured": bool(init_result and init_result["ok"]),
        "version": after,
        "path": shutil.which("gbrain"),
        "install_result": install_result,
        "init_result": init_result,
        "scaffold_result": scaffold_result,
        "doctor_result": doctor_result,
        "next_commands": [
            "gbrain doctor",
            "Connect `gbrain serve` to the MCP settings for the AI IDE or CLI agent you selected.",
        ],
        "reference": "https://github.com/garrytan/gbrain/blob/master/docs/INSTALL.md",
    }


def install_gitnexus(downloads: list[dict]) -> dict:
    cwd = Path.home()
    before = command_version("gitnexus")
    status_line("GITNEXUS", f"current: {before}")
    install_result: dict | None = None
    if before == "not installed":
        npm = shutil.which("npm")
        if not npm:
            return guidance(
                "gitnexus",
                "Node.js/npm is required before GitNexus can be installed.",
                [
                    "Install Node.js 18+ from https://nodejs.org/",
                    f"npm install -g {GITNEXUS_NPM_PACKAGE}",
                    "gitnexus setup",
                ],
                "https://github.com/abhigyanpatwari/GitNexus",
            )
        install_result = optional_run(
            [npm, "install", "-g", GITNEXUS_NPM_PACKAGE],
            downloads,
            "gitnexus",
            GITNEXUS_NPM_PACKAGE,
            cwd=cwd,
        )
        prepend_tool_paths()
    after = command_version("gitnexus")
    status_line("GITNEXUS", after, ok=after != "not installed")
    return {
        "name": "gitnexus",
        "installed": after != "not installed",
        "configured": False,
        "version": after,
        "path": shutil.which("gitnexus"),
        "install_result": install_result,
        "next_commands": ["gitnexus setup"],
        "reference": "https://github.com/abhigyanpatwari/GitNexus",
    }


def install_autoreview(downloads: list[dict], prefix: Path) -> dict:
    destination = Path.home() / ".agents" / "skills" / "autoreview"
    script = destination / "scripts" / "autoreview"
    if script.exists():
        status_line("AUTOREVIEW", str(script), ok=True)
        return {
            "name": "autoreview",
            "installed": True,
            "configured": True,
            "path": str(script),
            "reference": "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
        }

    git = shutil.which("git")
    if not git:
        return guidance(
            "autoreview",
            "Git is required to install the OpenClaw AUTOREVIEW skill.",
            [
                "git clone https://github.com/openclaw/agent-skills.git",
                "mkdir -p ~/.agents/skills",
                "cp -R agent-skills/skills/autoreview ~/.agents/skills/autoreview",
            ],
            "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
        )

    vendor = prefix / "vendors" / "openclaw-agent-skills"
    if vendor.exists():
        shutil.rmtree(vendor)
    vendor.parent.mkdir(parents=True, exist_ok=True)
    clone_result = optional_run(
        [git, "clone", "--depth", "1", OPENCLAW_AGENT_SKILLS_REPO, str(vendor)],
        downloads,
        "autoreview",
        OPENCLAW_AGENT_SKILLS_REPO,
        cwd=vendor.parent,
    )
    source = vendor / "skills" / "autoreview"
    if not clone_result["ok"] or not source.exists():
        return {
            "name": "autoreview",
            "installed": False,
            "configured": False,
            "install_result": clone_result,
            "next_commands": [
                "git clone https://github.com/openclaw/agent-skills.git",
                "mkdir -p ~/.agents/skills",
                "cp -R agent-skills/skills/autoreview ~/.agents/skills/autoreview",
            ],
            "reference": "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
        }
    links = symlink_violations(source)
    if links:
        return {
            "name": "autoreview",
            "installed": False,
            "configured": False,
            "install_result": clone_result,
            "error": "Downloaded AUTOREVIEW skill contains symlinks; refusing to copy it.",
            "symlinks": links,
            "reference": "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
        }
    backup = None
    if destination.exists():
        backup = backup_path(destination)
        shutil.move(str(destination), str(backup))
    shutil.copytree(source, destination)
    status_line("AUTOREVIEW", str(script), ok=script.exists())
    return {
        "name": "autoreview",
        "installed": script.exists(),
        "configured": script.exists(),
        "path": str(script),
        "backup": str(backup) if backup else None,
        "install_result": clone_result,
        "next_commands": [f'export AUTOREVIEW="{script}"', '"$AUTOREVIEW" --mode local'],
        "reference": "https://github.com/openclaw/agent-skills/tree/main/skills/autoreview",
    }


def ensure_pnpm(downloads: list[dict]) -> str | None:
    pnpm = shutil.which("pnpm")
    npm = shutil.which("npm")
    if not pnpm and not npm:
        return None
    if not pnpm and npm:
        result = optional_run([npm, "install", "-g", "pnpm"], downloads, "pnpm", "pnpm", cwd=Path.home())
        if not result["ok"]:
            return None
        prepend_tool_paths()
        pnpm = shutil.which("pnpm")
    if not pnpm:
        return None
    pnpm_home = Path(os.environ.get("PNPM_HOME") or (Path.home() / ".local" / "share" / "pnpm"))
    pnpm_home.mkdir(parents=True, exist_ok=True)
    os.environ["PNPM_HOME"] = str(pnpm_home)
    prepend_tool_paths()
    setup_result = optional_run(
        [pnpm, "config", "set", "global-bin-dir", str(pnpm_home)],
        downloads,
        "pnpm",
        "pnpm global-bin-dir",
        cwd=Path.home(),
    )
    return pnpm if setup_result["ok"] else None


def install_clawpatch(downloads: list[dict]) -> dict:
    before = command_version("clawpatch")
    status_line("CLAWPATCH", f"current: {before}")
    if before != "not installed":
        return {
            "name": "clawpatch",
            "installed": True,
            "configured": True,
            "version": before,
            "path": shutil.which("clawpatch"),
            "reference": "https://github.com/openclaw/clawpatch",
        }
    pnpm = ensure_pnpm(downloads)
    if not pnpm:
        return guidance(
            "clawpatch",
            "pnpm is required before Clawpatch can be installed.",
            [
                "npm install -g pnpm",
                "pnpm setup",
                "pnpm add -g clawpatch",
                "clawpatch doctor",
            ],
            "https://github.com/openclaw/clawpatch",
        )
    install_result = optional_run(
        [pnpm, "add", "-g", CLAWPATCH_PACKAGE],
        downloads,
        "clawpatch",
        CLAWPATCH_PACKAGE,
        cwd=Path.home(),
    )
    prepend_tool_paths()
    after = command_version("clawpatch")
    doctor_result = None
    clawpatch = shutil.which("clawpatch")
    if clawpatch:
        doctor_result = optional_run(
            [clawpatch, "doctor"], downloads, "clawpatch", "clawpatch doctor", cwd=Path.home()
        )
    status_line("CLAWPATCH", after, ok=after != "not installed")
    return {
        "name": "clawpatch",
        "installed": after != "not installed",
        "configured": bool(doctor_result and doctor_result["ok"]),
        "version": after,
        "path": shutil.which("clawpatch"),
        "install_result": install_result,
        "doctor_result": doctor_result,
        "next_commands": ["clawpatch init", "clawpatch map", "clawpatch review --limit 3 --jobs 3"],
        "reference": "https://github.com/openclaw/clawpatch",
    }


def install_loop_library(downloads: list[dict], agents: list[str]) -> dict:
    npx = shutil.which("npx")
    if not npx:
        return guidance(
            "loop-library",
            "Node.js/npx is required before the Loop Library skill can be installed.",
            [
                "Install Node.js 18+ from https://nodejs.org/",
                "npx --yes skills add Forward-Future/loop-library --skill loop-library -g",
            ],
            "https://github.com/Forward-Future/loop-library",
        )
    selected_agents = agents
    if not selected_agents and sys.stdin.isatty():
        print("Loop Library skill target:")
        print("  1) skip")
        print("  2) codex")
        print("  3) cursor")
        print("  4) claude-code")
        answer = input("Choose target [1]: ").strip().lower()
        selected_agents = {
            "2": ["codex"],
            "codex": ["codex"],
            "3": ["cursor"],
            "cursor": ["cursor"],
            "4": ["claude-code"],
            "claude": ["claude-code"],
            "claude-code": ["claude-code"],
        }.get(answer, [])
    if selected_agents:
        argv = [npx, "--yes", "skills", "add", LOOP_LIBRARY_SKILL_SOURCE, "--skill", "loop-library"]
        for agent in selected_agents:
            argv.extend(["--agent", agent])
        argv.extend(["-g", "-y"])
    else:
        return guidance(
            "loop-library",
            "No Loop Library agent target was selected.",
            [
                "npx --yes skills add Forward-Future/loop-library --skill loop-library --agent YOUR_AGENT -g -y",
                "npx --yes skills add Forward-Future/loop-library --skill loop-library -g",
            ],
            "https://github.com/Forward-Future/loop-library",
        )
    result = optional_run(argv, downloads, "loop-library", LOOP_LIBRARY_SKILL_SOURCE, cwd=Path.home())
    return {
        "name": "loop-library",
        "installed": result["ok"],
        "configured": result["ok"],
        "install_result": result,
        "agents": selected_agents or ["interactive"],
        "reference": "https://signals.forwardfuture.ai/loop-library/",
    }


def install_obsidian(downloads: list[dict], method: str) -> dict:
    before = command_version("obsidian")
    status_line("OBSIDIAN", f"current: {before}")
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
    candidates: list[tuple[str, list[str]]] = []
    if method in {"auto", "winget"} and system == "windows" and shutil.which("winget"):
        candidates.append(
            (
                "winget",
                [
                    shutil.which("winget") or "winget",
                    "install",
                    "--id",
                    "Obsidian.Obsidian",
                    "-e",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ],
            )
        )
    if method in {"auto", "brew"} and system == "darwin" and shutil.which("brew"):
        candidates.append(("brew", [shutil.which("brew") or "brew", "install", "--cask", "obsidian"]))
    if method in {"auto", "flatpak"} and system == "linux" and shutil.which("flatpak"):
        candidates.append(
            (
                "flatpak",
                [
                    shutil.which("flatpak") or "flatpak",
                    "install",
                    "--user",
                    "-y",
                    "flathub",
                    "md.obsidian.Obsidian",
                ],
            )
        )
    if (
        method in {"auto", "snap"}
        and system == "linux"
        and shutil.which("snap")
        and hasattr(os, "geteuid")
        and os.geteuid() == 0
    ):
        candidates.append(("snap", [shutil.which("snap") or "snap", "install", "obsidian", "--classic"]))

    for installer, argv in candidates[:1]:
        result = optional_run(argv, downloads, "obsidian", installer, cwd=Path.home())
        after = command_version("obsidian")
        return {
            "name": "obsidian",
            "installed": after != "not installed" or result["ok"],
            "configured": after != "not installed" or result["ok"],
            "version": after,
            "path": shutil.which("obsidian"),
            "install_result": result,
            "reference": OBSIDIAN_HELP_URL,
        }

    commands = []
    if system == "linux":
        commands = [
            "flatpak install --user flathub md.obsidian.Obsidian",
            "sudo snap install obsidian --classic",
            "or download the AppImage from https://obsidian.md/download",
        ]
    elif system == "darwin":
        commands = ["brew install --cask obsidian", "or download from https://obsidian.md/download"]
    elif system == "windows":
        commands = ["winget install --id Obsidian.Obsidian -e", "or download from https://obsidian.md/download"]
    return guidance("obsidian", "No supported Obsidian installer was available automatically.", commands, OBSIDIAN_HELP_URL)


def choose_stack_mode(selection: str, install_flag: bool, skip_flag: bool) -> str:
    if install_flag:
        return "install"
    if skip_flag:
        return "skip"
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "skip"
    print("Recommended local stack:")
    print("  - GBrain memory")
    print("  - GitNexus code graph")
    print("  - AUTOREVIEW review helper")
    print("  - Clawpatch review and fix loop")
    print("  - Obsidian notes")
    print("  - Matthew Berman / Forward Future Loop Library skill")
    answer = input("Install and guide this stack now? [Y/n]: ").strip().lower()
    return "skip" if answer in {"n", "no", "skip"} else "install"


def install_recommended_stack(
    downloads: list[dict], agents: list[str], obsidian_method: str, prefix: Path
) -> list[dict]:
    status_line("STACK", "installing recommended local stack")
    return [
        install_gbrain(downloads),
        install_gitnexus(downloads),
        install_autoreview(downloads, prefix),
        install_clawpatch(downloads),
        install_loop_library(downloads, agents),
        install_obsidian(downloads, obsidian_method),
    ]


def choose_token_mode(selection: str) -> str:
    if selection != "ask":
        return selection
    if not sys.stdin.isatty():
        return "off"
    print("Token reduction mode:")
    print("  1) off")
    print("  2) caveman - terse, clean, fewer tokens")
    print("  3) curse - Uncle Matt's Caveman Curse, terse plus profanity")
    answer = input("Choose 1, 2, or 3 [1]: ").strip().lower()
    return {
        "": "off",
        "1": "off",
        "off": "off",
        "none": "off",
        "2": "caveman",
        "caveman": "caveman",
        "3": "curse",
        "curse": "curse",
        "uncle": "curse",
        "uncle-matts-caveman-curse": "curse",
    }.get(answer, "off")


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Install {FULL_NAME}")
    parser.add_argument(
        "--prefix",
        type=Path,
        default=Path.home() / ".local" / "share" / "umsmfburasbofe",
    )
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=Path.home() / ".local" / "bin",
    )
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-codex", action="store_true")
    parser.add_argument("--skip-codex", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stack", choices=["ask", "skip", "install"], default="ask")
    parser.add_argument("--install-stack", action="store_true")
    parser.add_argument("--skip-stack", action="store_true")
    parser.add_argument(
        "--loop-library-agent",
        action="append",
        default=[],
        help="Agent target for the optional Loop Library skill, such as codex, cursor, claude-code, gemini, or another skills-compatible agent.",
    )
    parser.add_argument(
        "--obsidian-method",
        choices=["auto", "guide", "flatpak", "snap", "brew", "winget"],
        default="auto",
    )
    parser.add_argument("--token-mode", choices=["ask", "off", "caveman", "curse"], default="ask")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args()
    if args.install_stack and args.skip_stack:
        raise SystemExit("--install-stack and --skip-stack conflict. Choose one.")
    if args.install_stack and args.stack == "skip":
        raise SystemExit("--install-stack conflicts with --stack skip.")
    if args.skip_stack and args.stack == "install":
        raise SystemExit("--skip-stack conflicts with --stack install.")

    print_banner(animation=not args.no_animation)
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
        token_mode_record = set_token_mode(token_mode, install_skills=token_mode != "off")
        status_line("TOKEN MODE", token_mode_record["label"], ok=True)

        source_env = {"PYTHONPATH": str(ROOT / "src")}
        if not args.skip_tests:
            status_line("VERIFY", "compiling source")
            run([sys.executable, "-m", "compileall", "-q", "src"], env=source_env)
            status_line("VERIFY", "running deterministic tests")
            run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                env=source_env,
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
                    "reason": "Codex is an adapter choice, not a core installer requirement.",
                }
            )

        stack_mode = choose_stack_mode(args.stack, args.install_stack, args.skip_stack)
        if stack_mode == "install":
            external_tools.extend(
                install_recommended_stack(downloads, args.loop_library_agent, args.obsidian_method, prefix)
            )
        else:
            external_tools.append(
                {
                    "name": "recommended-stack",
                    "skipped": True,
                    "reason": "Stack install was skipped. Rerun with --install-stack to install or guide GBrain, GitNexus, AUTOREVIEW, Clawpatch, Obsidian, and Loop Library.",
                }
            )

        stack_summary = summarize_external_tools(external_tools)
        status_line("STACK", f"{stack_summary['counts']['needs_action']} item(s) need follow-up")
        for item in stack_summary["items"]:
            state = "OK" if item["installed"] and not item["needs_action"] else "ACTION"
            print(f"  {state} {item['name']}")
            if item.get("reason"):
                print(f"    {item['reason']}")
            for command in item.get("next_commands", []):
                print(f"    next: {command}")

        if not venv_root.exists():
            status_line("INSTALL", f"creating isolated runtime at {venv_root}")
            venv.EnvBuilder(with_pip=False, clear=False).create(venv_root)

        if app_root.exists():
            shutil.rmtree(app_root)
        shutil.copytree(ROOT / "src", app_root)

        python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            raise SystemExit(f"Virtual-environment Python is missing: {python}")
        launcher = install_launcher(args.bin_dir.expanduser().resolve(), python, app_root, prefix)

        installed_env = {"PYTHONPATH": str(app_root)}
        version = run([str(python), "-m", "umsmfburasbofe", "--version"], cwd=prefix, env=installed_env)
        if args.skip_self_test:
            self_test_output = "skipped by release smoke"
        else:
            self_test = run([str(python), "-m", "umsmfburasbofe", "self-test"], cwd=prefix, env=installed_env)
            self_test_output = self_test.stdout.strip()

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
            "umsmfburasbofe_version_output": version.stdout.strip(),
            "self_test_output": self_test_output,
            "token_mode": token_mode_record,
            "external_tools": external_tools,
            "stack_summary": stack_summary,
            "uninstall_plan": uninstall_plan(prefix, args.bin_dir.expanduser().resolve()),
            "network_downloads": downloads,
            "dependency_policy": (
                "Core install is UMSMFBURASBOFE. Real runs require a configured agent "
                "adapter, a Git-backed target repo, and deterministic verification gates. "
                "The guided local stack includes GBrain, GitNexus, AUTOREVIEW, Clawpatch, "
                "Obsidian, and Loop Library when configured."
            ),
        }
        (prefix / "install-lock.json").write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    status_line("INSTALLED", str(launcher), ok=True)
    status_line("LOCKFILE", str(prefix / "install-lock.json"), ok=True)
    if str(args.bin_dir.expanduser().resolve()) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Add {args.bin_dir.expanduser().resolve()} to PATH, then open a new terminal.")
    if not args.no_music:
        play_once(cue="success", variant=69)
    print("\nNext commands:")
    print("  umsmfburasbofe --version")
    print("  umsmfburasbofe self-test")
    print("  umsmfburasbofe stack-status")
    print("  cd /path/to/project && umsmfburasbofe init --agent codex && umsmfburasbofe doctor")
    print("  AI IDEs can use the same command and repo-local skill; no vendor-specific build is needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
