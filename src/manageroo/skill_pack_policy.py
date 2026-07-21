from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Skill tree must be a real directory: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError(f"Skill tree contains unsupported symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def install_skill_pack_policy(module: Any) -> None:
    if getattr(module, "_manageroo_skill_pack_policy_installed", False):
        return
    original_candidate = module._candidate

    def candidate(path: Path, source_root: Path, target_root: Path, seen: set[str]):
        item = original_candidate(path, source_root, target_root, seen)
        if item.get("status") not in {"already-present", "conflict"}:
            return item
        source_dir = path.parent
        target_dir = target_root / str(item.get("name") or "")
        try:
            source_digest = _tree_digest(source_dir)
            target_digest = _tree_digest(target_dir)
        except ValueError as exc:
            item["status"] = "blocked"
            item["reason"] = str(exc)
            return item
        item["tree_sha256"] = source_digest
        item["target_tree_sha256"] = target_digest
        if source_digest == target_digest:
            item["status"] = "already-present"
            item["reason"] = "complete skill tree already installed"
        else:
            item["status"] = "conflict"
            item["reason"] = "installed skill tree differs; import will transactionally back up the complete old tree"
        return item

    def transactional_replace(source_dir: Path, target_dir: Path, target_root: Path) -> str:
        source_files = module._validate_source_tree(source_dir)
        module._validate_destination_tree(target_dir, target_root)
        stage = Path(tempfile.mkdtemp(prefix=f".{target_dir.name}.manageroo-stage-", dir=str(target_root)))
        backup: Path | None = None
        try:
            for source_file in source_files:
                relative = source_file.relative_to(source_dir)
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, destination)
            if not (stage / "SKILL.md").is_file():
                raise ValueError(f"Staged skill is missing SKILL.md: {source_dir}")
            if target_dir.exists():
                backup = module._backup_path(target_dir)
                target_dir.rename(backup)
            try:
                stage.rename(target_dir)
            except Exception as swap_exc:
                restore_error: Exception | None = None
                if backup and backup.exists() and not target_dir.exists():
                    try:
                        backup.rename(target_dir)
                    except Exception as exc:
                        restore_error = exc
                if restore_error is not None:
                    raise RuntimeError(
                        f"Skill replacement failed: {swap_exc}; previous skill restoration failed: {restore_error}"
                    ) from swap_exc
                raise
            return str(backup) if backup else ""
        finally:
            if stage.exists() and stage != target_dir:
                try:
                    if stage.is_dir() and not stage.is_symlink():
                        shutil.rmtree(stage)
                    else:
                        stage.unlink()
                except OSError:
                    # Restoration has already been attempted independently above. Cleanup
                    # failure must not suppress the original swap/restoration result.
                    pass

    module._candidate = candidate
    module._transactional_replace_skill = transactional_replace
    module._manageroo_skill_pack_policy_installed = True
