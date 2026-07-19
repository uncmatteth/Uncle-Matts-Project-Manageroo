#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION_TAG = "v2026.7.19.1"
ARCHIVE_NAME = f"uncle-matts-project-manageroo-{VERSION_TAG}.zip"
ARCHIVE_ROOT = "Uncle-Matts-Project-Manageroo"
EXPECTED_SKILL_COUNT = 17


def run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        shell=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "argv": argv,
                    "cwd": str(cwd),
                    "exit_code": result.returncode,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                },
                indent=2,
            )
        )
    return result


def parse_json_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> dict[str, Any]:
    result = run(argv, cwd=cwd, env=env, timeout=timeout)
    return json.loads(result.stdout)


def default_archive() -> Path:
    candidates = [
        ROOT.parent / ARCHIVE_NAME,
        ROOT / ARCHIVE_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def installer_command(extracted: Path, home: Path, *, skip_install_tests: bool) -> list[str]:
    prefix = home / ".local" / "share" / "manageroo"
    bin_dir = home / ".local" / "bin"
    if os.name == "nt":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("PowerShell is required for the Windows release smoke test.")
        argv = [
            powershell,
            "-NoProfile",
            "-File",
            str(extracted / "install.ps1"),
            "-Prefix",
            str(prefix),
            "-BinDir",
            str(bin_dir),
            "-Stack",
            "skip",
            "-GBrainLane",
            "skip",
            "-ClawpatchCodexLogin",
            "skip",
            "-TokenMode",
            "off",
            "-ProjectDiscovery",
            "skip",
            "-StackDoctor",
            "skip",
            "-SkillPack",
            "install",
            "-NoMusic",
            "-NoAnimation",
        ]
        if skip_install_tests:
            argv.append("-SkipTests")
        return argv

    argv = [
        "sh",
        "install.sh",
        "--prefix",
        str(prefix),
        "--bin-dir",
        str(bin_dir),
        "--stack",
        "skip",
        "--gbrain-lane",
        "skip",
        "--clawpatch-codex-login",
        "skip",
        "--token-mode",
        "off",
        "--project-discovery",
        "skip",
        "--stack-doctor",
        "skip",
        "--skill-pack",
        "install",
        "--no-music",
        "--no-animation",
    ]
    if skip_install_tests:
        argv.append("--skip-tests")
    return argv


def smoke(
    archive: Path,
    *,
    keep_temp: bool = False,
    skip_install_tests: bool = False,
) -> dict[str, Any]:
    archive = archive.expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"Release ZIP does not exist: {archive}")

    temp_root = Path(tempfile.mkdtemp(prefix="manageroo-release-smoke-"))
    try:
        home = temp_root / "home"
        work = temp_root / "work"
        home.mkdir()
        work.mkdir()
        with zipfile.ZipFile(archive) as release:
            release.extractall(work)
        extracted = work / ARCHIVE_ROOT
        if not extracted.is_dir():
            raise RuntimeError(f"Archive did not contain {ARCHIVE_ROOT}/")

        env = os.environ.copy()
        env["HOME"] = str(home)
        if os.name == "nt":
            env["USERPROFILE"] = str(home)
        env["PATH"] = f"{home / '.local' / 'bin'}{os.pathsep}{env.get('PATH', '')}"

        install_args = installer_command(
            extracted,
            home,
            skip_install_tests=skip_install_tests,
        )
        install = run(install_args, cwd=extracted, env=env, timeout=240)

        version = run(["manageroo", "--version"], cwd=extracted, env=env).stdout.strip()
        self_test = parse_json_command(["manageroo", "self-test"], cwd=extracted, env=env)
        if self_test.get("ok") is not True or self_test.get("status") != "COMPLETE":
            raise RuntimeError(f"self-test did not complete: {self_test}")

        skills = parse_json_command(["manageroo", "skills", "list"], cwd=extracted, env=env)
        bundled = skills.get("bundled_skills", [])
        if len(bundled) != EXPECTED_SKILL_COUNT or len(bundled) != len(set(bundled)):
            raise RuntimeError(f"Unexpected core skill list: {bundled}")
        support_files = [
            home / ".agents" / "skills" / "grill-with-docs" / "ADR-FORMAT.md",
        ]
        missing_support = [str(path) for path in support_files if not path.is_file()]
        if missing_support:
            raise RuntimeError(f"Missing installed core skill support files: {missing_support}")

        host_skills = parse_json_command(
            ["manageroo", "host-skills", "--json"],
            cwd=extracted,
            env=env,
        )
        if host_skills.get("manageroo_core_missing"):
            raise RuntimeError(f"Installed core not visible to host inventory: {host_skills}")

        capacity = parse_json_command(
            ["manageroo", "capacity", "--json"],
            cwd=extracted,
            env=env,
        )
        core_capacity = capacity.get("manageroo_core", {})
        if core_capacity.get("hardware_agnostic") is not True:
            raise RuntimeError(f"Capacity report lost hardware-agnostic contract: {capacity}")
        if core_capacity.get("auto_tunes_worker_concurrency_from_hardware") is not False:
            raise RuntimeError(f"Capacity report unexpectedly auto-tunes concurrency: {capacity}")

        reconcile_target = temp_root / "reconciled-skills"
        reconcile = parse_json_command(
            [
                "manageroo",
                "skills",
                "reconcile",
                "--skills-dir",
                str(reconcile_target),
                "--apply",
                "--no-default-roots",
                "--json",
            ],
            cwd=extracted,
            env=env,
        )
        if reconcile.get("missing_bundled") or reconcile.get("duplicate_count"):
            raise RuntimeError(f"Skill reconcile failed proof: {reconcile}")

        product = temp_root / "product"
        solo = parse_json_command(
            [
                "manageroo",
                "solo",
                str(product),
                "--create",
                "--starter",
                "static-site",
                "--agent",
                "mock",
                "--want",
                "make the homepage say hello from clean install",
                "--outcome",
                "static site initialized and ready to run",
                "--proof",
                "manageroo mock run passes",
                "--mode",
                "build",
                "--token-mode",
                "off",
                "--no-apply",
                "--json",
            ],
            cwd=extracted,
            env=env,
        )
        if solo.get("ok") is not True:
            raise RuntimeError(f"Solo first-run setup failed: {solo}")

        ready = parse_json_command(
            ["manageroo", "ready", str(product), "--json"],
            cwd=extracted,
            env=env,
        )
        if ready.get("ok") is not True:
            raise RuntimeError(f"Initialized project is not ready: {ready}")

        run_result = parse_json_command(
            [
                "manageroo",
                "run",
                "--repo",
                str(product),
                "--brief",
                str(product / ".manageroo" / "PRODUCT-BRIEF.md"),
                "--mode",
                "build",
                "--no-apply",
            ],
            cwd=product,
            env=env,
            timeout=180,
        )
        if run_result.get("status") != "COMPLETE":
            raise RuntimeError(f"Mock product run did not complete: {run_result}")

        return {
            "ok": True,
            "archive": str(archive),
            "version": version,
            "platform": sys.platform,
            "installer": Path(install_args[0]).name,
            "temp_root": str(temp_root) if keep_temp else "",
            "temp_root_retained": keep_temp,
            "install_stdout_tail": install.stdout[-2000:],
            "self_test_run_id": self_test.get("run_id"),
            "skill_count": len(bundled),
            "hardware_agnostic": core_capacity.get("hardware_agnostic"),
            "reconcile_duplicate_count": reconcile.get("duplicate_count"),
            "product_repo": str(product),
            "product_run_id": run_result.get("run_id"),
            "product_status": run_result.get("status"),
        }
    finally:
        if not keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test the end-user release ZIP in a clean temporary HOME."
    )
    parser.add_argument("--archive", type=Path, default=default_archive())
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument(
        "--skip-install-tests",
        action="store_true",
        help="Skip the installer's internal test suite; useful after package_release already ran it.",
    )
    args = parser.parse_args()
    try:
        result = smoke(
            args.archive,
            keep_temp=args.keep_temp,
            skip_install_tests=args.skip_install_tests,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
