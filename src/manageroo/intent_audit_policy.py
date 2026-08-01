from __future__ import annotations

from typing import Any

from .branding import PUBLIC_COMMAND


def install_intent_audit_policy(intent_lock_module: Any) -> None:
    original = intent_lock_module.audit_compaction_text
    if getattr(original, "_manageroo_confidence_policy", False):
        return

    def hardened(repo_path, summary_text: str, *, summary_path=None):
        report = original(repo_path, summary_text, summary_path=summary_path)
        if not report.get("ok") and not report.get("warnings"):
            return report
        lock_report = intent_lock_module.read_intent_lock(repo_path)
        lock = lock_report.get("lock", {}) if isinstance(lock_report, dict) else {}
        policy = lock.get("audit_policy", {}) if isinstance(lock, dict) else {}
        confidence_required = bool(
            isinstance(policy, dict) and policy.get("confidence_claims_require_evidence")
        )
        warnings = list(report.get("warnings", []) or [])
        proof = lock.get("proof", []) if isinstance(lock, dict) else []
        normalized_proof = [
            " ".join(str(item).casefold().split())
            for item in proof
            if str(item).strip()
        ] if isinstance(proof, (list, tuple)) else []
        unsupported_warnings = [
            warning
            for warning in warnings
            if not any(
                " ".join(str(warning.get("text", "")).casefold().split()) in evidence
                for evidence in normalized_proof
            )
        ]
        if confidence_required and unsupported_warnings:
            report["ok"] = False
            report["status"] = "blocked"
            report["confidence_claims_blocking"] = True
            report["next_command"] = f"{PUBLIC_COMMAND} intent show {report.get('repo', repo_path)}"
        else:
            report["confidence_claims_blocking"] = False
        return report

    hardened._manageroo_confidence_policy = True
    intent_lock_module.audit_compaction_text = hardened
