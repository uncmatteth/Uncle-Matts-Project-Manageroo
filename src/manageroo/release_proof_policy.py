from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .util import atomic_write_json, read_json, sha256_file


def _tracked_index_entries(repo: Path, runner: Any) -> dict[str, tuple[str, str]]:
    result = runner.run(
        ["git", "ls-files", "-s", "-z", "--cached"],
        cwd=repo,
        timeout_seconds=120,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "Could not enumerate tracked source tree for release proof")
    entries: dict[str, tuple[str, str]] = {}
    for record in result.stdout.split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        parts = metadata.split()
        if not separator or len(parts) < 3:
            raise RuntimeError(f"Unexpected git ls-files record: {record!r}")
        mode, object_id, stage = parts[0], parts[1], parts[2]
        if stage != "0":
            raise RuntimeError(f"Unmerged index entry cannot be release-certified: {relative}")
        entries[relative] = (mode, object_id)
    return entries


def _untracked_paths(repo: Path, runner: Any) -> list[str]:
    result = runner.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        cwd=repo,
        timeout_seconds=120,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "Could not enumerate untracked source tree for release proof")
    return sorted(item for item in result.stdout.split("\0") if item)


def source_tree_digest(repo: Path, runner: Any) -> str:
    """Hash Git-visible source state, including tracked gitlinks and untracked files."""
    repo = repo.expanduser().resolve()
    digest = hashlib.sha256()
    tracked = _tracked_index_entries(repo, runner)

    for relative in sorted(tracked):
        mode_text, object_id = tracked[relative]
        path = repo / relative
        if mode_text == "160000":
            # A submodule is represented by its pinned commit in the Git index. Hashing
            # that gitlink makes release proof change whenever the dependency revision changes.
            kind = b"gitlink"
            content_hash = object_id
        elif path.is_symlink():
            kind = b"symlink"
            target = path.readlink().as_posix().encode("utf-8", errors="surrogateescape")
            content_hash = hashlib.sha256(target).hexdigest()
        elif path.is_file():
            kind = mode_text.encode("ascii")
            content_hash = sha256_file(path)
        else:
            # Missing tracked paths are part of the current source state too.
            kind = ("missing:" + mode_text).encode("ascii")
            content_hash = object_id
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(kind)
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\0")

    for relative in _untracked_paths(repo, runner):
        path = repo / relative
        if path.is_symlink():
            kind = b"untracked-symlink"
            target = path.readlink().as_posix().encode("utf-8", errors="surrogateescape")
            content_hash = hashlib.sha256(target).hexdigest()
        elif path.is_file():
            kind = b"untracked-file"
            content_hash = sha256_file(path)
        else:
            continue
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(kind)
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _git_head(repo: Path, runner: Any) -> str:
    result = runner.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        timeout_seconds=120,
    )
    head = result.stdout.strip() if result.passed else ""
    if not head:
        raise RuntimeError(result.stderr or "Could not resolve Git HEAD for release proof")
    return head


def _reviewed_patch_digest(orchestrator: Any) -> str:
    result = orchestrator.runner.run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--binary",
            orchestrator.mirror.baseline_commit,
            "HEAD",
            "--",
        ],
        cwd=orchestrator.workspace,
        timeout_seconds=300,
    )
    if not result.passed:
        raise RuntimeError(result.stderr or "Could not reconstruct the reviewed final patch")
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def install_release_proof_policy(orchestrator_module: Any) -> None:
    orchestrator_class = orchestrator_module.Orchestrator
    if getattr(orchestrator_class, "_manageroo_release_proof_policy_installed", False):
        return
    original_run = orchestrator_class.run

    def run_with_bound_proof(self: Any, *args: Any, **kwargs: Any):
        run_git_head = _git_head(self.source_repo, self.runner)
        final_result_path = self.run_root / "delivery" / "final-result.json"
        preexisting_complete: dict[str, Any] | None = None
        if final_result_path.is_file():
            saved = read_json(final_result_path)
            if (
                isinstance(saved, dict)
                and saved.get("status") == "COMPLETE"
                and saved.get("applied_to_source") is True
            ):
                preexisting_complete = saved
        result = original_run(self, *args, **kwargs)
        if not isinstance(result, dict) or result.get("status") != "COMPLETE":
            return result

        def block(message: str) -> None:
            result.update(
                {
                    "status": "BLOCKED",
                    "error_type": "SafetyError",
                    "error": message,
                }
            )

        if preexisting_complete is not None:
            saved_head = str(preexisting_complete.get("verified_git_head") or "").strip()
            if not saved_head:
                block("Existing completed run has no run-bound Git HEAD proof.")
            elif saved_head != run_git_head:
                block("Existing completed run was verified at another Git HEAD.")
            else:
                return result
        elif _git_head(self.source_repo, self.runner) != run_git_head:
            block("Source repository HEAD changed before completed-run proof was bound.")
        else:
            evidence_paths = result.get("evidence_paths")
            patch_value = evidence_paths.get("patch") if isinstance(evidence_paths, dict) else None
            patch_path = (
                Path(patch_value)
                if patch_value
                else self.run_root / "delivery" / "final.patch"
            )
            expected_patch_digest = _reviewed_patch_digest(self)
            patch_digest_before = sha256_file(patch_path) if patch_path.is_file() else ""
            digest = source_tree_digest(self.source_repo, self.runner)
            patch_digest_after = sha256_file(patch_path) if patch_path.is_file() else ""
            if (
                patch_digest_before != expected_patch_digest
                or patch_digest_after != expected_patch_digest
            ):
                block("Final patch changed before completed-run proof was bound.")
            elif _git_head(self.source_repo, self.runner) != run_git_head:
                block("Source repository HEAD changed while completed-run proof was bound.")
            else:
                result["verified_source_tree_sha256"] = digest
                result["verified_git_head"] = run_git_head
                result["final_patch_sha256"] = expected_patch_digest
        if final_result_path.is_file():
            persisted = read_json(final_result_path)
            if isinstance(persisted, dict):
                persisted.update(result)
                atomic_write_json(final_result_path, persisted)
        return result

    orchestrator_class.run = run_with_bound_proof
    orchestrator_class._manageroo_release_proof_policy_installed = True
