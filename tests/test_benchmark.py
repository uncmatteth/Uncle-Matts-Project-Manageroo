from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.benchmark import run_continuity_benchmark
from manageroo.entrypoint import _root_help, main


ROOT = Path(__file__).resolve().parents[1]


class ContinuityBenchmarkTests(unittest.TestCase):
    def test_benchmark_proves_silent_routine_hooks_and_bounded_recovery(self):
        report = run_continuity_benchmark()

        self.assertTrue(report["ok"])
        self.assertEqual(report["kind"], "deterministic-controller")
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["routine"]["emitted_characters"], 0)
        self.assertEqual(report["routine"]["estimated_tokens"], 0)
        self.assertLessEqual(report["recovery"]["estimated_tokens"], 200)
        self.assertTrue(all(report["controls"].values()))
        self.assertTrue(report["controls"]["paused_tools_available"])
        self.assertTrue(report["controls"]["ordinary_stop_unblocked"])
        self.assertIn("does not measure model code quality", report["limits"])

    def test_benchmark_command_reports_machine_readable_results_without_model_calls(self):
        output = io.StringIO()
        with patch("sys.argv", ["manageroo", "benchmark", "--json"]), redirect_stdout(output):
            exit_code = main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["model_calls"], 0)

    def test_public_docs_separate_zero_model_measurement_from_live_ab(self):
        benchmark_docs = (ROOT / "docs" / "BENCHMARKING.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("benchmark             Measure hook overhead", _root_help())
        self.assertIn("manageroo benchmark --json", readme)
        self.assertIn("makes no model calls", benchmark_docs)
        self.assertIn("same agent/model/settings", benchmark_docs)
        self.assertIn("without telling the scorer which lane produced it", benchmark_docs)


if __name__ == "__main__":
    unittest.main()
