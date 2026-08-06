from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .assets import asset_path
from .util import atomic_write_json


@dataclass(frozen=True)
class TokenMode:
    id: str
    label: str
    skill_name: str | None
    asset: str | None
    prompt: str


TOKEN_MODES = {
    "off": TokenMode(id="off", label="Off", skill_name=None, asset=None, prompt=""),
    "caveman": TokenMode(
        id="caveman",
        label="Token Reduction: Caveman",
        skill_name="caveman",
        asset="skills/caveman/SKILL.md",
        prompt=(
            "Token mode: Caveman. Be terse. Drop filler, pleasantries, hedging, "
            "and needless connector words. Keep exact technical meaning, code, "
            "commands, JSON keys, quoted errors, paths, and safety warnings intact."
        ),
    ),
    "curse": TokenMode(
        id="curse",
        label="Token Reduction: Uncle Matt's Caveman Curse",
        skill_name="uncle-matts-caveman-curse",
        asset="skills/uncle-matts-caveman-curse/SKILL.md",
        prompt=(
            "Token mode: Uncle Matt's Caveman Curse. Use caveman compression with "
            "blunt profanity in natural-language status, findings, and explanations "
            "when it fits because life is more fun with appropriately placed, "
            "well-used profanity. Curse at broken code or broken process, not the user. "
            "Never add profanity to code, shell commands, JSON keys, exact errors, "
            "quoted source, or user-facing product copy unless explicitly asked."
        ),
    ),
}

BUNDLED_SKILL_LIBRARY = {
    "uncle-matts-project-manageroo": "skills/uncle-matts-project-manageroo/SKILL.md",
    "use-installed-skills-first": "skills/use-installed-skills-first/SKILL.md",
    "skill-vetter": "skills/skill-vetter/SKILL.md",
    "pimp-my-prompt": "skills/pimp-my-prompt/SKILL.md",
    "brain-ops": "skills/brain-ops/SKILL.md",
    "query": "skills/query/SKILL.md",
    "ingest": "skills/ingest/SKILL.md",
    "idea-ingest": "skills/idea-ingest/SKILL.md",
    "media-ingest": "skills/media-ingest/SKILL.md",
    "voice-note-ingest": "skills/voice-note-ingest/SKILL.md",
    "article-enrichment": "skills/article-enrichment/SKILL.md",
    "book-mirror": "skills/book-mirror/SKILL.md",
    "strategic-reading": "skills/strategic-reading/SKILL.md",
    "pdf": "skills/pdf/SKILL.md",
    "brain-pdf": "skills/brain-pdf/SKILL.md",
    "citation-fixer": "skills/citation-fixer/SKILL.md",
    "reports": "skills/reports/SKILL.md",
    "exact-text-replacement": "skills/exact-text-replacement/SKILL.md",
    "academic-verify": "skills/academic-verify/SKILL.md",
    "data-research": "skills/data-research/SKILL.md",
    "perplexity-research": "skills/perplexity-research/SKILL.md",
    "repo-architecture": "skills/repo-architecture/SKILL.md",
    "find-skills": "skills/find-skills/SKILL.md",
    "writing-for-agents": "skills/writing-for-agents/SKILL.md",
    "edit-skill": "skills/edit-skill/SKILL.md",
    "skillify": "skills/skillify/SKILL.md",
    "skillpack-check": "skills/skillpack-check/SKILL.md",
    "handoff": "skills/handoff/SKILL.md",
    "setup-matt-pocock-skills": "skills/setup-matt-pocock-skills/SKILL.md",
    "to-spec": "skills/to-spec/SKILL.md",
    "to-tickets": "skills/to-tickets/SKILL.md",
    "grill-me": "skills/grill-me/SKILL.md",
    "grilling": "skills/grilling/SKILL.md",
    "grill-with-docs": "skills/grill-with-docs/SKILL.md",
    "domain-modeling": "skills/domain-modeling/SKILL.md",
    "codebase-design": "skills/codebase-design/SKILL.md",
    "functional-area-resolver": "skills/functional-area-resolver/SKILL.md",
    "diagnosing-bugs": "skills/diagnosing-bugs/SKILL.md",
    "tdd": "skills/tdd/SKILL.md",
    "testing": "skills/testing/SKILL.md",
    "improve-codebase-architecture": "skills/improve-codebase-architecture/SKILL.md",
    "security-review": "skills/security-review/SKILL.md",
    "cross-modal-review": "skills/cross-modal-review/SKILL.md",
    "subagent-orchestrator": "skills/subagent-orchestrator/SKILL.md",
    "minion-orchestrator": "skills/minion-orchestrator/SKILL.md",
    "autoreview": "skills/autoreview/SKILL.md",
    "plain-web-copy": "skills/plain-web-copy/SKILL.md",
    "fix-my-bad-website": "skills/fix-my-bad-website/SKILL.md",
    "web-design-guidelines": "skills/web-design-guidelines/SKILL.md",
    "open-design": "skills/open-design/SKILL.md",
    "playwright": "skills/playwright/SKILL.md",
    "playwright-interactive": "skills/playwright-interactive/SKILL.md",
    "caveman": "skills/caveman/SKILL.md",
    "uncle-matts-caveman-curse": "skills/uncle-matts-caveman-curse/SKILL.md",
}

