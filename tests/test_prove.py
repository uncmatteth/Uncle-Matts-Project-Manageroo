import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo import entrypoint
from manageroo.prove import (
    _configure_proof_project,
    _git_fixture,
    _live_agent_case,
    _remove_disposable_config_locks,
    format_product_proof,
    run_product_proof,
)


class ProductProofTests(unittest.TestCase):
    def test_live_proof_uses_the_real_orchestrator_and_requires_complete(self):
        class ProofAdapter:
            def doctor(self, cwd):
                return {"ok": True, "adapter": "codex", "version": "test"}

        def completed_run(controller, **kwargs):
            del kwargs
            (controller.source_repo / "manageroo_live_agent_proof.txt").write_text(
                "MANAGEROO live agent proof completed\n", encoding="utf-8"
            )
            return {
                "status": "COMPLETE",
                "run_id": "proof-run",
                "applied_to_source": True,
                "files_changed": ["manageroo_live_agent_proof.txt"],
                "gates": [{"id": "product-proof-check", "passed": True}],
                "review": {"status": "approved"},
                "evidence_paths": {"run_root": "/proof"},
            }

        with patch("manageroo.prove.build_adapter", return_value=ProofAdapter()), patch(
            "manageroo.prove.Orchestrator.run", autospec=True, side_effect=completed_run
        ) as run:
            result = _live_agent_case("codex")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["run_status"], "COMPLETE")
        self.assertTrue(result["independent_review_approved"])
        self.assertEqual(run.call_args.kwargs["exact_task"]["targets"], ["manageroo_live_agent_proof.txt"])

    def test_live_proof_rejects_noncomplete_orchestrator_result(self):
        class ProofAdapter:
            def doctor(self, cwd):
                return {"ok": True, "adapter": "codex", "version": "test"}

        with patch("manageroo.prove.build_adapter", return_value=ProofAdapter()), patch(
            "manageroo.prove.Orchestrator.run",
            return_value={"status": "BLOCKED", "files_changed": []},
        ):
            result = _live_agent_case("codex")
        self.assertFalse(result["ok"])
        self.assertEqual(result["run_status"], "BLOCKED")

    def test_live_proof_fixture_is_pristine_before_transactional_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _git_fixture(Path(temp))
            _configure_proof_project(repo, agent="codex")
            _remove_disposable_config_locks(repo)
            for argv in (["git", "add", "-A"], ["git", "commit", "-m", "proof"]):
                result = subprocess.run(
                    argv,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all", "--ignored"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(status.stdout, "")

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

    def test_manageroo_prove_auto_selects_supported_live_agent(self):
        fake_report = {
            "ok": True,
            "status": "COMPLETE",
            "checks": [],
            "blockers": [],
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "prove", "--json"]):
            with patch("manageroo.entrypoint._auto_live_agent", return_value="codex"):
                with patch(
                    "manageroo.entrypoint.run_product_proof",
                    return_value=fake_report,
                ) as run:
                    with redirect_stdout(output):
                        code = entrypoint.main()
        self.assertEqual(code, 0)
        run.assert_called_once_with(include_regression=True, live_agent="codex")
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
        self.assertEqual(
            entrypoint._provider_neutral_argv(["init", ".", "--agent=gemini"]),
            ["init", ".", "--agent=gemini"],
        )

    def test_root_help_surfaces_product_proof_command(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["manageroo", "--help"]):
            with redirect_stdout(output):
                self.assertEqual(entrypoint.main(), 0)
        text = output.getvalue()
        self.assertIn("Product certification:", text)
        self.assertIn("prove", text)
        self.assertIn("available supported live coding agent", text)

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
