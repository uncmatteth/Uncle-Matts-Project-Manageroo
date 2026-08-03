from __future__ import annotations

import os
import shlex
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .errors import SafetyError
from .util import atomic_write_text, read_json


@contextmanager
def _hold_release_head(release_ready_module: Any, repo: Path) -> Iterator[str]:
    """Prevent Git from moving the candidate HEAD while release evidence is finalized."""
    head = release_ready_module._git_output(repo, ["git", "rev-parse", "HEAD"])
    symbolic_ref = release_ready_module._git_output(
        repo, ["git", "symbolic-ref", "-q", "HEAD"]
    )
    if not head:
        raise SafetyError("Release candidate HEAD could not be resolved.")
    ref = symbolic_ref or "HEAD"
    try:
        transaction = subprocess.Popen(
            ["git", "-c", f"core.hooksPath={os.devnull}", "update-ref", "--stdin"],
            cwd=repo,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise SafetyError(f"Could not start the release HEAD transaction: {exc}") from exc
    if transaction.stdin is None or transaction.stdout is None or transaction.stderr is None:
        transaction.kill()
        transaction.wait()
        raise SafetyError("Could not open the release HEAD transaction pipes.")

    try:
        transaction.stdin.write(f"start\nupdate {ref} {head} {head}\nprepare\n")
        transaction.stdin.flush()
        responses = [transaction.stdout.readline().strip(), transaction.stdout.readline().strip()]
        if responses != ["start: ok", "prepare: ok"]:
            transaction.stdin.close()
            transaction.wait(timeout=5)
            detail = transaction.stderr.read().strip() or "; ".join(responses)
            raise SafetyError(f"Could not lock the release candidate HEAD: {detail}")
        yield head
    finally:
        cleanup_error: SafetyError | None = None
        response = ""
        if transaction.poll() is None:
            try:
                transaction.stdin.write("abort\n")
                transaction.stdin.flush()
                response = transaction.stdout.readline().strip()
                transaction.stdin.close()
                transaction.wait(timeout=5)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired) as exc:
                transaction.kill()
                transaction.wait()
                cleanup_error = SafetyError(
                    f"Could not release the release candidate HEAD transaction: {exc}"
                )
            if cleanup_error is None and (
                response != "abort: ok" or transaction.returncode != 0
            ):
                detail = transaction.stderr.read().strip() or response
                cleanup_error = SafetyError(
                    f"Could not release the release candidate HEAD transaction: {detail}"
                )
        for stream in (transaction.stdin, transaction.stdout, transaction.stderr):
            if not stream.closed:
                stream.close()
        if cleanup_error is not None:
            raise cleanup_error


