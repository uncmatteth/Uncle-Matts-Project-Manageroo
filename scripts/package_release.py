#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manageroo.config_lock import config_mutation_lock  # noqa: E402

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
EXPLICIT_TRACKED_POLICY_FILES = {".manageroo/config.toml"}
SENSITIVE_FILENAMES = {".env", "credentials.json", "service-account.json", "id_rsa", "id_ed25519"}
SAFE_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"}
CHECKSUM_EXCLUDED = {"SHA256SUMS.txt", "BUILD-VALIDATION.json"}
EXPLICIT_GENERATED = {"BUILD-VALIDATION.json", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md"}
DROP_ARCHIVE_PREFIXES = (
    "uncle-matts-project-manageroo-",
    "Manageroo-",
    "".join(chr(code) for code in [85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69]) + "-",
)
DROP_ARCHIVE_SUFFIX = re.compile(r"v\d+(?:\.\d+)+(?:-source)?\.zip")
END_USER_EXCLUDED = {
    "BUILD-VALIDATION.json", "GITHUB_DESCRIPTION.md", "SHA256SUMS.txt", "docs/FILE_MANIFEST.md",
    "scripts/package_release.py", "tests/test_package_release.py",
}
RELEASE_FILE_LIST_ENV = "MANAGEROO_RELEASE_FILE_LIST"
PACKAGE_RESULT_PREFIX = "MANAGEROO_PACKAGE_RESULT="


def _strict_relative_path(path: Path, root: Path) -> Path | None:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if not relative.parts or path != root / relative:
        return None
    return relative


def _validated_release_file_list_entry(relative: str) -> str:
    components = [relative]
    for separator in (os.sep, os.altsep):
        if separator:
            components = [part for component in components for part in component.split(separator)]
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or any(component in {"", ".", ".."} for component in components)
        or _strict_relative_path(ROOT / candidate, ROOT) != candidate
    ):
        raise RuntimeError(f"Unsafe release file-list entry: {relative!r}")
    return relative


def release_file_allowed(path: Path) -> bool:
    relative = _strict_relative_path(path, ROOT)
    if relative is None:
        return False
    if path.is_symlink():
        return False
    relative_text = relative.as_posix()
    if any(part in EXCLUDED_PARTS for part in relative.parts) and relative_text not in EXPLICIT_TRACKED_POLICY_FILES:
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
    snapshot_file_list = os.environ.get(RELEASE_FILE_LIST_ENV)
    if snapshot_file_list:
        return {
            _validated_release_file_list_entry(os.fsdecode(item))
            for item in Path(snapshot_file_list).read_bytes().split(b"\0")
            if item
        }
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
    )
    if result.returncode:
        raise RuntimeError("Unable to enumerate tracked release files: " + result.stderr.strip())
    return {
        _validated_release_file_list_entry(item)
        for item in result.stdout.split("\0")
        if item
    }


def included_files() -> list[Path]:
    relative_paths = _tracked_relative_paths()
    relative_paths.update(relative for relative in EXPLICIT_GENERATED if (ROOT / relative).is_file())
    files = [ROOT / relative for relative in sorted(relative_paths) if release_file_allowed(ROOT / relative)]
    required = {
        ".manageroo/config.toml",
        "README.md",
        "pyproject.toml",
        "install.sh",
        "install.ps1",
        "src/manageroo/__init__.py",
    }
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


