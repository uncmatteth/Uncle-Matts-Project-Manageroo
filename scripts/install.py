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

CODEX_INSTALL_URL = "https://chatgpt.com/codex/install.sh"


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


def install_launcher(bin_dir: Path, python: Path, app_root: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        launcher = bin_dir / "umsmfburasbofe.cmd"
        launcher.write_text(
            f'@set "PYTHONPATH={app_root}"\r\n@"{python}" -m umsmfburasbofe %*\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / "umsmfburasbofe"
        launcher.write_text(
            "#!/bin/sh\n"
            f'export PYTHONPATH="{app_root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
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
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--no-animation", action="store_true")
    args = parser.parse_args()

    print_banner(animation=not args.no_animation)
    print(f"Installing {FULL_NAME}\n")

    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    if shutil.which("git") is None:
        raise SystemExit("Git is required.")

    downloads: list[dict] = []
    external_tools: list[dict] = []
    with ThemePlayback(cue="install", enabled=not args.no_music, variant=69):
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

        prefix = args.prefix.expanduser().resolve()
        venv_root = prefix / "venv"
        app_root = prefix / "app"
        prefix.mkdir(parents=True, exist_ok=True)
        if not venv_root.exists():
            status_line("INSTALL", f"creating isolated runtime at {venv_root}")
            venv.EnvBuilder(with_pip=False, clear=False).create(venv_root)

        if app_root.exists():
            shutil.rmtree(app_root)
        shutil.copytree(ROOT / "src", app_root)

        python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            raise SystemExit(f"Virtual-environment Python is missing: {python}")
        launcher = install_launcher(args.bin_dir.expanduser().resolve(), python, app_root)

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
            "external_tools": external_tools,
            "network_downloads": downloads,
            "dependency_policy": (
                "Core install is UMSMFBURASBOFE. Real runs require a configured agent "
                "adapter, a Git-backed target repo, and deterministic verification gates. "
                "The intended local stack includes GBrain, GitNexus, Obsidian, AUTOREVIEW, "
                "and Clawpatch when configured."
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
    print("  cd /path/to/project && umsmfburasbofe init --agent codex && umsmfburasbofe doctor")
    print("  AI IDEs can use the same command and repo-local skill; no vendor-specific build is needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
