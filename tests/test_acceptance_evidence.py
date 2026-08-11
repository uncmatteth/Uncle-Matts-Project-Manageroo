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

    def test_malformed_exit_codes_never_pass_bound_gate(self):
        malformed_results = {
            "false": {"exit_code": False},
            "true": {"exit_code": True},
            "string": {"exit_code": "0"},
            "null": {"exit_code": None},
            "missing": {},
        }
        for label, result in malformed_results.items():
            with self.subTest(exit_code=label):
                rows = build_acceptance_evidence(
                    product={"acceptance_outcomes": ["Configured verification gates pass."]},
                    gate_results=[{"gate": {"id": "smoke"}, "result": result}],
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
                self.assertEqual(rows[0]["status"], "failed")
                self.assertIn("smoke", rows[0]["reason"])

    def test_malformed_gate_id_bindings_fail_closed(self):
        malformed_gate_ids = {
            "null": None,
            "integer": 1,
            "boolean": True,
            "string": "smoke",
            "dictionary": {"gate": "smoke"},
            "empty-list": [],
            "mixed-list": ["smoke", 1],
        }
        outcome = "Configured verification gates pass."
        for label, gate_ids in malformed_gate_ids.items():
            with self.subTest(gate_ids=label):
                rows = build_acceptance_evidence(
                    product={"acceptance_outcomes": [outcome]},
                    gate_results=[
                        {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
                    ],
                    demonstration={
                        "gates": [],
                        "product_evidence": [
                            {"outcome": outcome, "gate_ids": gate_ids},
                        ],
                    },
                    review={"status": "approved", "findings": []},
                )
                self.assertEqual(rows[0]["status"], "failed")
                self.assertEqual(rows[0]["evidence"], [])
                self.assertIn("list of non-empty strings", rows[0]["reason"])

    def test_existing_but_failing_bound_gate_fails_only_its_outcome(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Export remains correct.", "Import remains correct."]},
            gate_results=[
                {"gate": {"id": "export-regression"}, "result": {"exit_code": 1}},
                {"gate": {"id": "import-regression"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [],
                "product_evidence": [
                    {"outcome": "Export remains correct.", "gate_ids": ["export-regression"]},
                    {"outcome": "Import remains correct.", "gate_ids": ["import-regression"]},
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[1]["status"], "passed")

    def test_conflicting_duplicate_bound_gate_results_never_pass(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Configured verification gates pass."]},
            gate_results=[
                {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
                {"gate": {"id": "smoke"}, "result": {"exit_code": 1}},
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
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("duplicate", rows[0]["reason"])

    def test_cross_lane_failure_cannot_be_masked_by_regular_pass(self):
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": ["Configured verification gates pass."]},
            gate_results=[
                {"gate": {"id": "smoke"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [
                    {"gate": {"id": "smoke"}, "result": {"exit_code": 1}},
                ],
                "product_evidence": [
                    {
                        "outcome": "Configured verification gates pass.",
                        "gate_ids": ["smoke"],
                    }
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("conflicting", rows[0]["reason"])

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

    def test_hyphenated_security_terms_require_bound_demonstration_gate(self):
        outcomes = (
            "Role-based access is enforced.",
            "Auth-protected dashboard.",
            "Permission-gated settings.",
        )
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                rows = build_acceptance_evidence(
                    product={"acceptance_outcomes": [outcome]},
                    gate_results=[
                        {"gate": {"id": "security-unit"}, "result": {"exit_code": 0}},
                    ],
                    demonstration={
                        "gates": [],
                        "product_evidence": [
                            {"outcome": outcome, "gate_ids": ["security-unit"]},
                        ],
                    },
                    review={"status": "approved", "findings": []},
                )
                self.assertEqual(rows[0]["status"], "unknown")
                self.assertIn("demonstration", rows[0]["reason"].lower())

    def test_failing_bound_demonstration_gate_fails_user_journey(self):
        outcome = "User can complete the browser checkout journey."
        rows = build_acceptance_evidence(
            product={"acceptance_outcomes": [outcome]},
            gate_results=[
                {"gate": {"id": "checkout-unit"}, "result": {"exit_code": 0}},
            ],
            demonstration={
                "gates": [
                    {"gate": {"id": "checkout-e2e"}, "result": {"exit_code": 1}},
                ],
                "product_evidence": [
                    {"outcome": outcome, "gate_ids": ["checkout-unit", "checkout-e2e"]},
                ],
            },
            review={"status": "approved", "findings": []},
        )
        self.assertEqual(rows[0]["status"], "failed")

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
