import unittest

from manageroo.orchestrator import build_acceptance_evidence


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_user_journey_claim_without_demonstration_evidence_is_unknown(self):
        rows = build_acceptance_evidence(
            product={
                "acceptance_outcomes": [
                    "Configured verification gates pass.",
                    "User can complete the browser checkout journey.",
                ]
            },
            gate_results=[
                {
                    "gate": {"id": "smoke"},
                    "result": {"exit_code": 0},
                }
            ],
            demonstration={
                "gates": [],
                "product_evidence": [],
            },
            review={"status": "approved", "findings": []},
        )

        by_description = {item["description"]: item for item in rows}
        self.assertEqual(
            by_description["Configured verification gates pass."]["status"],
            "passed",
        )
        browser = by_description["User can complete the browser checkout journey."]
        self.assertEqual(browser["status"], "unknown")
        self.assertEqual(browser["evidence"], [])
        self.assertIn("demonstration", browser["reason"].lower())


if __name__ == "__main__":
    unittest.main()
