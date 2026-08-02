from __future__ import annotations

import re
from typing import Any

from .branding import PUBLIC_COMMAND


_NEGATION_IN_CLAUSE = re.compile(
    r"\b(?:cannot|can't|did not|didn't|do not|don't|failed|fails|failing|is not|isn't|"
    r"must not|mustn't|never|no|not|should not|shouldn't|unsuccessful|unproven|"
    r"unsupported|without)\b",
    re.IGNORECASE,
)
_SUCCESS_OUTCOME = re.compile(
    r"\b(?:approved|confirmed|evidenced|green|passed|passes|passing|proven|succeeded|"
    r"successful|supported|verified)\b",
    re.IGNORECASE,
)
_AFTER_CLAIM_SUPPORT = re.compile(
    r"^\s*(?:(?:is|was)\s+(?:now\s+)?(?:approved|confirmed|evidenced|proven|supported|verified)\b|"
    r"(?:after|based on|because|by|following|from|with)\b|[:\-–—])",
    re.IGNORECASE,
)
_BEFORE_CLAIM_LINK = re.compile(
    r"\b(?:confirming|making|so|therefore|thus)\s+(?:(?:the\s+)?(?:build|release|result|status)\s+(?:is|was)\s+)?$",
    re.IGNORECASE,
)
_AFFIRMATIVE_CLAIM_PREFIX = re.compile(
    r"^\s*(?:(?:the\s+)?(?:build|release|result|status)\s+(?:is|was)\s+)?$",
    re.IGNORECASE,
)
_NONAFFIRMATIVE_CLAIM_STATE = re.compile(
    r"^\s*(?:(?:is|was|remains?)\s+)?(?:pending|unknown|unconfirmed|unproven|unverified)\b",
    re.IGNORECASE,
)
_BENIGN_NEGATIVE_OUTCOME = re.compile(
    r"\b(?:no|zero)\s+(?:errors?|failures?)\b|\bwithout\s+(?:errors?|failures?)\b",
    re.IGNORECASE,
)
_QUOTE_PAIRS = (("\"", "\""), ("'", "'"), ("`", "`"), ("“", "”"), ("‘", "’"))


def _inside_quoted_span(text: str, start: int, end: int) -> bool:
    for opening, closing in _QUOTE_PAIRS:
        cursor = 0
        while True:
            left = text.find(opening, cursor)
            if left < 0:
                break
            right = text.find(closing, left + len(opening))
            if right < 0:
                if left < start:
                    return True
                break
            if left < start and end <= right:
                return True
            cursor = right + len(closing)
    return False


def _affirmatively_supports_claim(evidence: str, claim: str) -> bool:
    if not claim:
        return False
    start = 0
    while True:
        index = evidence.find(claim, start)
        if index < 0:
            return False
        end = index + len(claim)
        before = evidence[:index]
        after = evidence[end:]
        quoted = _inside_quoted_span(evidence, index, end)
        clause_start = max(before.rfind(delimiter) for delimiter in ".!?;:\n") + 1
        following_boundaries = [
            boundary
            for delimiter in ".!?;:\n"
            if (boundary := after.find(delimiter)) >= 0
        ]
        clause_end = end + (min(following_boundaries) if following_boundaries else len(after))
        clause_prefix = evidence[clause_start:index]
        support = evidence[end:clause_end]
        support_without_benign_negation = _BENIGN_NEGATIVE_OUTCOME.sub("", support)
        claim_first_support = (
            _AFTER_CLAIM_SUPPORT.search(support)
            and _SUCCESS_OUTCOME.search(support)
            and not _NEGATION_IN_CLAUSE.search(support_without_benign_negation)
        )
        linked_prefix_support = bool(
            _BEFORE_CLAIM_LINK.search(clause_prefix)
            and _SUCCESS_OUTCOME.search(clause_prefix)
            and not _NEGATION_IN_CLAUSE.search(
                _BENIGN_NEGATIVE_OUTCOME.sub("", clause_prefix)
            )
        )
        previous_clause_support = False
        if _AFFIRMATIVE_CLAIM_PREFIX.fullmatch(clause_prefix):
            previous_end = clause_start - 1
            if previous_end >= 0:
                earlier = evidence[:previous_end]
                previous_start = max(earlier.rfind(delimiter) for delimiter in ".!?;:\n") + 1
                previous_clause = earlier[previous_start:]
                previous_clause_support = bool(
                    _SUCCESS_OUTCOME.search(previous_clause)
                    and not _NEGATION_IN_CLAUSE.search(
                        _BENIGN_NEGATIVE_OUTCOME.sub("", previous_clause)
                    )
                )
        if (
            not quoted
            and not _NEGATION_IN_CLAUSE.search(clause_prefix)
            and not _NONAFFIRMATIVE_CLAIM_STATE.search(support)
            and (claim_first_support or linked_prefix_support or previous_clause_support)
        ):
            return True
        start = end


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
                _affirmatively_supports_claim(
                    evidence,
                    " ".join(str(warning.get("text", "")).casefold().split()),
                )
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