CORE_SKILL_NAMES = (
    "uncle-matts-project-manageroo",
    "use-installed-skills-first",
    "skill-vetter",
    "pimp-my-prompt",
    "setup-matt-pocock-skills",
    "to-spec",
    "to-tickets",
    "grill-me",
    "grilling",
    "grill-with-docs",
    "domain-modeling",
    "codebase-design",
    "diagnosing-bugs",
    "tdd",
    "testing",
    "security-review",
    "handoff",
    "writing-for-agents",
    "edit-skill",
    "skillify",
    "caveman",
    "uncle-matts-caveman-curse",
)
CORE_SKILL_PACK = {name: BUNDLED_SKILL_LIBRARY[name] for name in CORE_SKILL_NAMES}
OPTIONAL_SKILL_PACK = {
    name: asset for name, asset in BUNDLED_SKILL_LIBRARY.items() if name not in CORE_SKILL_PACK
}
RECOMMENDED_SKILL_PACK = CORE_SKILL_PACK
CORE_HELPER_SKILLS = CORE_SKILL_PACK

RETIRED_CORE_SKILL_NAMES = (
    "to-prd",
    "to-issues",
    "diagnose",
    "write-a-skill",
)

MAX_OWNED_SKILL_TREE_BYTES = 2_000_000
MAX_OWNED_SKILL_TREE_FILES = 128
MAX_OWNED_SKILL_TREE_ENTRIES = 512

