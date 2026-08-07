#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
PROJECT = PYPROJECT["project"]
BUILD_REQUIREMENTS_LOCK = ROOT / "build-requirements.lock"
EXPECTED_VERSION = str(PROJECT["version"])
EXPECTED_CORE_SKILLS = 22
EXPECTED_OPTIONAL_SKILLS = 32
EXPECTED_TOTAL_SKILLS = EXPECTED_CORE_SKILLS + EXPECTED_OPTIONAL_SKILLS
BUILD_LOCK_ENTRY = re.compile(
    r"(?P<requirement>[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+) "
    r"--hash=sha256:(?P<digest>[0-9a-f]{64})"
)


def _run(argv: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            json.dumps(
                {
                    "argv": argv,
                    "exit_code": result.returncode,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                },
                indent=2,
            )
        )
    return result


def _locked_build_requirements() -> list[str]:
    declared = list(PYPROJECT["build-system"]["requires"])
    locked: list[str] = []
    for line_number, line in enumerate(
        BUILD_REQUIREMENTS_LOCK.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = BUILD_LOCK_ENTRY.fullmatch(stripped)
        if match is None:
            raise RuntimeError(
                f"Invalid hash-locked build requirement at "
                f"{BUILD_REQUIREMENTS_LOCK.name}:{line_number}"
            )
        locked.append(match.group("requirement"))
    if locked != declared:
        raise RuntimeError(
            "build-system.requires must exactly match the ordered SHA-256 build lock: "
            f"declared={declared!r}, locked={locked!r}"
        )
    return locked


def _download_build_requirements(wheelhouse: Path) -> subprocess.CompletedProcess[str]:
    _locked_build_requirements()
    return _run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "download",
            "--disable-pip-version-check",
            "--require-hashes",
            "--only-binary=:all:",
            "--no-deps",
            "--dest",
            str(wheelhouse),
            "--requirement",
            str(BUILD_REQUIREMENTS_LOCK),
        ],
        cwd=ROOT,
        timeout=600,
    )


def _install_build_requirements(
    python: Path,
    wheelhouse: Path,
    root: Path,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--require-hashes",
            "--no-deps",
            "--requirement",
            str(BUILD_REQUIREMENTS_LOCK),
        ],
        cwd=root,
        timeout=300,
    )


def _build_wheel(python: Path, wheel_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "wheel",
            "--disable-pip-version-check",
            "--no-build-isolation",
            "--no-index",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(ROOT),
        ],
        cwd=ROOT,
        timeout=600,
    )


def _install_wheel(python: Path, wheel: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            str(python),
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            str(wheel),
        ],
        cwd=root,
        timeout=300,
    )


def verify_distribution() -> dict:
    with tempfile.TemporaryDirectory(prefix="manageroo-distribution-proof-") as temp:
        root = Path(temp)
        wheel_dir = root / "wheel"
        wheel_dir.mkdir()
        wheelhouse = root / "build-wheelhouse"
        wheelhouse.mkdir()
        _download_build_requirements(wheelhouse)

        build_venv = root / "build-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(build_venv)
        build_python = build_venv / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        if not build_python.is_file():
            raise RuntimeError(f"Distribution build venv Python is missing: {build_python}")
        _install_build_requirements(build_python, wheelhouse, root)
        build = _build_wheel(build_python, wheel_dir)
        wheels = sorted(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected exactly one built wheel, found: {[path.name for path in wheels]}")
        wheel = wheels[0]

        venv_root = root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
        python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        manageroo = venv_root / ("Scripts/manageroo.exe" if os.name == "nt" else "bin/manageroo")
        if not python.is_file():
            raise RuntimeError(f"Distribution verification venv Python is missing: {python}")

        _install_wheel(python, wheel, root)
        if not manageroo.is_file():
            raise RuntimeError(f"Installed wheel did not create the manageroo console entry point: {manageroo}")

        version = _run([str(manageroo), "--version"], cwd=root).stdout.strip()
        if version != EXPECTED_VERSION:
            raise RuntimeError(
                f"Installed console entry point version mismatch: expected {EXPECTED_VERSION!r}, got {version!r}"
            )
        help_output = _run([str(manageroo), "--help"], cwd=root).stdout
        if "usage: manageroo" not in help_output.casefold():
            raise RuntimeError("Installed manageroo console entry point did not emit expected help output.")

        probe_code = """
import json
from manageroo.assets import asset_path
from manageroo.token_modes import BUNDLED_SKILL_LIBRARY, CORE_SKILL_PACK, OPTIONAL_SKILL_PACK
missing = []
for name, relative in BUNDLED_SKILL_LIBRARY.items():
    path = asset_path(relative)
    if not path.is_file():
        missing.append({"name": name, "path": relative})
print(json.dumps({
    "core": len(CORE_SKILL_PACK),
    "optional": len(OPTIONAL_SKILL_PACK),
    "total": len(BUNDLED_SKILL_LIBRARY),
    "missing": missing,
}, sort_keys=True))
""".strip()
        asset_probe = json.loads(_run([str(python), "-c", probe_code], cwd=root).stdout)
        expected = {
            "core": EXPECTED_CORE_SKILLS,
            "optional": EXPECTED_OPTIONAL_SKILLS,
            "total": EXPECTED_TOTAL_SKILLS,
        }
        for key, value in expected.items():
            if asset_probe.get(key) != value:
                raise RuntimeError(
                    f"Installed wheel skill count mismatch for {key}: expected {value}, got {asset_probe.get(key)}"
                )
        if asset_probe.get("missing"):
            raise RuntimeError(f"Installed wheel is missing bundled skill assets: {asset_probe['missing']}")

        return {
            "ok": True,
            "wheel": wheel.name,
            "version": version,
            "console_entrypoint": str(manageroo),
            "core_skills": asset_probe["core"],
            "optional_skills": asset_probe["optional"],
            "total_skills": asset_probe["total"],
            "build_stdout_tail": build.stdout[-1000:],
        }


def main() -> int:
    try:
        result = verify_distribution()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
