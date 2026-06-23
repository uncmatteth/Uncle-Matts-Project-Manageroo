#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "Uncle-Matts-Project-Manageroo"
VERSION_TAG = "v2026.6.22.1"
ARTIFACT_BASENAME = f"uncle-matts-project-manageroo-{VERSION_TAG}"
DROP_ROOT = ARTIFACT_BASENAME
DEFAULT_DROP_DIR = ROOT.parent / DROP_ROOT
INSTALLER_ZIP = f"{ARTIFACT_BASENAME}.zip"
SOURCE_ZIP = f"{ARTIFACT_BASENAME}-source.zip"
OUTPUT = ROOT.parent / INSTALLER_ZIP
SOURCE_OUTPUT = ROOT.parent / SOURCE_ZIP
EXCLUDED_PARTS = {".git", ".venv", ".clawpatch", "__pycache__", "dist", "build"}
CHECKSUM_EXCLUDED = {"SHA256SUMS.txt", "BUILD-VALIDATION.json"}
DROP_CLEANUP_PREFIXES = (
    ARTIFACT_BASENAME,
    "Manageroo-",
    "".join(chr(code) for code in [85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69]) + "-",
)
END_USER_EXCLUDED = {
    "BUILD-VALIDATION.json",
    "GITHUB_DESCRIPTION.md",
    "SHA256SUMS.txt",
    "docs/FILE_MANIFEST.md",
    "scripts/package_release.py",
    "tests/test_package_release.py",
}


def included_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def end_user_files() -> list[Path]:
    return [
        path
        for path in included_files()
        if path.relative_to(ROOT).as_posix() not in END_USER_EXCLUDED
    ]


def purpose(relative: str) -> str:
    if relative.startswith("src/manageroo/assets/schemas/"):
        return "Structured agent-output contract"
    if relative.startswith("src/manageroo/assets/prompts/"):
        return "Role procedure reference"
    if relative.startswith("src/manageroo/"):
        return "Harness runtime source"
    if relative.startswith("tests/"):
        return "Deterministic harness test"
    if relative.startswith("docs/"):
        return "Operator and engineering documentation"
    if relative in {"install.sh", "install.ps1"} or relative.startswith("scripts/"):
        return "Installation, validation, or packaging"
    if relative.startswith(".github/"):
        return "GitHub repository metadata"
    if relative.startswith("examples/"):
        return "Example product input"
    return "Project metadata or handoff"


def generate_manifest() -> None:
    lines = [
        "# File manifest",
        "",
        "This manifest is generated from the release source tree.",
        "",
        "| File | Bytes | Purpose |",
        "|---|---:|---|",
    ]
    for path in included_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in {"docs/FILE_MANIFEST.md", "SHA256SUMS.txt"}:
            continue
        lines.append(f"| `{relative}` | {path.stat().st_size} | {purpose(relative)} |")
    (ROOT / "docs" / "FILE_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive(output: Path, files: list[Path]) -> None:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(
                path,
                arcname=f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}",
            )


def refresh_drop_folder(drop_dir: Path, end_user_archive: Path, source_archive: Path) -> None:
    drop_dir.mkdir(parents=True, exist_ok=True)
    for path in drop_dir.iterdir():
        if path.is_file() and path.name.startswith(DROP_CLEANUP_PREFIXES):
            path.unlink()
    copies = {
        INSTALLER_ZIP: end_user_archive,
        SOURCE_ZIP: source_archive,
        "SOURCE-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "FINAL-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "LOCAL-SETUP.md": ROOT / "LOCAL_SETUP.md",
        "PUBLISH-TO-GITHUB.md": ROOT / "PUBLISH_TO_GITHUB.md",
        "GIVE-THIS-TO-YOUR-IDE-AGENT.md": ROOT / "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
        "GITHUB-DESCRIPTION.md": ROOT / "GITHUB_DESCRIPTION.md",
    }
    for name, source in copies.items():
        shutil.copy2(source, drop_dir / name)
    checksum_lines = []
    for name in copies:
        path = drop_dir / name
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    checksums = "\n".join(checksum_lines) + "\n"
    (drop_dir / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")


def main() -> int:
    result = subprocess.run(
        [sys.executable, "scripts/verify_release.py"],
        cwd=ROOT,
        shell=False,
    )
    if result.returncode:
        return result.returncode

    generate_manifest()
    checksums = []
    for path in included_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in CHECKSUM_EXCLUDED:
            continue
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    write_archive(OUTPUT, end_user_files())
    write_archive(SOURCE_OUTPUT, included_files())
    smoke = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_release_install.py",
            "--archive",
            str(OUTPUT),
            "--skip-install-tests",
        ],
        cwd=ROOT,
        shell=False,
    )
    if smoke.returncode:
        return smoke.returncode
    refresh_drop_folder(DEFAULT_DROP_DIR, OUTPUT, SOURCE_OUTPUT)
    print(OUTPUT)
    print(SOURCE_OUTPUT)
    print(DEFAULT_DROP_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