# Full-tree digests shipped by Manageroo before the ownership ledger existed.
# These are migration identities, not a claim over arbitrary same-name skills.
LEGACY_MANAGEROO_SKILL_DIGESTS = {
    "uncle-matts-project-manageroo": {"0cda7775b5771ec09f70c841c1fd636435251ca2951d6a196d14d9189211c8bf", "551282202f0db68b79cc324f3c17121d4fc4ac5032e5422a2a0e920f8238baa1"},
    "use-installed-skills-first": {"a9878b6a14df15bb2ad8d0381be99519265e56e4c9919a78ac3c86255c579e5e"},
    "skill-vetter": {"2b09c761fc0890e4b64f22e96bfcb5c6d20e729073b14d766da0bef7f80aebc2"},
    "pimp-my-prompt": {"085f757dd6109185e37b0de81f1af3d07e1297ad716ac24dfe1e01fe2fd2c3d4"},
    "to-prd": {"9901089b6c0e3aebad5ba84a8cb62dcbc876b396f0d7893029258ef5d9f09476"},
    "to-issues": {"5289bd5c5395e9aa87c755939f2befa913b9a865aa41f0bcfeab78e02798b180"},
    "grill-me": {"2fd5c5ebe9776ce10691d31593f78d85d66698a68b3b16955da9c92d858945ac"},
    "grill-with-docs": {"ffc49a3b389aadbb3b08a72ff9b9b9bf819e1ba009cf614d5b26adf8a3e04aff"},
    "diagnose": {"a10d620f55ebda97b5b8e543b068db139224b7d978db81bf9e93d989fe661c87"},
    "tdd": {"00ace6156bbb502d80c31baf4077597ed350d04a817d89642bc706f5c8b37281"},
    "testing": {"00973a750737ac8cdfe660362c9d240a9943ff96da5e67cb18aee8f615511702"},
    "security-review": {"68e692de077f5d9d3cdf5b828d6f1f68935819d84379c1adba675b9c7ef302ce"},
    "handoff": {"3e06bf1bf645c3f0195e510f2984af4e5fb37e4fa4380694b684622bedc65b0b"},
    "write-a-skill": {"75ecacda1a91eda680f3bd45aa5bcc2e13ac04cf84dad62f772ad3e069627934"},
    "edit-skill": {"17eb3d1145f7a79fbcfafdf5525ee4a3f902ffb45b415297b031581564247458"},
    "skillify": {"8212c35f7b43f4e85a30ba256f542cbda04da83f197c657fb747fad192dbeef2"},
    "caveman": {"8f23754244ec66dbd30d049893eaab06c5bfa95a8a131bf4bc4ca01d5759e2d5"},
    "uncle-matts-caveman-curse": {"ced70c837bd982122e759846939a4564cbf78f12e329d449a6d77e39836c42b1"},
}

ALIASES = {
    "none": "off",
    "normal": "off",
    "clean": "caveman",
    "uncle": "curse",
    "uncle-matts-caveman-curse": "curse",
    "caveman-curse": "curse",
}


def normalize_mode(mode: str) -> str:
    normalized = ALIASES.get(mode.strip().lower(), mode.strip().lower())
    if normalized not in TOKEN_MODES:
        allowed = ", ".join(sorted(TOKEN_MODES))
        raise ValueError(f"Unknown token mode {mode!r}. Use one of: {allowed}.")
    return normalized


def token_mode_state_path() -> Path:
    explicit = os.environ.get("MANAGEROO_TOKEN_MODE_FILE")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".config" / "manageroo" / "token-mode.json"


def token_mode_skills_dir() -> Path:
    explicit = os.environ.get("MANAGEROO_SKILLS_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".agents" / "skills"


def _backup_path(destination: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}")
    index = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}.manageroo-backup-{stamp}-{index}")
        index += 1
    return candidate


def _validated_destination_parent(root_real: Path, destination: Path) -> Path:
    try:
        relative = destination.relative_to(root_real)
    except ValueError as exc:
        raise ValueError(f"Refusing to install skill outside skills root: {destination}") from exc
    current = root_real
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing to install through symlinked destination directory: {current}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"Refusing to install through non-directory path: {current}")
        current.mkdir(exist_ok=True)
        resolved = current.resolve()
        if not resolved.is_relative_to(root_real):
            raise ValueError(f"Refusing to install through path outside skills root: {current}")
    return destination.parent


def _copy_skill_tree(source_dir: Path, destination_dir: Path, *, root_real: Path) -> None:
    for source_path in source_dir.rglob("*"):
        if source_path.is_symlink():
            raise ValueError(f"Refusing to copy symlinked bundled skill content: {source_path}")
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source_dir)
        destination = destination_dir / relative
        _validated_destination_parent(root_real, destination)
        if destination.is_symlink():
            raise ValueError(f"Refusing to overwrite symlinked skill file: {destination}")
        if destination.exists() and destination.read_bytes() != source_path.read_bytes():
            backup = _backup_path(destination)
            _validated_destination_parent(root_real, backup)
            shutil.copy2(destination, backup)
        shutil.copy2(source_path, destination)


