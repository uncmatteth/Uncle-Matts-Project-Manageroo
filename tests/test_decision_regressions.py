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
from manageroo.util import atomic_write_json, read_json


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

    def test_malformed_decision_artifacts_fail_closed_for_show_and_answer(self):
        malformed_artifacts = {
            "invalid-json": "{",
            "top-level-array": "[]",
            "scalar-decisions": '{"decisions": 1}',
            "string-decisions": '{"decisions": "open"}',
        }
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for name, artifact in malformed_artifacts.items():
                with self.subTest(name=name, command="show"):
                    planning = (
                        repo
                        / ".manageroo"
                        / "runs"
                        / name
                        / "artifacts"
                        / "planning"
                    )
                    planning.mkdir(parents=True)
                    (planning / "blocking-decisions.json").write_text(
                        artifact, encoding="utf-8"
                    )
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = _decisions_main(
                            ["show", name, "--repo", str(repo), "--json"]
                        )
                    payload = json.loads(stdout.getvalue())
                    self.assertEqual(code, 2)
                    self.assertEqual(payload["ok"], False)
                    self.assertIn("Cannot read blocking decisions", payload["error"])
                    self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())

                with self.subTest(name=name, command="answer"):
                    stderr = io.StringIO()
                    with patch(
                        "builtins.input", side_effect=AssertionError("input must not be called")
                    ):
                        with redirect_stderr(stderr):
                            code = _decisions_main(
                                ["answer", name, "--repo", str(repo)]
                            )
                    self.assertEqual(code, 2)
                    self.assertIn("Cannot read blocking decisions", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

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

    def test_concurrent_answer_session_cannot_replace_saved_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "concurrent-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {
                            "id": "deployment",
                            "question": "Choose deployment",
                            "options": ["Blue", "Green"],
                        }
                    ]
                },
            )
            competing_codes: list[int] = []

            def answer_after_competing_session(_: str) -> str:
                with patch("builtins.input", return_value="1"):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        competing_codes.append(
                            _decisions_main(["answer", run_id, "--repo", str(repo)])
                        )
                return "2"

            stderr = io.StringIO()
            with patch("builtins.input", side_effect=answer_after_competing_session):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    stale_code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(competing_codes, [0])
            self.assertEqual(stale_code, 2)
            self.assertIn("another decision answer session", stderr.getvalue())
            resolved = read_json(planning / "resolved-decisions.json")
            self.assertEqual(
                resolved["answers"], [{"id": "deployment", "chosen": "Blue"}]
            )
            self.assertRegex(resolved["blocking_decisions_sha256"], r"^[0-9a-f]{64}$")

    def test_changed_blocking_decisions_during_prompt_are_not_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "changed-decisions-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {
                            "id": "deployment",
                            "question": "Choose deployment",
                            "options": ["Blue", "Green"],
                        }
                    ]
                },
            )

            def change_decisions(_: str) -> str:
                atomic_write_json(
                    blocking,
                    {
                        "decisions": [
                            {
                                "id": "region",
                                "question": "Choose region",
                                "options": ["East", "West"],
                            }
                        ]
                    },
                )
                return "1"

            stderr = io.StringIO()
            with patch("builtins.input", side_effect=change_decisions):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("changed while answers were being entered", stderr.getvalue())
            self.assertFalse((planning / "resolved-decisions.json").exists())


if __name__ == "__main__":
    unittest.main()
