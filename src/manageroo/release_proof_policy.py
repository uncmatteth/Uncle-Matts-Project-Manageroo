from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .util import atomic_write_json, read_json, sha256_file


def source_tree_digest(repo: Path, runner: Any) -> str:
    """Hash the complete Git-visible source state, including mode and untracked files."""
    repo = repo.expanduser().resolve()
    result = runner.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        timeout_seconds=120,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "Could not enumerate source tree for release proof")
    digest = hashlib.sha256()
    for relative in sorted(item for item in result.stdout.split("\0") if item):
        path = repo / relative
        if path.is_symlink():
            target = path.readlink().as_posix().encode("utf-8", errors="surrogateescape")
            mode = b"symlink"
            content_hash = hashlib.sha256(target).hexdigest()
        elif path.is_file():
            mode = oct(path.stat().st_mode & 0o777).encode("ascii")
            content_hash = sha256_file(path)
        else:
            continue
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(mode)
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def install_release_proof_policy(orchestrator_module: Any) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_release_proof_policy_installed", False):
        return
    original_run = orchestrator_class.run

    def run_with_bound_proof(self: Any, *args: Any, **kwargs: Any):
        result = original_run(self, *args, **kwargs)
        if not isinstance(result, dict) or result.get("status") != "COMPLETE":
            return result
        digest = source_tree_digest(self.source_repo, self.runner)
        result["verified_source_tree_sha256"] = digest
        patch_value = result.get("evidence_paths", {}).get("patch")
        patch_path = Path(patch_value) if patch_value else self.run_root / "delivery" / "final.patch"
        result["final_patch_sha256"] = sha256_file(patch_path) if patch_path.is_file() else ""
        final_result_path = self.run_root / "delivery" / "final-result.json"
        if final_result_path.is_file():
            persisted = read_json(final_result_path)
            if isinstance(persisted, dict):
                persisted.update(
                    {
                        "verified_source_tree_sha256": result["verified_source_tree_sha256"],
                        "final_patch_sha256": result["final_patch_sha256"],
                    }
                )
                atomic_write_json(final_result_path, persisted)
        return result

    orchestrator_class.run = run_with_bound_proof
    orchestrator_class._manageroo_release_proof_policy_installed = True
