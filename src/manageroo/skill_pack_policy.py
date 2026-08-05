from __future__ import annotations

from pathlib import Path
from typing import Any


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
            source_digest = str(item["tree_sha256"])
            target_digest = module._validated_source_tree_sha256(target_dir)
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

    module._candidate = candidate
    module._manageroo_skill_pack_policy_installed = True