def _skill_tree_digest(root: Path, *, structured: bool) -> str:
    digest = hashlib.sha256()
    entries = 0
    files = 0
    total_bytes = 0
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort()
        file_names.sort()
        entries += len(directory_names) + len(file_names)
        if entries > MAX_OWNED_SKILL_TREE_ENTRIES:
            raise ValueError("Skill tree exceeds the ownership entry limit.")
        for name in directory_names:
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError(f"Refusing symlinked skill content: {path}")
            if structured:
                relative = path.relative_to(root).as_posix().encode("utf-8", errors="strict")
                digest.update(b"D")
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
        for name in file_names:
            path = Path(current) / name
            if path.is_symlink():
                raise ValueError(f"Refusing symlinked skill content: {path}")
            if not path.is_file():
                continue
            files += 1
            if files > MAX_OWNED_SKILL_TREE_FILES:
                raise ValueError("Skill tree exceeds the ownership file limit.")
            size = path.stat().st_size
            if size < 0 or total_bytes + size > MAX_OWNED_SKILL_TREE_BYTES:
                raise ValueError("Skill tree exceeds the ownership byte limit.")
            relative = path.relative_to(root).as_posix().encode("utf-8", errors="strict")
            if structured:
                digest.update(b"F")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            if structured:
                digest.update(size.to_bytes(8, "big"))
            read_bytes = 0
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65_536), b""):
                    read_bytes += len(chunk)
                    if total_bytes + read_bytes > MAX_OWNED_SKILL_TREE_BYTES:
                        raise ValueError("Skill tree exceeds the ownership byte limit.")
                    digest.update(chunk)
            if read_bytes != size:
                raise ValueError(f"Skill file changed while hashing: {path}")
            total_bytes += read_bytes
    if structured:
        digest.update(b"END")
        digest.update(entries.to_bytes(8, "big"))
        digest.update(files.to_bytes(8, "big"))
        digest.update(total_bytes.to_bytes(8, "big"))
    return digest.hexdigest()


def _skill_tree_sha256(root: Path) -> str:
    return _skill_tree_digest(root, structured=True)


def _legacy_skill_tree_sha256(root: Path) -> str:
    return _skill_tree_digest(root, structured=False)


def _is_manageroo_owned(
    skill_dir: Path,
    skill_name: str,
    ownership: dict[str, Any],
    current_digest: str,
    bundled_digest: str | None = None,
) -> bool:
    if bundled_digest is not None and current_digest == bundled_digest:
        return True
    record = ownership.get("skills", {}).get(str(skill_dir.resolve()), {})
    if isinstance(record, dict) and record.get("tree_sha256") == current_digest:
        return True
    legacy_digest = _legacy_skill_tree_sha256(skill_dir)
    return (
        isinstance(record, dict) and record.get("tree_sha256") == legacy_digest
    ) or legacy_digest in LEGACY_MANAGEROO_SKILL_DIGESTS.get(skill_name, set())


