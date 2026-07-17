import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from manageroo import entrypoint
from manageroo.prove import format_product_proof, run_product_proof


class ProductProofTests(unittest.TestCase):
    def test_product_proof_core_lanes_pass_but_missing_evidence_forbids_complete(self):
        report = run_product_proof(include_regression=False)
        self.assertFalse(report["ok"], report)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIn("Source-level adversarial regression evidence", report["blockers"])
        self.assertIn("Live coding-agent integration", report["blockers"])
        by_name = {item["name"]: item for item in report["checks"]}
        self.assertTrue(by_name["Whole-project lifecycle"]["ok"])
        self.assertTrue(by_name["Intent preservation and compaction defense"]["ok"])
        self.assertTrue(by_name["Scope and command enforcement"]["ok"])
        self.assertTrue(by_name["Durable worker state and drift rejection"]["ok"])
        self.assertFalse(by_name["Source-level adversarial regression evidence"]["ok"])
        self.assertFalse(by_name["Live coding-agent integration"]["ok"])

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

    def test_manageroo_prove_json_routes_explicit_live_agent(self):
        fake_report = {
            "ok": True,
            "status": "COMPLETE",
            "checks": [],
            "blockers": [],
        }
        output = io.StringIO()
        with patch.object(
            sys,
            "argv",
            ["manageroo", "prove", "--json", "--no-regression", "--live-agent", "codex"],
        ):
            with patch("manageroo.entrypoint.run_product_proof", return_value=fake_report) as run:
                with redirect_stdout(output):
                    code = entrypoint.main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(include_regression=False, live_agent="codex")
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "COMPLETE")
        self.assertEqual(payload["live_agent_selection"], "explicit")

    def test_manageroo_prove_auto_selects_any_available_live_agent(self):
        fake_report = {
            "ok": True,
            "status": "COMPLETE",
            "checks": [],
            "blockers": [],
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "prove", "--json"]):
            with patch("manageroo.entrypoint._auto_live_agent", return_value="gemini"):
                with patch(
                    "manageroo.entrypoint.run_product_proof",
                    return_value=fake_report,
                ) as run:
                    with redirect_stdout(output):
                        code = entrypoint.main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(include_regression=True, live_agent="gemini")
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["live_agent_selection"], "automatic")

    def test_manageroo_prove_returns_nonzero_when_no_live_agent_is_available(self):
        fake_report = {
            "ok": False,
            "status": "PARTIAL",
            "checks": [{"name": "Live coding-agent integration", "ok": False, "detail": "missing"}],
            "blockers": ["Live coding-agent integration"],
        }
        with patch.object(sys, "argv", ["manageroo", "prove", "--no-regression"]):
            with patch("manageroo.entrypoint._auto_live_agent", return_value=None):
                with patch(
                    "manageroo.entrypoint.run_product_proof",
                    return_value=fake_report,
                ) as run:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(entrypoint.main(), 2)
        run.assert_called_once_with(include_regression=False, live_agent=None)

    def test_provider_neutral_commands_route_to_automatic_worker_pool(self):
        self.assertEqual(
            entrypoint._provider_neutral_argv(["init", "."]),
            ["init", ".", "--agent", "auto"],
        )
        self.assertEqual(
            entrypoint._provider_neutral_argv(["projects", "--add"]),
            ["projects", "--add", "--agent", "auto"],
        )
        self.assertEqual(
            entrypoint._provider_neutral_argv(["init", ".", "--agent", "gemini"]),
            ["init", ".", "--agent", "gemini"],
        )

    def test_root_help_surfaces_product_proof_command(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--help"]):
            with redirect_stdout(output):
                self.assertEqual(entrypoint.main(), 0)
        text = output.getvalue()
        self.assertIn("Product certification:", text)
        self.assertIn("prove", text)
        self.assertIn("any available supported live coding agent", text)

    def test_prove_help_surfaces_optional_agent_override(self):
        output = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(output):
                entrypoint._prove_main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        text = output.getvalue()
        self.assertIn("--live-agent", text)
        self.assertIn("Omit this", text)


if __name__ == "__main__":
    unittest.main()