def _stage_release_snapshot(snapshot_root: Path) -> Path:
    """Copy Git-selected worktree bytes into one private immutable release input."""
    if RELEASE_FILE_LIST_ENV in os.environ:
        raise RuntimeError(
            f"Refusing inherited {RELEASE_FILE_LIST_ENV} during release snapshot staging"
        )
    snapshot_root.mkdir(mode=0o700)
    relative_paths: list[str] = []
    for source in included_files():
        try:
            relative = source.relative_to(ROOT)
        except ValueError as exc:
            raise RuntimeError(f"Refusing unsafe release file while staging: {source}") from exc
        destination = snapshot_root / relative
        if _strict_relative_path(destination, snapshot_root) != relative:
            raise RuntimeError(f"Refusing unsafe release destination while staging: {destination}")
        if source.is_symlink() or not release_file_allowed(source):
            raise RuntimeError(f"Refusing unsafe release file while staging: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        if (
            destination.is_symlink()
            or not destination.is_file()
            or _strict_relative_path(destination, snapshot_root) != relative
        ):
            raise RuntimeError(f"Release file became unsafe while staging: {source}")
        relative_paths.append(relative.as_posix())

    file_list = snapshot_root.parent / ".manageroo-release-files"
    file_list.write_bytes(b"\0".join(os.fsencode(path) for path in relative_paths) + b"\0")
    return file_list


@contextmanager
def _use_release_snapshot(snapshot_root: Path, file_list: Path):
    """Bind all release selectors and child validators to the staged snapshot."""
    global ROOT
    original_root = ROOT
    original_file_list = os.environ.get(RELEASE_FILE_LIST_ENV)
    ROOT = snapshot_root
    os.environ[RELEASE_FILE_LIST_ENV] = str(file_list)
    try:
        yield
    finally:
        ROOT = original_root
        if original_file_list is None:
            os.environ.pop(RELEASE_FILE_LIST_ENV, None)
        else:
            os.environ[RELEASE_FILE_LIST_ENV] = original_file_list


