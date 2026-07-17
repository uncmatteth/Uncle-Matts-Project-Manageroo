import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from manageroo import entrypoint
from manageroo.prove import format_product_proof, run_product_proof


class ProductProofTests(unittest.TestCase):
    def test_product_proof_core_lanes_pass_but_skipped_regression_forbids_complete(self):
        report = run_product_proof(include_regression=False)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("Source-level adversarial regression evidence", report["blockers"])
        by_name = {item["name"]: item for item in report["checks"]}
        self.assertTrue(by_name["Whole-project lifecycle"]["ok"])
        self.assertTrue(by_name["Intent preservation and compaction defense"]["ok"])
        self.assertTrue(by_name["Scope and command enforcement"]["ok"])
        self.assertTrue(by_name["Durable worker state and drift rejection"]["ok"])
        self.assertFalse(by_name["Source-level adversarial regression evidence"]["ok"])

    def test_product_proof_never_formats_complete_when_a_required_lane_fails(self):
        report = {
            "ok": False,
            "status": "PARTIAL",
            "checks": [{"name": "Dishonest evidence rejection", "ok": False, "detail": "blocked"}],
            "blockers": ["Dishonest evidence rejection"],
        }
        text = format_product_proof(report)
        self.assertIn("FAIL  Dishonest evidence rejection", text)
        self.assertIn("RESULT: PARTIAL", text)
        self.assertNotIn("RESULT: COMPLETE", text)

    def test_manageroo_prove_json_routes_through_unified_entrypoint(self):
        fake_report = {
            "ok": True,
            "status": "COMPLETE",
            "checks": [],
            "blockers": [],
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "prove", "--json", "--no-regression"]):
            with patch("manageroo.entrypoint.run_product_proof", return_value=fake_report) as run:
                with redirect_stdout(output):
                    code = entrypoint.main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(include_regression=False)
        self.assertEqual(json.loads(output.getvalue())["status"], "COMPLETE")

    def test_manageroo_prove_returns_nonzero_for_partial_proof(self):
        fake_report = {
            "ok": False,
            "status": "PARTIAL",
            "checks": [{"name": "regression", "ok": False, "detail": "failed"}],
            "blockers": ["regression"],
        }
        with patch.object(sys, "argv", ["manageroo", "prove", "--no-regression"]):
            with patch("manageroo.entrypoint.run_product_proof", return_value=fake_report):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(entrypoint.main(), 2)


if __name__ == "__main__":
    unittest.main()