def install_release_ready_policy(release_ready_module: Any) -> None:
    if getattr(release_ready_module, "_manageroo_release_ready_policy_installed", False):
        return

    original_latest = release_ready_module._latest_manageroo_run_proof
    original_release_ready = release_ready_module.release_ready

    def _latest_manageroo_run_proof_hardened(repo: Path) -> dict[str, Any]:
        results = sorted(
            (repo / PROJECT_DIR / "runs").glob("*/delivery/final-result.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not results:
            return original_latest(repo)
        result_path = results[0]
        run_id = result_path.parents[1].name
        continuation = shlex.join(
            [PUBLIC_COMMAND, "run", "--continue", run_id, "--repo", str(repo), "--apply"]
        )
        try:
            data = read_json(result_path)
        except Exception:
            return original_latest(repo)

        def invalid_schema(detail: str) -> dict[str, Any]:
            return {
                "ok": False,
                "run_id": run_id,
                "result_path": str(result_path),
                "detail": f"latest run final-result.json has an invalid schema: {detail}",
                "next": continuation,
            }

        if not isinstance(data, dict):
            return invalid_schema("top-level value must be an object")
        for field in ("evidence_paths", "review"):
            if not isinstance(data.get(field), dict):
                return invalid_schema(f"{field} must be an object")

        evidence_paths = data["evidence_paths"]
        expected_strings = (
            ("status", data.get("status")),
            ("review.status", data["review"].get("status")),
            ("verified_source_tree_sha256", data.get("verified_source_tree_sha256")),
            ("final_patch_sha256", data.get("final_patch_sha256")),
        )
        for field, value in expected_strings:
            if not isinstance(value, str):
                return invalid_schema(f"{field} must be a string")
        if "patch" in evidence_paths and not isinstance(evidence_paths["patch"], str):
            return invalid_schema("evidence_paths.patch must be a string")
        if not isinstance(data.get("applied_to_source"), bool):
            return invalid_schema("applied_to_source must be a boolean")
        return original_latest(repo)

    def release_ready_hardened(*args: Any, **kwargs: Any) -> dict[str, Any]:
        repo_arg = args[0] if args else kwargs.get("repo_path")
        repo = release_ready_module.git_root(Path(repo_arg))
        with _hold_release_head(release_ready_module, repo) as release_head:
            report = original_release_ready(*args, **kwargs)
            handoff_path = Path(
                str(report.get("handoff_path") or release_ready_module._handoff_path(repo))
            )

            # Render only from the authoritative final report. The original implementation
            # may have written a READY handoff before its post-write cleanliness check downgraded
            # the result, so overwrite that artifact after every final-state transition.
            handoff_markdown = release_ready_module._production_handoff_markdown(report)
            atomic_write_text(handoff_path, handoff_markdown)
            try:
                persisted = handoff_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise SafetyError(
                    f"Release handoff could not be read back after writing: {exc}"
                ) from exc

            if report.get("ok"):
                failures: list[str] = []
                head_before = release_ready_module._git_output(
                    repo, ["git", "rev-parse", "HEAD"]
                )
                expected_digest = str(
                    report.get("manageroo_run", {}).get("verified_source_tree_sha256") or ""
                ).strip()
                try:
                    final_digest = release_ready_module.source_tree_digest(
                        repo, release_ready_module.CommandRunner()
                    )
                except Exception as exc:
                    failures.append(f"final source-tree digest could not be computed: {exc}")
                else:
                    if final_digest != expected_digest:
                        failures.append("source tree changed after completed-run proof")
                clean, status_text = release_ready_module._git_status(repo)
                head_after = release_ready_module._git_output(
                    repo, ["git", "rev-parse", "HEAD"]
                )
                if head_before != release_head or head_after != release_head:
                    failures.append("HEAD changed while release evidence was finalized")
                if not clean:
                    failures.append(
                        "Git worktree changed while release evidence was finalized"
                        + (f": {status_text}" if status_text else "")
                    )
                if failures:
                    report["ok"] = False
                    report["status"] = "NOT READY FOR RELEASE"
                    report["git_status"] = status_text
                    report["items"].append(
                        release_ready_module._item(
                            "source integrity after release evidence",
                            False,
                            "; ".join(failures),
                            "git status --short",
                        )
                    )
                    report["next_commands"] = ["git status --short"]
                    handoff_markdown = release_ready_module._production_handoff_markdown(report)
                    atomic_write_text(handoff_path, handoff_markdown)
                    persisted = handoff_path.read_text(encoding="utf-8")

            expected_status = f"Status: {report.get('status')}"
            expected_decision = (
                "Ship when the human operator is ready."
                if report.get("ok")
                else "Do not ship yet."
            )
            if (
                persisted != handoff_markdown
                or expected_status not in persisted
                or expected_decision not in persisted
            ):
                raise SafetyError(
                    "Persisted production handoff does not match the authoritative final release-readiness result."
                )
            if not report.get("ok") and "- None detected by `release-ready`." in persisted:
                raise SafetyError(
                    "Not-ready release handoff incorrectly claims there are no release blockers."
                )

            report["handoff_path"] = str(handoff_path)
            report["handoff_markdown"] = persisted
            report["handoff_verified"] = True
            return report

    release_ready_module._latest_manageroo_run_proof = _latest_manageroo_run_proof_hardened
    release_ready_module.release_ready = release_ready_hardened
    release_ready_module._manageroo_release_ready_policy_installed = True
