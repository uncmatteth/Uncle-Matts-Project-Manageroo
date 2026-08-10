import unittest

from manageroo.report import build_report


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

    def test_report_exposes_the_exact_locked_reuse_path_and_deviation(self):
        report = build_report(
            {
                "run_id": "run-2",
                "status": "COMPLETE",
                "mode": "repair",
                "files_changed": ["AgentRobotView.kt"],
                "gates": [],
                "review": {"status": "approved", "findings": []},
                "reuse_conformance": [
                    {
                        "need": "final animations",
                        "candidate": "tools/swipebot_motion.py at 722296ca",
                        "implementation": "adapt-existing",
                        "deviation": "",
                    }
                ],
            }
        )
        self.assertIn("adapt-existing from `tools/swipebot_motion.py at 722296ca`", report)
        self.assertIn("deviation: none", report)


if __name__ == "__main__":
    unittest.main()
