import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo import entrypoint
from manageroo.discovery_policy import apply_resolved_decisions
from manageroo.entrypoint import _decisions_main, _validated_decisions
from manageroo.errors import ValidationError
from manageroo.util import atomic_write_json


class DecisionRegressionTests(unittest.TestCase):
    def test_console_main_installs_entrypoint_policy_before_dispatch(self):
        output = io.StringIO()
        with patch("manageroo.entrypoint_policy.install_entrypoint_policy") as install:
            with patch.object(sys, "argv", ["manageroo", "--help"]):
                with redirect_stdout(output):
                    code = entrypoint.main()
        self.assertEqual(code, 0)
        install.assert_called_once_with(entrypoint)

    def test_console_main_rejects_malformed_blocking_decisions_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "malformed-run"
            planning = repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            planning.mkdir(parents=True)
            (planning / "blocking-decisions.json").write_text("{", encoding="utf-8")
            stderr = io.StringIO()
            argv = ["manageroo", "decisions", "show", run_id, "--repo", str(repo)]
            with patch.object(sys, "argv", argv):
                with redirect_stderr(stderr):
                    code = entrypoint.main()
            self.assertEqual(code, 2)
            self.assertIn("Cannot read blocking decisions", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_console_main_converts_eof_during_decision_answer_to_exit_two(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "interrupted-run"
            planning = repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "decision-a", "question": "Choose", "options": ["one", "two"]}
                    ]
                },
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = ["manageroo", "decisions", "answer", run_id, "--repo", str(repo)]
            with patch.object(sys, "argv", argv), patch("builtins.input", side_effect=EOFError):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = entrypoint.main()
            self.assertEqual(code, 2)
            self.assertIn("input ended before all choices were completed", stderr.getvalue())
            self.assertFalse((planning / "resolved-decisions.json").exists())

    def test_show_json_returns_valid_empty_payload_when_no_decisions_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "empty-run"
            (repo / ".manageroo" / "runs" / run_id).mkdir(parents=True)
            output = io.StringIO()
            with redirect_stdout(output):
                code = _decisions_main(["show", run_id, "--repo", str(repo), "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload, {"run_id": run_id, "decisions": []})

    def test_optionless_decision_is_rejected_before_interactive_prompting(self):
        decisions, error = _validated_decisions([
            {"id": "deployment-mode", "question": "Choose deployment", "options": []}
        ])
        self.assertEqual(decisions, [])
        self.assertIn("no selectable options", error or "")

    def test_unknown_resolved_answer_is_rejected_without_consuming_input(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            resolved = planning / "resolved-decisions.json"
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {"id": "known", "question": "Known?", "options": ["yes", "no"], "chosen": ""}
                    ]
                },
            )
            atomic_write_json(
                resolved,
                {"answers": [{"id": "known", "chosen": "yes"}, {"id": "unknown", "chosen": "no"}]},
            )
            with self.assertRaisesRegex(ValidationError, "unknown decision id"):
                apply_resolved_decisions(run_root)
            self.assertTrue(resolved.is_file())

    def test_duplicate_resolved_answer_is_rejected_without_last_writer_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            resolved = planning / "resolved-decisions.json"
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {"id": "known", "question": "Known?", "options": ["yes", "no"], "chosen": ""}
                    ]
                },
            )
            atomic_write_json(
                resolved,
                {"answers": [{"id": "known", "chosen": "yes"}, {"id": "known", "chosen": "no"}]},
            )
            with self.assertRaisesRegex(ValidationError, "duplicate answer id"):
                apply_resolved_decisions(run_root)
            self.assertTrue(resolved.is_file())


if __name__ == "__main__":
    unittest.main()
