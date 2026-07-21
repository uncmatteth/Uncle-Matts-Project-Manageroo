from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR, PUBLIC_COMMAND
from .errors import SafetyError
from .util import atomic_write_text, read_json


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
        if not isinstance(data, dict):
            return {
                "ok": False,
                "run_id": run_id,
                "result_path": str(result_path),
                "detail": "latest run final-result.json has an invalid schema: top-level value must be an object",
                "next": continuation,
            }
        for field in ("evidence_paths", "review"):
            value = data.get(field, {})
            if value is not None and not isinstance(value, dict):
                return {
                    "ok": False,
                    "run_id": run_id,
                    "result_path": str(result_path),
                    "detail": f"latest run final-result.json has an invalid schema: {field} must be an object",
                    "next": continuation,
                }
        return original_latest(repo)

    def release_ready_hardened(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = original_release_ready(*args, **kwargs)
        repo = Path(str(report.get("repo") or "")).expanduser().resolve()
        handoff_path = Path(str(report.get("handoff_path") or release_ready_module._handoff_path(repo)))

        # Render only from the authoritative final report. The original implementation
        # may have written a READY handoff before its post-write cleanliness check downgraded
        # the result, so overwrite that artifact after every final-state transition.
        handoff_markdown = release_ready_module._production_handoff_markdown(report)
        atomic_write_text(handoff_path, handoff_markdown)
        try:
            persisted = handoff_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SafetyError(f"Release handoff could not be read back after writing: {exc}") from exc

        expected_status = f"Status: {report.get('status')}"
        expected_decision = (
            "Ship when the human operator is ready."
            if report.get("ok")
            else "Do not ship yet."
        )
        if persisted != handoff_markdown or expected_status not in persisted or expected_decision not in persisted:
            raise SafetyError(
                "Persisted production handoff does not match the authoritative final release-readiness result."
            )
        if not report.get("ok") and "- None detected by `release-ready`." in persisted:
            raise SafetyError("Not-ready release handoff incorrectly claims there are no release blockers.")

        report["handoff_path"] = str(handoff_path)
        report["handoff_markdown"] = persisted
        report["handoff_verified"] = True
        return report

    release_ready_module._latest_manageroo_run_proof = _latest_manageroo_run_proof_hardened
    release_ready_module.release_ready = release_ready_hardened
    release_ready_module._manageroo_release_ready_policy_installed = True
