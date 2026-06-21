#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition-final.zip"
ARCHIVE_ROOT = "Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition"
DEFAULT_DROP_DIR = ROOT.parent / ARCHIVE_ROOT
END_USER_ZIP = "UMSMFBURASBOFE-End-User-Release-v2026.6.20.1.zip"
SOURCE_ZIP = "UMSMFBURASBOFE-GitHub-Source-v2026.6.20.1.zip"
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "dist", "build"}
CHECKSUM_EXCLUDED = {"SHA256SUMS.txt", "BUILD-VALIDATION.json"}


def included_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
    )


def purpose(relative: str) -> str:
    if relative.startswith("src/umsmfburasbofe/assets/schemas/"):
        return "Structured agent-output contract"
    if relative.startswith("src/umsmfburasbofe/assets/prompts/"):
        return "Role procedure reference"
    if relative.startswith("src/umsmfburasbofe/"):
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


def write_archive(output: Path) -> None:
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in included_files():
            archive.write(
                path,
                arcname=f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}",
            )


def refresh_drop_folder(drop_dir: Path, archive: Path) -> None:
    drop_dir.mkdir(parents=True, exist_ok=True)
    copies = {
        END_USER_ZIP: archive,
        SOURCE_ZIP: archive,
        "UMSMFBURASBOFE-SOURCE-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "UMSMFBURASBOFE-FINAL-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "UMSMFBURASBOFE-LOCAL-SETUP.md": ROOT / "LOCAL_SETUP.md",
        "UMSMFBURASBOFE-PUBLISH-TO-GITHUB.md": ROOT / "PUBLISH_TO_GITHUB.md",
        "UMSMFBURASBOFE-GIVE-THIS-TO-YOUR-IDE-AGENT.md": ROOT / "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
        "UMSMFBURASBOFE-GITHUB-DESCRIPTION.md": ROOT / "GITHUB_DESCRIPTION.md",
    }
    for name, source in copies.items():
        shutil.copy2(source, drop_dir / name)
    checksum_lines = []
    for name in copies:
        path = drop_dir / name
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}")
    checksums = "\n".join(checksum_lines) + "\n"
    (drop_dir / "UMSMFBURASBOFE-Release-SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    (drop_dir / "UMSMFBURASBOFE-SHA256SUMS.txt").write_text(checksums, encoding="utf-8")


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

    write_archive(OUTPUT)
    refresh_drop_folder(DEFAULT_DROP_DIR, OUTPUT)
    print(OUTPUT)
    print(DEFAULT_DROP_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
