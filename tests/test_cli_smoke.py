import io
import json
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.cli import main as cli_main
from manageroo.entrypoint import main
from manageroo.errors import SafetyError


ROOT = Path(__file__).resolve().parents[1]


class CliSmokeTests(unittest.TestCase):
    def test_run_failure_is_plain_english_unless_json_is_requested(self):
        controller = unittest.mock.Mock()
        controller.run_id = "run-plain-english"
        controller.run.side_effect = SafetyError(
            "Worker modified critical Manageroo controller truth; changes were "
            "restored: /tmp/example/controller/budget.json"
        )
        output = io.StringIO()
        with (
            patch("manageroo.cli._repo", return_value=Path("/tmp/example")),
            patch("manageroo.cli.Orchestrator", return_value=controller),
            redirect_stderr(output),
        ):
            code = cli_main(["run", "--repo", "/tmp/example", "--apply"])

        rendered = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("Manageroo stopped safely", rendered)
        self.assertIn("What happened:", rendered)
        self.assertIn("What this means:", rendered)
        self.assertIn("What to do next:", rendered)
        self.assertNotIn("controller truth", rendered)
        self.assertNotIn("budget.json", rendered)

    def test_run_json_keeps_full_diagnostics_when_explicitly_requested(self):
        controller = unittest.mock.Mock()
        controller.run_id = "run-diagnostic"
        controller.run.side_effect = SafetyError(
            "Worker modified critical Manageroo controller truth; changes were "
            "restored: /tmp/example/controller/budget.json"
        )
        output = io.StringIO()
        with (
            patch("manageroo.cli._repo", return_value=Path("/tmp/example")),
            patch("manageroo.cli.Orchestrator", return_value=controller),
            redirect_stdout(output),
        ):
            code = cli_main(
                ["run", "--repo", "/tmp/example", "--apply", "--json"]
            )

        rendered = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn('"run_id": "run-diagnostic"', rendered)
        self.assertIn("controller truth", rendered)
        self.assertIn("budget.json", rendered)

    def test_plain_failure_surfaces_the_actual_non_sensitive_error(self):
        controller = unittest.mock.Mock()
        controller.run_id = "run-visible-error"
        controller.run.side_effect = SafetyError("configured gate unit-tests failed")
        output = io.StringIO()
        with (
            patch("manageroo.cli._repo", return_value=Path("/tmp/example")),
            patch("manageroo.cli.Orchestrator", return_value=controller),
            redirect_stderr(output),
        ):
            code = cli_main(["run", "--repo", "/tmp/example"])
        self.assertEqual(code, 1)
        self.assertIn("configured gate unit-tests failed", output.getvalue())

    def test_report_defaults_to_plain_english_and_hides_internal_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "run-plain-report"
            delivery = repo / ".manageroo" / "runs" / run_id / "delivery"
            delivery.mkdir(parents=True)
            (delivery / "failure.json").write_text(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "error": (
                            "Worker modified critical Manageroo controller truth; "
                            "changes were restored: /tmp/example/controller/budget.json"
                        ),
                        "applied_to_source": False,
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch("manageroo.cli._repo", return_value=repo),
                redirect_stdout(output),
            ):
                code = cli_main(["report", run_id, "--repo", str(repo)])

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Manageroo stopped safely", rendered)
        self.assertIn("What happened:", rendered)
        self.assertIn("What this means:", rendered)
        self.assertIn("What to do next:", rendered)
        self.assertNotIn("controller truth", rendered)
        self.assertNotIn("budget.json", rendered)

    def test_status_defaults_to_plain_english(self):
        store = unittest.mock.Mock()
        store.status_summary.return_value = {
            "current_job": "product-analyst",
            "completed_jobs": 0,
            "failed_attempts": 2,
            "next_action": "retry",
            "blocking_reason": "internal detail",
        }
        output = io.StringIO()
        with (
            patch("manageroo.cli._repo", return_value=Path("/tmp/example")),
            patch(
                "manageroo.cli.read_json",
                return_value={
                    "status": "BLOCKED",
                    "error": (
                        "Worker modified critical Manageroo controller truth; "
                        "changes were restored: /tmp/example/controller/budget.json"
                    ),
                },
            ),
            patch("manageroo.cli.JobStore", return_value=store),
            redirect_stdout(output),
        ):
            code = cli_main(
                ["status", "run-plain-status", "--repo", "/tmp/example"]
            )

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Manageroo stopped safely", rendered)
        self.assertNotIn("product-analyst", rendered)
        self.assertNotIn("budget.json", rendered)

    def test_active_run_is_not_reported_as_stopped(self):
        store = unittest.mock.Mock()
        store.status_summary.return_value = {
            "current_job": "implementer",
            "completed_jobs": 1,
            "failed_attempts": 0,
            "next_action": "continue",
            "blocking_reason": "",
        }
        output = io.StringIO()
        with patch("manageroo.cli._repo", return_value=Path("/tmp/example")), patch(
            "manageroo.cli.read_json", return_value={"status": "IMPLEMENTING"}
        ), patch("manageroo.cli.JobStore", return_value=store), redirect_stdout(output):
            code = cli_main(["status", "run-active", "--repo", "/tmp/example"])
        self.assertEqual(code, 0)
        self.assertIn("Manageroo is working", output.getvalue())
        self.assertNotIn("stopped safely", output.getvalue())

    def test_console_script_points_to_public_entrypoint(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(project["project"]["scripts"]["manageroo"], "manageroo.entrypoint:main")

    def test_public_help_entrypoint_constructs_and_exits_cleanly(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--help"]), redirect_stdout(output):
            code = main()
        self.assertEqual(code, 0)
        rendered = output.getvalue()
        self.assertIn("manageroo", rendered.lower())
        self.assertIn("prove", rendered)
        self.assertIn("stack-update", rendered)


if __name__ == "__main__":
    unittest.main()