def _ownership_file(root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("MANAGEROO_SKILL_OWNERSHIP_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if root == token_mode_skills_dir().expanduser().resolve():
        return Path.home() / ".config" / "manageroo" / "skill-ownership.json"
    return root / ".manageroo-ownership.json"


def _read_ownership(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {"version": 1, "skills": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"version": 1, "skills": {}}
    skills = payload.get("skills", {}) if isinstance(payload, dict) else {}
    return {"version": 1, "skills": skills if isinstance(skills, dict) else {}}


def _snapshot_file_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


def _json_file_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _restore_file_bytes(path: Path, contents: bytes | None) -> None:
    if contents is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, stage_name = tempfile.mkstemp(
        prefix=f".{path.name}.manageroo-restore-",
        dir=path.parent,
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, path)
    finally:
        if stage.exists():
            stage.unlink()


def _restore_file_bytes_if_matches(
    path: Path,
    expected_current: bytes,
    previous: bytes | None,
) -> None:
    if _snapshot_file_bytes(path) == expected_current:
        _restore_file_bytes(path, previous)


def _default_search_roots(target_root: Path) -> list[Path]:
    target_real = target_root.expanduser().resolve()
    values = [Path.home() / ".agents" / "skills", Path.home() / ".codex" / "skills"]
    return [
        value.expanduser().resolve()
        for value in values
        if not value.expanduser().is_symlink()
        and value.expanduser().exists()
        and value.expanduser().resolve() != target_real
    ]


def _existing_skill_in_roots(skill_name: str, roots: list[Path]) -> Path | None:
    for root in roots:
        unresolved = root.expanduser()
        if unresolved.is_symlink() or not unresolved.is_dir():
            continue
        root_real = unresolved.resolve()
        skill_dir = unresolved / skill_name
        candidate = skill_dir / "SKILL.md"
        if skill_dir.is_symlink() or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root_real)
            _skill_tree_sha256(skill_dir)
        except (OSError, ValueError):
            continue
        return resolved
    return None


def _try_lock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _skill_install_lock(root_real: Path, *, timeout: float = 30.0):
    lock = root_real / ".manageroo-skill-install.lock"
    common_flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(lock, common_flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(lock, common_flags)
        except OSError as exc:
            raise OSError(f"Could not open skill install lock: {lock}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"Could not open skill install lock: {lock}: {exc}") from exc
    acquired = False
    try:
        lock_state = os.fstat(descriptor)
        try:
            path_state = lock.lstat()
        except OSError as exc:
            raise OSError(f"Could not validate skill install lock path: {lock}: {exc}") from exc
        is_reparse_point = bool(
            getattr(path_state, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if (
            lock.is_symlink()
            or is_reparse_point
            or not stat.S_ISREG(lock_state.st_mode)
            or not stat.S_ISREG(path_state.st_mode)
            or lock_state.st_nlink != 1
            or path_state.st_nlink != 1
            or (lock_state.st_dev, lock_state.st_ino) != (path_state.st_dev, path_state.st_ino)
        ):
            raise OSError(f"Skill install lock path is not a private regular file: {lock}")

        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock_file(descriptor)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise OSError(f"Could not acquire skill install lock: {lock}: {exc}") from exc
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for skill install lock: {lock}") from exc
                time.sleep(0.05)

        # Existing lock files are never rewritten: even a valid regular file may be
        # unexpected user data. Only publish metadata to the inode created above.
        if created:
            os.write(descriptor, f"pid={os.getpid()}\n".encode("utf-8"))
            os.fsync(descriptor)
        yield
    finally:
        try:
            if acquired:
                _unlock_file(descriptor)
        finally:
            os.close(descriptor)


def _tree_identity(path: Path) -> tuple[int, int, str]:
    stat = path.lstat()
    return stat.st_dev, stat.st_ino, _skill_tree_sha256(path)


def _same_tree_identity(path: Path, identity: tuple[int, int, str] | None) -> bool:
    if identity is None or not path.is_dir() or path.is_symlink():
        return False
    try:
        return _tree_identity(path) == identity
    except (OSError, ValueError):
        return False


def _replace_owned_skill(
    source_dir: Path,
    destination_dir: Path,
    root_real: Path,
    *,
    expected_identity: tuple[int, int, str] | None = None,
) -> None:
    stage = Path(tempfile.mkdtemp(prefix=f".{destination_dir.name}.manageroo-stage-", dir=root_real))
    old = root_real / f".{destination_dir.name}.manageroo-old-{os.urandom(6).hex()}"
    moved_old = False
    preserve_old = False
    try:
        shutil.copytree(source_dir, stage, dirs_exist_ok=True, symlinks=False)
        if not (stage / "SKILL.md").is_file():
            raise ValueError(f"Bundled skill is missing SKILL.md: {source_dir}")
        if expected_identity is not None and not destination_dir.exists():
            raise RuntimeError(f"Skill tree changed during replacement: {destination_dir}")
        if destination_dir.exists():
            destination_dir.rename(old)
            moved_old = True
            if expected_identity is not None and not _same_tree_identity(old, expected_identity):
                if destination_dir.exists():
                    preserve_old = True
                else:
                    old.rename(destination_dir)
                    moved_old = False
                raise RuntimeError(f"Skill tree changed during replacement: {destination_dir}")
        stage.rename(destination_dir)
        if moved_old:
            shutil.rmtree(old)
    except Exception:
        if moved_old and old.exists() and not destination_dir.exists():
            old.rename(destination_dir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if old.exists() and destination_dir.exists() and not preserve_old:
            shutil.rmtree(old)


def _install_bundled_skill(
    root: Path,
    skill_name: str,
    asset: str,
    *,
    search_roots: list[Path],
    ownership: dict[str, Any],
) -> str:
    unresolved_root = root.expanduser()
    if unresolved_root.is_symlink():
        raise ValueError(f"Refusing to install through symlinked skills root: {unresolved_root}")
    unresolved_root.mkdir(parents=True, exist_ok=True)
    root_real = unresolved_root.resolve()
    skill_dir = root_real / skill_name
    if skill_dir.is_symlink():
        raise ValueError(f"Refusing to install through symlinked skill directory: {skill_dir}")
    if skill_dir.exists() and not skill_dir.is_dir():
        raise ValueError(f"Refusing to install over non-directory skill path: {skill_dir}")
    if not skill_dir.resolve(strict=False).is_relative_to(root_real):
        raise ValueError(f"Refusing to install skill outside skills root: {skill_dir}")
    destination = skill_dir / "SKILL.md"
    if destination.is_symlink():
        raise ValueError(f"Refusing to overwrite symlinked skill file: {destination}")
    if skill_dir.exists() and not destination.is_file():
        raise ValueError(
            f"Refusing to replace occupied skill directory without SKILL.md: {skill_dir}"
        )
    source = asset_path(asset)
    source_digest = _skill_tree_sha256(source.parent)
    ownership_key = str(skill_dir.resolve())
    ownership_skills = ownership.setdefault("skills", {})
    if destination.exists():
        current_identity = _tree_identity(skill_dir)
        current_digest = current_identity[2]
        manageroo_owned = _is_manageroo_owned(
            skill_dir,
            skill_name,
            ownership,
            current_digest,
            source_digest,
        )
        if not manageroo_owned:
            ownership_skills.pop(ownership_key, None)
            return str(destination)
        if current_digest != source_digest:
            _replace_owned_skill(
                source.parent,
                skill_dir,
                root_real,
                expected_identity=current_identity,
            )
        ownership_skills[ownership_key] = {
            "name": skill_name,
            "tree_sha256": source_digest,
            "tree_hash_version": 2,
        }
        return str(destination)
    existing = _existing_skill_in_roots(skill_name, search_roots)
    if existing is not None:
        return str(existing)
    _replace_owned_skill(source.parent, skill_dir, root_real)
    ownership_skills[ownership_key] = {
        "name": skill_name,
        "tree_sha256": source_digest,
        "tree_hash_version": 2,
    }
    return str(destination)


def _install_skill_pack_transactionally(
    root: Path,
    items: list[tuple[str, str, str]],
    *,
    search_roots: list[Path],
    ownership_path: Path,
    retired_skill_names: tuple[str, ...] = (),
    finalize: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, str]:
    unresolved_root = root.expanduser()
    if unresolved_root.is_symlink():
        raise ValueError(f"Refusing to install through symlinked skills root: {unresolved_root}")
    unresolved_root.mkdir(parents=True, exist_ok=True)
    root_real = unresolved_root.resolve()
    with _skill_install_lock(root_real):
        ownership_before = _snapshot_file_bytes(ownership_path)
        ownership = _read_ownership(ownership_path)
        transaction = Path(tempfile.mkdtemp(prefix=".manageroo-skill-transaction-", dir=root_real))
        snapshots = transaction / "snapshots"
        snapshots.mkdir()
        retired_root = transaction / "retired"
        retired_root.mkdir()
        absent: set[str] = set()
        snapshotted: set[str] = set()
        written: dict[str, tuple[int, int, str]] = {}
        retired: dict[str, tuple[Path, tuple[int, int, str]]] = {}
        ownership_written = False
        ownership_written_bytes: bytes | None = None
        try:
            ownership_skills = ownership.setdefault("skills", {})
            for skill_name in retired_skill_names:
                skill_dir = root_real / skill_name
                ownership_key = str(skill_dir.resolve(strict=False))
                if skill_dir.is_symlink() or not skill_dir.is_dir():
                    ownership_skills.pop(ownership_key, None)
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_symlink() or not skill_file.is_file():
                    ownership_skills.pop(ownership_key, None)
                    continue
                current_identity = _tree_identity(skill_dir)
                if not _is_manageroo_owned(
                    skill_dir,
                    skill_name,
                    ownership,
                    current_identity[2],
                ):
                    ownership_skills.pop(ownership_key, None)
                    continue
                if not _same_tree_identity(skill_dir, current_identity):
                    raise RuntimeError(f"Skill tree changed during retirement: {skill_dir}")
                moved = retired_root / skill_name
                skill_dir.rename(moved)
                if not _same_tree_identity(moved, current_identity):
                    if not skill_dir.exists():
                        moved.rename(skill_dir)
                    raise RuntimeError(f"Skill tree changed during retirement: {skill_dir}")
                retired[skill_name] = (moved, current_identity)
                ownership_skills.pop(ownership_key, None)

            for _, skill_name, asset in items:
                skill_dir = unresolved_root / skill_name
                if not skill_dir.exists():
                    absent.add(skill_name)
                    continue
                current_digest = _skill_tree_sha256(skill_dir)
                bundled_digest = _skill_tree_sha256(asset_path(asset).parent)
                if _is_manageroo_owned(
                    skill_dir,
                    skill_name,
                    ownership,
                    current_digest,
                    bundled_digest,
                ):
                    shutil.copytree(skill_dir, snapshots / skill_name, symlinks=False)
                    snapshotted.add(skill_name)

            installed: dict[str, str] = {}
            for result_key, skill_name, asset in items:
                installed[result_key] = _install_bundled_skill(
                    unresolved_root,
                    skill_name,
                    asset,
                    search_roots=search_roots,
                    ownership=ownership,
                )
                skill_dir = unresolved_root / skill_name
                if skill_dir.is_dir() and not skill_dir.is_symlink():
                    written[skill_name] = _tree_identity(skill_dir)
            ownership_written_bytes = _json_file_bytes(ownership)
            atomic_write_json(ownership_path, ownership)
            ownership_written = True
            if finalize is not None:
                finalize(installed)
            return installed
        except Exception:
            try:
                for skill_name in snapshotted:
                    destination_dir = unresolved_root / skill_name
                    if not _same_tree_identity(destination_dir, written.get(skill_name)):
                        continue
                    shutil.rmtree(destination_dir)
                    shutil.copytree(snapshots / skill_name, destination_dir, symlinks=False)
                for skill_name in absent:
                    destination_dir = unresolved_root / skill_name
                    if _same_tree_identity(destination_dir, written.get(skill_name)):
                        shutil.rmtree(destination_dir)
                for skill_name, (moved, _) in retired.items():
                    if not moved.exists():
                        continue
                    destination_dir = root_real / skill_name
                    if not destination_dir.exists():
                        moved.rename(destination_dir)
                        continue
                    recovery = root_real / (
                        f".{skill_name}.manageroo-retired-recovery-{os.urandom(6).hex()}"
                    )
                    moved.rename(recovery)
            finally:
                if ownership_written and ownership_written_bytes is not None:
                    _restore_file_bytes_if_matches(
                        ownership_path,
                        ownership_written_bytes,
                        ownership_before,
                    )
            raise
        finally:
            if transaction.exists():
                shutil.rmtree(transaction, ignore_errors=True)


def install_core_helper_skills(
    skills_dir: Path | None = None,
    *,
    search_roots: list[Path] | None = None,
    ownership_path: Path | None = None,
) -> dict[str, str]:
    root = (skills_dir or token_mode_skills_dir()).expanduser()
    state_path = _ownership_file(root, ownership_path)
    roots = (
        list(search_roots)
        if search_roots is not None
        else (_default_search_roots(root) if skills_dir is None else [])
    )
    return _install_skill_pack_transactionally(
        root,
        [(skill_name, skill_name, asset) for skill_name, asset in CORE_SKILL_PACK.items()],
        search_roots=roots,
        ownership_path=state_path,
        retired_skill_names=RETIRED_CORE_SKILL_NAMES,
    )


def install_token_skills(
    skills_dir: Path | None = None,
    *,
    search_roots: list[Path] | None = None,
    ownership_path: Path | None = None,
    _finalize: Callable[[dict[str, str]], None] | None = None,
) -> dict[str, str]:
    root = (skills_dir or token_mode_skills_dir()).expanduser()
    state_path = _ownership_file(root, ownership_path)
    roots = (
        list(search_roots)
        if search_roots is not None
        else (_default_search_roots(root) if skills_dir is None else [])
    )
    items: list[tuple[str, str, str]] = []
    for mode in TOKEN_MODES.values():
        if not mode.skill_name or not mode.asset:
            continue
        items.append((mode.id, mode.skill_name, mode.asset))
    return _install_skill_pack_transactionally(
        root,
        items,
        search_roots=roots,
        ownership_path=state_path,
        finalize=_finalize,
    )


def read_token_mode(state_path: Path | None = None) -> dict[str, Any]:
    path = (state_path or token_mode_state_path()).expanduser()
    if not path.exists():
        return {
            "mode": "off",
            "label": TOKEN_MODES["off"].label,
            "state_path": str(path),
            "skills_dir": str(token_mode_skills_dir()),
            "installed_skills": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    mode = normalize_mode(str(data.get("mode", "off")))
    data["mode"] = mode
    data["label"] = TOKEN_MODES[mode].label
    data.setdefault("state_path", str(path))
    data.setdefault("skills_dir", str(token_mode_skills_dir()))
    data.setdefault("installed_skills", {})
    return data


def set_token_mode(
    mode: str,
    *,
    state_path: Path | None = None,
    skills_dir: Path | None = None,
    install_skills: bool = True,
) -> dict[str, Any]:
    normalized = normalize_mode(mode)
    path = (state_path or token_mode_state_path()).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "mode": normalized,
        "label": TOKEN_MODES[normalized].label,
        "selected_skill": TOKEN_MODES[normalized].skill_name,
        "state_path": str(path),
        "skills_dir": str((skills_dir or token_mode_skills_dir()).expanduser().resolve()),
        "installed_skills": {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if install_skills and normalized != "off":
        state_before = _snapshot_file_bytes(path)

        def write_state(installed: dict[str, str]) -> None:
            data["installed_skills"] = installed
            state_written_bytes = _json_file_bytes(data)
            try:
                atomic_write_json(path, data)
            except Exception:
                _restore_file_bytes_if_matches(path, state_written_bytes, state_before)
                raise

        install_token_skills(skills_dir, _finalize=write_state)
        return data
    atomic_write_json(path, data)
    return data


def token_mode_prompt(mode: str | None = None) -> str:
    selected = normalize_mode(mode) if mode is not None else read_token_mode()["mode"]
    prompt = TOKEN_MODES[selected].prompt
    if not prompt:
        return ""
    return "# Token reduction mode\n\n" + prompt
