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


def operator_reuse_directives(brief: str) -> list[str]:
    directives = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", brief):
        value = sentence.strip()
        if value and _OPERATOR_REUSE_VERB.search(value) and _OPERATOR_SOURCE_CUE.search(value):
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
