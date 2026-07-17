import unittest

from manageroo.plan_proof_policy import proof_binding_findings


class PlanProofPolicyTests(unittest.TestCase):
    def test_missing_binding_is_rejected_before_implementation(self):
        findings = proof_binding_findings(
            product={"acceptance_outcomes": ["Checkout works"]},
            plan={"demonstration": {"gate_ids": [], "product_evidence": []}},
            available_gate_ids={"tests"},
        )
        self.assertTrue(any(item["id"].startswith("PROOF-BINDING") for item in findings))

    def test_unknown_gate_is_rejected(self):
        findings = proof_binding_findings(
            product={"acceptance_outcomes": ["Configured tests pass"]},
            plan={
                "demonstration": {
                    "gate_ids": [],
                    "product_evidence": [
                        {"outcome": "Configured tests pass", "gate_ids": ["invented"]}
                    ],
                }
            },
            available_gate_ids={"tests"},
        )
        self.assertTrue(any(item["id"].startswith("PROOF-UNKNOWN-GATES") for item in findings))

    def test_user_journey_requires_bound_demonstration_gate(self):
        findings = proof_binding_findings(
            product={"acceptance_outcomes": ["User can log in"]},
            plan={
                "demonstration": {
                    "gate_ids": [],
                    "product_evidence": [
                        {"outcome": "User can log in", "gate_ids": ["unit-tests"]}
                    ],
                }
            },
            available_gate_ids={"unit-tests", "browser-demo"},
        )
        self.assertTrue(any(item["id"].startswith("PROOF-DEMONSTRATION") for item in findings))

    def test_exact_valid_binding_has_no_findings(self):
        findings = proof_binding_findings(
            product={"acceptance_outcomes": ["User can log in"]},
            plan={
                "demonstration": {
                    "gate_ids": ["browser-demo"],
                    "product_evidence": [
                        {"outcome": "User can log in", "gate_ids": ["browser-demo"]}
                    ],
                }
            },
            available_gate_ids={"browser-demo"},
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
