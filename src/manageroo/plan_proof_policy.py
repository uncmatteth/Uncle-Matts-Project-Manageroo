from __future__ import annotations

from collections import Counter
from typing import Any

from .acceptance import _needs_demonstration, _normalized


def proof_binding_findings(
    *,
    product: dict,
    plan: dict,
    available_gate_ids: set[str],
) -> list[dict]:
    """Return deterministic plan-review findings for invalid proof bindings."""

    findings: list[dict] = []
    outcomes = [str(item) for item in product.get("acceptance_outcomes", [])]
    normalized_outcomes = [_normalized(item) for item in outcomes]
    outcome_counts = Counter(normalized_outcomes)
    for normalized, count in sorted(outcome_counts.items()):
        if normalized and count > 1:
            findings.append(
                {
                    "id": f"PROOF-DUPLICATE-OUTCOME-{len(findings) + 1}",
                    "severity": "high",
                    "problem": "Product model contains duplicate acceptance outcomes after normalization.",
                    "required_change": "Keep each independently provable acceptance outcome exactly once.",
                }
            )

    demonstration = plan.get("demonstration", {})
    demo_gate_ids = {
        str(item).strip()
        for item in demonstration.get("gate_ids", [])
        if str(item).strip()
    }
    unknown_demo = sorted(demo_gate_ids - available_gate_ids)
    if unknown_demo:
        findings.append(
            {
                "id": "PROOF-UNKNOWN-DEMO-GATES",
                "severity": "high",
                "problem": "Demonstration references unknown gate IDs: " + ", ".join(unknown_demo),
                "required_change": "Use only configured deterministic gate IDs.",
            }
        )

    bindings: dict[str, list[dict]] = {}
    for item in demonstration.get("product_evidence", []) or []:
        if not isinstance(item, dict):
            continue
        key = _normalized(item.get("outcome"))
        bindings.setdefault(key, []).append(item)

    known_outcomes = set(normalized_outcomes)
    unknown_bindings = sorted(key for key in bindings if key and key not in known_outcomes)
    for key in unknown_bindings:
        findings.append(
            {
                "id": f"PROOF-UNKNOWN-OUTCOME-{len(findings) + 1}",
                "severity": "high",
                "problem": f"Proof binding targets an unknown or paraphrased outcome: {key}",
                "required_change": "Copy the acceptance outcome text exactly into product_evidence.",
            }
        )

    for description, key in zip(outcomes, normalized_outcomes):
        matches = bindings.get(key, [])
        if len(matches) != 1:
            findings.append(
                {
                    "id": f"PROOF-BINDING-{len(findings) + 1}",
                    "severity": "high",
                    "problem": (
                        f"Acceptance outcome must have exactly one proof binding: {description}"
                    ),
                    "required_change": "Add one unambiguous product_evidence binding for this exact outcome.",
                }
            )
            continue

        gate_ids = {
            str(item).strip()
            for item in matches[0].get("gate_ids", [])
            if str(item).strip()
        }
        unknown = sorted(gate_ids - available_gate_ids)
        if unknown:
            findings.append(
                {
                    "id": f"PROOF-UNKNOWN-GATES-{len(findings) + 1}",
                    "severity": "high",
                    "problem": (
                        f"Outcome proof binding references unknown gates for {description}: "
                        + ", ".join(unknown)
                    ),
                    "required_change": "Bind only configured gate IDs.",
                }
            )
        if _needs_demonstration(description) and not (gate_ids & demo_gate_ids):
            findings.append(
                {
                    "id": f"PROOF-DEMONSTRATION-{len(findings) + 1}",
                    "severity": "high",
                    "problem": (
                        "Observable, security, deployment, visual, authentication, or user-journey "
                        f"outcome has no bound demonstration gate: {description}"
                    ),
                    "required_change": (
                        "Bind at least one proving gate that is also listed in demonstration.gate_ids."
                    ),
                }
            )
    return findings


def install_plan_proof_policy(orchestrator_module: Any) -> None:
    original = orchestrator_module.Orchestrator._plan_context_preflight

    def strict_preflight(self: Any, plan: dict, inventory: list[dict]) -> list[dict]:
        findings = list(original(self, plan, inventory))
        product = self._artifact_json("planning/product-model.json") or {}
        findings.extend(
            proof_binding_findings(
                product=product,
                plan=plan,
                available_gate_ids=set(self._gate_catalog()),
            )
        )
        return findings

    orchestrator_module.Orchestrator._plan_context_preflight = strict_preflight
