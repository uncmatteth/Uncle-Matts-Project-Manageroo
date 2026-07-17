import unittest

from manageroo.acceptance import build_acceptance_evidence as strict_build_acceptance_evidence
from manageroo.orchestrator import build_acceptance_evidence


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_package_installs_strict_completion_policy(self):
        self.assertIs(build_acceptance_evidence, strict_build_acceptance_evidence)

    def test_unbound_outcome_is_unknown_even_when_global_test_passes(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Password reset works."]},
            gate_results=[
                {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
            ],
            demonstration={"gates": [], "product_evidence": []},
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertIn("binding", rows[0]["reason"].lower())

    def test_outcome_passes_only_with_its_bound_gate(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Configured verification gates pass."]},
            gate_results=[
                {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
                {"gate": {"id": "unrelated"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [],
                "product_evidence": [
                    {
                        "outcome": "Configured verification gates pass.",
                        "gate_ids": ["smoke"],
                    }
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "passed")
        self.assertIn("gate:smoke", rows[0]["evidence"])
        self.assertNotIn("gate:unrelated", rows[0]["evidence"])

    def test_user_journey_requires_bound_demonstration_gate(self):
        outcome = "User can complete the browser checkout journey."
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": [outcome]},
            gate_results=[
                {"gate": {"id": "checkout-unit"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [],
                "product_evidence": [
                    {"outcome": outcome, "gate_ids": ["checkout-unit"]},
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "unknown")
        self.assertIn("demonstration", rows[0]["reason"].lower())

        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": [outcome]},
            gate_results=[
                {"gate": {"id": "checkout-unit"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [
                    {"gate": {"id": "checkout-e2e"}, "result": {"exit_code": 0}},
                ],
                "product_evidence": [
                    {
                        "outcome": outcome,
                        "gate_ids": ["checkout-unit", "checkout-e2e"],
                    },
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "passed")

    def test_missing_bound_gate_fails_outcome(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Export remains correct."]},
            gate_results=[
                {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [],
                "product_evidence": [
                    {"outcome": "Export remains correct.", "gate_ids": ["export-regression"]},
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("export-regression", rows[0]["reason"])


if __name__ == "__main__":
    unittest.main()
