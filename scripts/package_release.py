#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "Uncle-Matts-Project-Manageroo"
PROJECT_VERSION = str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
VERSION_TAG = f"v{PROJECT_VERSION}"
ARTIFACT_BASENAME = f"uncle-matts-project-manageroo-{VERSION_TAG}"
DROP_ROOT = ARTIFACT_BASENAME
DEFAULT_DROP_DIR = ROOT.parent / DROP_ROOT
INSTALLER_ZIP = f"{ARTIFACT_BASENAME}.zip"
SOURCE_ZIP = f"{ARTIFACT_BASENAME}-source.zip"
OUTPUT = ROOT.parent / INSTALLER_ZIP
SOURCE_OUTPUT = ROOT.parent / SOURCE_ZIP
EXCLUDED_PARTS = {
    ".git", ".manageroo", ".venv", ".clawpatch", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "__pycache__", "dist", "build",
}
SENSITIVE_FILENAMES = {".env", "credentials.json", "service-account.json", "id_rsa", "id_ed25519"}
SAFE_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
CHECKSUM_EXCLUDED = {"SHA256SUMS.txt", "BUILD-VALIDATION.json"}
EXPLICIT_GENERATED = {"BUILD-VALIDATION.json", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md"}
DROP_CLEANUP_PREFIXES = (
    ARTIFACT_BASENAME,
    "Manageroo-",
    "".join(chr(code) for code in [85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69]) + "-",
)
END_USER_EXCLUDED = {
    "BUILD-VALIDATION.json", "GITHUB_DESCRIPTION.md", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md",
    "scripts/package_release.py", "tests/test_package_release.py",
}


def release_file_allowed(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    if path.is_symlink():
        return False
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    lowered = path.name.lower()
    if lowered in SENSITIVE_FILENAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
        return False
    if "secret" in lowered or "credential" in lowered:
        return False
    if lowered.startswith(".env") and lowered not in SAFE_ENV_EXAMPLES:
        return False
    return path.is_file()


def _tracked_relative_paths() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
    )
    if result.returncode:
        raise RuntimeError("Unable to enumerate tracked release files: " + result.stderr.strip())
    return {item for item in result.stdout.split("\0") if item}


def included_files() -> list[Path]:
    relative_paths = _tracked_relative_paths()
    relative_paths.update(relative for relative in EXPLICIT_GENERATED if (ROOT / relative).is_file())
    files = [ROOT / relative for relative in sorted(relative_paths) if release_file_allowed(ROOT / relative)]
    required = {"README.md", "pyproject.toml", "install.sh", "install.ps1", "src/manageroo/__init__.py"}
    present = {path.relative_to(ROOT).as_posix() for path in files}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("Release file selection is incomplete; required files missing: " + ", ".join(missing))
    return files


def end_user_files() -> list[Path]:
    return [path for path in included_files() if path.relative_to(ROOT).as_posix() not in END_USER_EXCLUDED]


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
        "# File manifest", "", "This manifest is generated from the release source tree.", "",
        "| File | Bytes | Purpose |", "|---|---:|---|",
    ]
    for path in included_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in {"docs/FILE_MANIFEST.md", "SHA256SUMS.txt"}:
            continue
        lines.append(f"| `{relative}` | {path.stat().st_size} | {purpose(relative)} |")
    (ROOT / "docs" / "FILE_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive(output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                if path.is_symlink() or not release_file_allowed(path):
                    raise RuntimeError(f"Refusing unsafe release file: {path}")
                archive.write(path, arcname=f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}")
        os.replace(temp_path, output)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _drop_copies(end_user_archive: Path, source_archive: Path) -> dict[str, Path]:
    return {
        INSTALLER_ZIP: end_user_archive,
        SOURCE_ZIP: source_archive,
        "SOURCE-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "FINAL-VALIDATION.json": ROOT / "BUILD-VALIDATION.json",
        "LOCAL-SETUP.md": ROOT / "LOCAL_SETUP.md",
        "PUBLISH-TO-GITHUB.md": ROOT / "PUBLISH_TO_GITHUB.md",
        "GIVE-THIS-TO-YOUR-IDE-AGENT.md": ROOT / "GIVE-THIS-TO-YOUR-IDE-AGENT.md",
        "GITHUB-DESCRIPTION.md": ROOT / "GITHUB_DESCRIPTION.md",
    }


def _assert_drop_has_no_operator_symlinks(drop_dir: Path) -> None:
    if not drop_dir.exists():
        return
    if drop_dir.is_symlink() or not drop_dir.is_dir():
        raise RuntimeError(f"Release drop path must be a real directory: {drop_dir}")
    for existing in drop_dir.iterdir():
        if existing.is_symlink():
            raise RuntimeError(
                f"Refusing to refresh release drop containing operator-owned symlink: {existing}. "
                "Manageroo will not dereference or silently delete it."
            )


def refresh_drop_folder(drop_dir: Path, end_user_archive: Path, source_archive: Path) -> None:
    copies = _drop_copies(end_user_archive, source_archive)
    for source in copies.values():
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"Required release-drop file is missing or unsafe: {source}")
    _assert_drop_has_no_operator_symlinks(drop_dir)

    parent = drop_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{drop_dir.name}.stage-", dir=str(parent)))
    backup = drop_dir.with_name(drop_dir.name + ".manageroo-previous")
    try:
        if drop_dir.is_dir():
            for existing in drop_dir.iterdir():
                if existing.name == "SHA256SUMS.txt":
                    continue
                if existing.is_file() and existing.name.startswith(DROP_CLEANUP_PREFIXES):
                    continue
                destination = stage / existing.name
                if existing.is_dir():
                    shutil.copytree(existing, destination, symlinks=True)
                elif existing.is_file():
                    shutil.copy2(existing, destination)
        for name, source in copies.items():
            shutil.copy2(source, stage / name)
        checksum_lines = [
            f"{hashlib.sha256((stage / name).read_bytes()).hexdigest()}  {name}"
            for name in copies
        ]
        (stage / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

        if backup.exists():
            shutil.rmtree(backup)
        if drop_dir.exists():
            drop_dir.rename(backup)
        stage.rename(drop_dir)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if not drop_dir.exists() and backup.exists():
            backup.rename(drop_dir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _publish_archive_pair(candidate_output: Path, candidate_source: Path) -> None:
    """Publish both public archives as one recoverable transaction."""
    output_backup = OUTPUT.with_name(OUTPUT.name + ".manageroo-previous")
    source_backup = SOURCE_OUTPUT.with_name(SOURCE_OUTPUT.name + ".manageroo-previous")
    for backup in (output_backup, source_backup):
        if backup.exists():
            backup.unlink()
    output_had_old = OUTPUT.exists()
    source_had_old = SOURCE_OUTPUT.exists()
    try:
        if output_had_old:
            OUTPUT.rename(output_backup)
        if source_had_old:
            SOURCE_OUTPUT.rename(source_backup)
        os.replace(candidate_output, OUTPUT)
        os.replace(candidate_source, SOURCE_OUTPUT)
    except Exception as exc:
        rollback_errors: list[str] = []
        for published, backup, had_old in (
            (OUTPUT, output_backup, output_had_old),
            (SOURCE_OUTPUT, source_backup, source_had_old),
        ):
            try:
                if published.exists():
                    published.unlink()
                if had_old and backup.exists():
                    backup.rename(published)
            except OSError as rollback_exc:
                rollback_errors.append(f"{published}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                f"Release archive publication failed: {exc}; rollback also failed: {'; '.join(rollback_errors)}"
            ) from exc
        raise
    else:
        for backup in (output_backup, source_backup):
            if backup.exists():
                backup.unlink()


def main() -> int:
    result = subprocess.run([sys.executable, "scripts/verify_release.py"], cwd=ROOT, shell=False)
    if result.returncode:
        return result.returncode

    distribution = subprocess.run([sys.executable, "scripts/verify_distribution.py"], cwd=ROOT, shell=False)
    if distribution.returncode:
        return distribution.returncode

    generate_manifest()
    checksums = []
    for path in included_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in CHECKSUM_EXCLUDED:
            continue
        checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    (ROOT / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="manageroo-release-candidate-", dir=str(ROOT.parent)) as temp:
        candidate_root = Path(temp)
        candidate_output = candidate_root / INSTALLER_ZIP
        candidate_source = candidate_root / SOURCE_ZIP
        write_archive(candidate_output, end_user_files())
        write_archive(candidate_source, included_files())
        smoke = subprocess.run(
            [
                sys.executable,
                "scripts/smoke_release_install.py",
                "--archive",
                str(candidate_output),
                "--skip-install-tests",
            ],
            cwd=ROOT,
            shell=False,
        )
        if smoke.returncode:
            return smoke.returncode
        _publish_archive_pair(candidate_output, candidate_source)

    refresh_drop_folder(DEFAULT_DROP_DIR, OUTPUT, SOURCE_OUTPUT)
    print(OUTPUT)
    print(SOURCE_OUTPUT)
    print(DEFAULT_DROP_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
