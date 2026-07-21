from __future__ import annotations

import re
from typing import Any


DEMONSTRATION_TERMS = (
    "browser",
    "journey",
    "demo",
    "deploy",
    "deployment",
    "security",
    "auth",
    "authentication",
    "authorization",
    "authorize",
    "authorized",
    "unauthorized",
    "login",
    "permission",
    "permissions",
    "access control",
    "access-control",
    "privilege",
    "privileges",
    "role",
    "roles",
    "policy",
    "screenshot",
    "visual",
    "checkout",
    "user can",
    "end user",
)


def _normalized(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _passed_gate_ids(gates: list[dict]) -> set[str]:
    passed: set[str] = set()
    for item in gates:
        if not isinstance(item, dict):
            continue
        gate = item.get("gate", {})
        result = item.get("result", {})
        if isinstance(gate, dict) and isinstance(result, dict) and result.get("exit_code") == 0:
            gate_id = str(gate.get("id") or "").strip()
            if gate_id:
                passed.add(gate_id)
    return passed


def _term_present(text: str, term: str) -> bool:
    normalized = _normalized(text)
    term_normalized = _normalized(term)
    if " " in term_normalized:
        return term_normalized in normalized
    return bool(re.search(rf"(?<![\w-]){re.escape(term_normalized)}(?![\w-])", normalized))


def _needs_demonstration(description: str) -> bool:
    return any(_term_present(description, term) for term in DEMONSTRATION_TERMS)


def _bindings(demonstration: dict) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list(demonstration.get("product_evidence", []) or []):
        if not isinstance(item, dict):
            continue
        outcome = _normalized(item.get("outcome"))
        gate_ids = [str(value).strip() for value in item.get("gate_ids", []) if str(value).strip()]
        if not outcome or not gate_ids:
            continue
        grouped.setdefault(outcome, []).append(
            {"outcome": str(item.get("outcome") or ""), "gate_ids": gate_ids}
        )
    return grouped


def build_acceptance_evidence(
    *,
    product: dict,
    gate_results: list[dict],
    demonstration: dict,
    review: dict,
) -> list[dict]:
    """Prove each requested outcome independently instead of sharing generic green checks."""

    passed_gates = _passed_gate_ids(gate_results)
    demo_gates = _passed_gate_ids(list(demonstration.get("gates", []) or []))
    all_passed = passed_gates | demo_gates
    review_approved = review.get("status") == "approved"
    bindings = _bindings(demonstration)
    rows: list[dict] = []

    for raw_outcome in product.get("acceptance_outcomes", []):
        description = str(raw_outcome)
        matches = bindings.get(_normalized(description), [])
        if len(matches) != 1:
            rows.append(
                {
                    "description": description,
                    "status": "unknown",
                    "evidence": [],
                    "reason": (
                        "Outcome-specific proof binding is missing."
                        if not matches
                        else "Outcome has duplicate proof bindings and is therefore ambiguous."
                    ),
                }
            )
            continue

        required_gate_ids = set(matches[0]["gate_ids"])
        missing = sorted(required_gate_ids - all_passed)
        if missing:
            rows.append(
                {
                    "description": description,
                    "status": "failed",
                    "evidence": [f"gate:{gate_id}" for gate_id in sorted(required_gate_ids & all_passed)],
                    "reason": "Bound proof gates did not pass: " + ", ".join(missing),
                }
            )
            continue

        if _needs_demonstration(description) and not (required_gate_ids & demo_gates):
            rows.append(
                {
                    "description": description,
                    "status": "unknown",
                    "evidence": [f"gate:{gate_id}" for gate_id in sorted(required_gate_ids)],
                    "reason": (
                        "This outcome describes observable, security, authorization, access-control, "
                        "or user-journey behavior but none of its bound proof gates ran in the demonstration lane."
                    ),
                }
            )
            continue

        if not review_approved:
            rows.append(
                {
                    "description": description,
                    "status": "failed",
                    "evidence": [f"gate:{gate_id}" for gate_id in sorted(required_gate_ids)],
                    "reason": "Independent review did not approve the verified implementation.",
                }
            )
            continue

        evidence = [f"gate:{gate_id}" for gate_id in sorted(required_gate_ids)]
        evidence.append("review:approved")
        rows.append(
            {
                "description": description,
                "status": "passed",
                "evidence": evidence,
                "reason": "Every gate explicitly bound to this outcome passed and independent review approved.",
            }
        )
    return rows