def _release_fingerprint(*, exclude: set[str] | frozenset[str] = frozenset()) -> tuple:
    return tuple(
        (relative, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in included_files()
        if (relative := path.relative_to(ROOT).as_posix()) not in exclude
    )


def _assert_release_fingerprint(expected: tuple, stage: str, *, exclude: set[str]) -> None:
    if _release_fingerprint(exclude=exclude) != expected:
        raise RuntimeError(f"Staged release source changed during {stage}; refusing publication.")


def write_archive(output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                relative = _strict_relative_path(path, ROOT)
                if relative is None or path.is_symlink() or not release_file_allowed(path):
                    raise RuntimeError(f"Refusing unsafe release file: {path}")
                archive.write(path, arcname=f"{ARCHIVE_ROOT}/{relative.as_posix()}")
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


def _is_versioned_release_archive(name: str) -> bool:
    return any(
        name.startswith(prefix) and DROP_ARCHIVE_SUFFIX.fullmatch(name[len(prefix):])
        for prefix in DROP_ARCHIVE_PREFIXES
    )


def refresh_drop_folder(
    drop_dir: Path,
    end_user_archive: Path,
    source_archive: Path,
    retain_backup: bool = False,
) -> None:
    copies = _drop_copies(end_user_archive, source_archive)
    for source in copies.values():
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"Required release-drop file is missing or unsafe: {source}")
    _assert_drop_has_no_operator_symlinks(drop_dir)

    parent = drop_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    backup = drop_dir.with_name(drop_dir.name + ".manageroo-previous")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(
            f"Interrupted release-drop transaction found at {backup}; "
            "refusing to overwrite recovery data."
        )
    drop_had_old = drop_dir.is_dir()
    stage = Path(tempfile.mkdtemp(prefix=f".{drop_dir.name}.stage-", dir=str(parent)))
    generated_names = {*copies, "SHA256SUMS.txt"}
    try:
        if drop_had_old:
            for existing in drop_dir.iterdir():
                if existing.is_file() and (
                    existing.name in generated_names
                    or _is_versioned_release_archive(existing.name)
                ):
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

        if drop_dir.exists():
            drop_dir.rename(backup)
        stage.rename(drop_dir)
        if backup.exists() and not retain_backup:
            shutil.rmtree(backup)
    except Exception:
        if not drop_dir.exists() and backup.exists():
            backup.rename(drop_dir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _publish_archive_pair(
    candidate_output: Path,
    candidate_source: Path,
    retain_backups: bool = False,
) -> None:
    """Publish both public archives as one recoverable transaction."""
    output_backup = OUTPUT.with_name(OUTPUT.name + ".manageroo-previous")
    source_backup = SOURCE_OUTPUT.with_name(SOURCE_OUTPUT.name + ".manageroo-previous")
    existing_backups = [
        backup
        for backup in (output_backup, source_backup)
        if backup.exists() or backup.is_symlink()
    ]
    if existing_backups:
        raise RuntimeError(
            "Interrupted release archive transaction found; refusing to overwrite recovery data: "
            + ", ".join(str(backup) for backup in existing_backups)
        )
    output_had_old = OUTPUT.exists()
    source_had_old = SOURCE_OUTPUT.exists()
    output_backup_created = False
    source_backup_created = False
    output_published = False
    source_published = False
    try:
        if output_had_old:
            OUTPUT.rename(output_backup)
            output_backup_created = True
        if source_had_old:
            SOURCE_OUTPUT.rename(source_backup)
            source_backup_created = True
        os.replace(candidate_output, OUTPUT)
        output_published = True
        os.replace(candidate_source, SOURCE_OUTPUT)
        source_published = True
    except Exception as exc:
        rollback_errors: list[str] = []
        for published, backup, backup_created, candidate_published in (
            (OUTPUT, output_backup, output_backup_created, output_published),
            (SOURCE_OUTPUT, source_backup, source_backup_created, source_published),
        ):
            try:
                if candidate_published and published.exists():
                    published.unlink()
                if backup_created and backup.exists():
                    backup.rename(published)
            except OSError as rollback_exc:
                rollback_errors.append(f"{published}: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(
                f"Release archive publication failed: {exc}; rollback also failed: {'; '.join(rollback_errors)}"
            ) from exc
        raise
    else:
        if not retain_backups:
            for backup in (output_backup, source_backup):
                if backup.exists():
                    backup.unlink()


def _rollback_archive_pair(
    candidate_output: Path,
    candidate_source: Path,
) -> list[str]:
    rollback_errors: list[str] = []
    for published, candidate in (
        (OUTPUT, candidate_output),
        (SOURCE_OUTPUT, candidate_source),
    ):
        backup = published.with_name(published.name + ".manageroo-previous")
        try:
            if published.exists():
                os.replace(published, candidate)
            if backup.exists():
                backup.rename(published)
        except OSError as exc:
            rollback_errors.append(f"{published}: {exc}")
    return rollback_errors


def _release_lock_target() -> Path:
    """Use one publication lock for every checkout sharing the output archive."""
    output_parent = OUTPUT.parent.resolve()
    return output_parent / ".manageroo-release-locks" / OUTPUT.name


def _files_match(first: Path, second: Path) -> bool:
    if (
        first.is_symlink()
        or second.is_symlink()
        or not first.is_file()
        or not second.is_file()
        or first.stat().st_size != second.stat().st_size
    ):
        return False
    return hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()


def _publication_backups(drop_dir: Path) -> tuple[Path, Path, Path]:
    return (
        OUTPUT.with_name(OUTPUT.name + ".manageroo-previous"),
        SOURCE_OUTPUT.with_name(SOURCE_OUTPUT.name + ".manageroo-previous"),
        drop_dir.with_name(drop_dir.name + ".manageroo-previous"),
    )


def _cleanup_publication_backups(drop_dir: Path) -> list[str]:
    warnings: list[str] = []
    output_backup, source_backup, drop_backup = _publication_backups(drop_dir)
    for backup in (output_backup, source_backup):
        if not backup.exists() and not backup.is_symlink():
            continue
        try:
            if backup.is_symlink() or not backup.is_file():
                raise OSError("backup is not a regular file")
            backup.unlink()
        except OSError as exc:
            warnings.append(f"Could not remove published-release backup {backup}: {exc}")
    if drop_backup.exists() or drop_backup.is_symlink():
        try:
            if drop_backup.is_symlink() or not drop_backup.is_dir():
                raise OSError("backup is not a real directory")
            shutil.rmtree(drop_backup)
        except OSError as exc:
            warnings.append(f"Could not remove published-release backup {drop_backup}: {exc}")
    return warnings


def _reconcile_publication_backups(
    candidate_output: Path,
    candidate_source: Path,
    drop_dir: Path,
) -> None:
    backups = [
        backup
        for backup in _publication_backups(drop_dir)
        if backup.exists() or backup.is_symlink()
    ]
    if not backups:
        return
    copies = _drop_copies(OUTPUT, SOURCE_OUTPUT)
    publication_matches = (
        _files_match(candidate_output, OUTPUT)
        and _files_match(candidate_source, SOURCE_OUTPUT)
        and all(_files_match(drop_dir / name, source) for name, source in copies.items())
    )
    if not publication_matches:
        raise RuntimeError(
            "Interrupted release transaction does not match the current candidate; "
            "refusing to discard recovery data: " + ", ".join(str(path) for path in backups)
        )
    warnings = _cleanup_publication_backups(drop_dir)
    if warnings:
        raise RuntimeError("Could not reconcile published-release backups: " + "; ".join(warnings))


def _publish_release(candidate_output: Path, candidate_source: Path, drop_dir: Path) -> dict:
    release_lock_target = _release_lock_target()
    release_lock_target.parent.mkdir(mode=0o700, exist_ok=True)
    if release_lock_target.parent.is_symlink() or not release_lock_target.parent.is_dir():
        raise RuntimeError(f"Release lock directory is unsafe: {release_lock_target.parent}")
    with config_mutation_lock(release_lock_target, timeout_seconds=600.0):
        _reconcile_publication_backups(candidate_output, candidate_source, drop_dir)
        _publish_archive_pair(
            candidate_output,
            candidate_source,
            True,
        )
        try:
            refresh_drop_folder(drop_dir, OUTPUT, SOURCE_OUTPUT, True)
        except Exception as exc:
            rollback_errors = _rollback_archive_pair(
                candidate_output,
                candidate_source,
            )
            if rollback_errors:
                raise RuntimeError(
                    f"Release drop publication failed: {exc}; "
                    f"archive rollback also failed: {'; '.join(rollback_errors)}"
                ) from exc
            raise
        return {
            "release_created": True,
            "warnings": _cleanup_publication_backups(drop_dir),
        }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="manageroo-release-candidate-", dir=str(ROOT)) as temp:
        candidate_root = Path(temp)
        snapshot_root = candidate_root / "snapshot"
        file_list = _stage_release_snapshot(snapshot_root)
        candidate_output = candidate_root / INSTALLER_ZIP
        candidate_source = candidate_root / SOURCE_ZIP
        with _use_release_snapshot(snapshot_root, file_list):
            result = subprocess.run(
                [sys.executable, "scripts/verify_release.py"], cwd=ROOT, shell=False
            )
            if result.returncode:
                return result.returncode
            validated_source = _release_fingerprint(exclude=EXPLICIT_GENERATED)

            distribution = subprocess.run(
                [sys.executable, "scripts/verify_distribution.py"], cwd=ROOT, shell=False
            )
            if distribution.returncode:
                return distribution.returncode
            _assert_release_fingerprint(
                validated_source, "distribution verification", exclude=EXPLICIT_GENERATED
            )

            generate_manifest()
            checksums = []
            for path in included_files():
                relative = path.relative_to(ROOT).as_posix()
                if relative in CHECKSUM_EXCLUDED:
                    continue
                checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
            (ROOT / "SHA256SUMS.txt").write_text(
                "\n".join(checksums) + "\n", encoding="utf-8"
            )
            archive_source = _release_fingerprint()

            write_archive(candidate_output, end_user_files())
            write_archive(candidate_source, included_files())
            _assert_release_fingerprint(archive_source, "archive creation", exclude=set())
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
            _assert_release_fingerprint(archive_source, "smoke testing", exclude=set())
            publication = _publish_release(candidate_output, candidate_source, DEFAULT_DROP_DIR)
    for warning in publication["warnings"]:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(OUTPUT)
    print(SOURCE_OUTPUT)
    print(DEFAULT_DROP_DIR)
    print(PACKAGE_RESULT_PREFIX + json.dumps(publication, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
