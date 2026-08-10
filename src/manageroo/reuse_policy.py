from __future__ import annotations

import re
from typing import Any


_REUSE_METHODS = {
    "reuse-internal": {"reuse-as-is", "adapt-existing"},
    "reuse-external": {"reuse-as-is", "adapt-existing"},
    "platform-native": {"reuse-as-is", "adapt-existing"},
    "build-custom": {"build-custom"},
    "defer": {"defer"},
}

_OPERATOR_REUSE_VERB = re.compile(r"\b(?:use|reuse|copy|port)\b", re.IGNORECASE)
_OPERATOR_SOURCE_CUE = re.compile(
    r"\b(?:existing|already|finished|authoritative|source|renderer|from|commit)\b|"
    r"(?:^|\s)[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+",
    re.IGNORECASE,
)
_NEGATED_REUSE = re.compile(r"\b(?:do\s+not|don't|never|without)\b", re.IGNORECASE)
_QUESTION_PREFIX = re.compile(
    r"^(?:why|what|when|where|who|how|should|could|would|did|does|do|is|are|was|were|has|have|had)\b",
    re.IGNORECASE,
)
_EXPLICIT_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|[0-9a-f]{7,40})(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)


def _affirmative_reuse(sentence: str) -> bool:
    for match in _OPERATOR_REUSE_VERB.finditer(sentence):
        prefix = sentence[: match.start()].strip().lower()
        prefix = re.sub(r"^(?:(?:>+|[-*+]|\d+[.)])\s*)+", "", prefix)
        if _NEGATED_REUSE.search(prefix) or _QUESTION_PREFIX.match(prefix):
            continue
        if not prefix or re.fullmatch(r"(?:(?:please|now|then|also|yes|ok|okay)\s+)*", prefix):
            return True
        if re.search(
            r"(?:\bi\s+(?:want|need|told|asked|instructed)\b|\byou\s+(?:must|need|have)\b|"
            r"\bgo\s+ahead\b|\b(?:and|then|also)\s*)$",
            prefix,
        ):
            return True
    return False


def _explicit_candidates(directive: str) -> list[str]:
    return list(
        dict.fromkeys(
            match.group(1).rstrip(".,:;")
            for match in _EXPLICIT_CANDIDATE.finditer(directive)
        )
    )


def operator_reuse_directives(brief: str) -> list[str]:
    directives = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", brief):
        value = sentence.strip()
        if value and _affirmative_reuse(value) and _OPERATOR_SOURCE_CUE.search(value):
            directives.append(value)
    return directives


def operator_reuse_findings(*, brief: str, reuse: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    decisions = [item for item in reuse.get("decisions", []) or [] if isinstance(item, dict)]
    for directive in operator_reuse_directives(brief):
        matches = [
            item
            for item in decisions
            if directive in [str(value) for value in item.get("evidence", []) or []]
            and item.get("decision") in {"reuse-internal", "reuse-external", "platform-native"}
        ]
        if len(matches) != 1:
            findings.append(
                {
                    "id": f"OPERATOR-REUSE-{len(findings) + 1}",
                    "severity": "high",
                    "problem": f"Operator reuse directive was omitted, weakened, or reclassified: {directive}",
                    "required_change": (
                        "Copy the directive exactly into one reuse decision's evidence and select "
                        "reuse-internal, reuse-external, or platform-native. Do not build a replacement."
                    ),
                }
            )
            continue
        candidates = _explicit_candidates(directive)
        selected = str(matches[0].get("candidate") or "")
        if candidates and any(candidate not in selected for candidate in candidates):
            findings.append(
                {
                    "id": f"OPERATOR-REUSE-{len(findings) + 1}",
                    "severity": "high",
                    "problem": (
                        "Reuse decision does not name every explicit operator candidate: "
                        f"{', '.join(candidates)}"
                    ),
                    "required_change": (
                        "Bind the decision candidate to the exact path or identifier named by "
                        "the operator; do not substitute another source."
                    ),
                }
            )
    return findings


def reuse_binding_findings(*, reuse: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, str]]:
    """Bind reuse research to the plan instead of leaving it as advisory prose."""
    findings: list[dict[str, str]] = []
    bindings: dict[str, list[dict[str, Any]]] = {}
    for binding in plan.get("reuse_bindings", []) or []:
        if isinstance(binding, dict):
            bindings.setdefault(str(binding.get("need") or ""), []).append(binding)

    for decision in reuse.get("decisions", []) or []:
        if not isinstance(decision, dict):
            continue
        need = str(decision.get("need") or "")
        expected_decision = str(decision.get("decision") or "")
        expected_candidate = str(decision.get("candidate") or "")
        matches = bindings.get(need, [])
        if len(matches) != 1:
            findings.append(
                {
                    "id": f"REUSE-BINDING-{len(findings) + 1}",
                    "severity": "high",
                    "problem": f"Reuse decision for {need!r} has no single exact plan binding.",
                    "required_change": "Bind the locked reuse decision exactly once before implementation.",
                }
            )
            continue
        binding = matches[0]
        if (
            binding.get("decision") != expected_decision
            or binding.get("candidate") != expected_candidate
        ):
            findings.append(
                {
                    "id": f"REUSE-SOURCE-{len(findings) + 1}",
                    "severity": "high",
                    "problem": f"Plan changed the locked reuse source or decision for {need!r}.",
                    "required_change": "Copy the reuse decision and candidate exactly; do not substitute another source.",
                }
            )
            continue
        implementation = str(binding.get("implementation") or "")
        if implementation not in _REUSE_METHODS.get(expected_decision, set()):
            findings.append(
                {
                    "id": f"REUSE-METHOD-{len(findings) + 1}",
                    "severity": "high",
                    "problem": (
                        f"Plan replaces locked {expected_decision} work for {need!r} with "
                        f"{implementation or 'an unspecified method'}."
                    ),
                    "required_change": "Reuse or adapt the named candidate; custom replacement requires a new operator request.",
                }
            )
        if str(binding.get("deviation") or "").strip():
            findings.append(
                {
                    "id": f"REUSE-DEVIATION-{len(findings) + 1}",
                    "severity": "high",
                    "problem": f"Plan declares an unauthorized substitution for {need!r}.",
                    "required_change": "Stop and report the deviation; do not implement it under the current locked request.",
                }
            )
    return findings
