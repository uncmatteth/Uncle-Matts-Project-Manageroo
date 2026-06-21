import unittest

from umsmfburasbofe.report import build_report


class ReportTests(unittest.TestCase):
    def test_report_has_plain_english_summary_and_empty_gate_notice(self):
        report = build_report(
            {
                "run_id": "run-1",
                "status": "BLOCKED",
                "mode": "build",
                "applied_to_source": False,
                "files_changed": [],
                "gates": [],
                "review": {"status": "not-run", "findings": []},
                "evidence_paths": {"run_root": "/tmp/run-1"},
                "error_type": "ValidationError",
                "error": "Product brief not found",
            }
        )
        self.assertIn("## Plain English", report)
        self.assertIn("Applied to source repo: no", report)
        self.assertIn("Verification gates recorded: 0", report)
        self.assertIn("No verification gates recorded.", report)
        self.assertIn("ValidationError: Product brief not found", report)
        self.assertIn("cat /tmp/run-1/delivery/final-result.json", report)


if __name__ == "__main__":
    unittest.main()
