import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
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

    def test_show_rejects_symlinked_blocking_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "symlinked-blocking-decisions"
            planning = repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            planning.mkdir(parents=True)
            external = root / "external.json"
            atomic_write_json(
                external,
                {
                    "decisions": [
                        {"id": "external", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            try:
                (planning / "blocking-decisions.json").symlink_to(external)
            except OSError as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")

            output = io.StringIO()
            with redirect_stdout(output):
                code = _decisions_main(["show", run_id, "--repo", str(repo), "--json"])

            self.assertEqual(code, 2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["ok"], False)
            self.assertIn("Cannot read blocking decisions", payload["error"])
            self.assertNotIn("external", output.getvalue())

    def test_show_rejects_blocking_decisions_replaced_after_open(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "replaced-blocking-decisions"
            planning = repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            replacement = planning / ".replacement.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {"id": "original", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            atomic_write_json(
                replacement,
                {
                    "decisions": [
                        {"id": "replacement", "question": "Choose", "options": ["two"]}
                    ]
                },
            )
            original_fstat = os.fstat
            replaced = False

            def fstat_then_replace(descriptor):
                nonlocal replaced
                state = original_fstat(descriptor)
                if stat.S_ISREG(state.st_mode) and not replaced:
                    replacement.replace(blocking)
                    replaced = True
                return state

            output = io.StringIO()
            with patch("manageroo.entrypoint.os.fstat", side_effect=fstat_then_replace):
                with redirect_stdout(output):
                    code = _decisions_main(["show", run_id, "--repo", str(repo), "--json"])

            self.assertTrue(replaced)
            self.assertEqual(code, 2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["ok"], False)
            self.assertIn("unsafe", payload["error"])
            self.assertNotIn('"id"', output.getvalue())

    def test_show_rejects_blocking_decisions_removed_after_open(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "removed-blocking-decisions"
            planning = repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {"id": "original", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            original_fstat = os.fstat
            removed = False

            def fstat_then_remove(descriptor):
                nonlocal removed
                state = original_fstat(descriptor)
                if stat.S_ISREG(state.st_mode) and not removed:
                    blocking.unlink()
                    removed = True
                return state

            output = io.StringIO()
            with patch("manageroo.entrypoint.os.fstat", side_effect=fstat_then_remove):
                with redirect_stdout(output):
                    code = _decisions_main(["show", run_id, "--repo", str(repo), "--json"])

            self.assertTrue(removed)
            self.assertEqual(code, 2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["ok"], False)
            self.assertIn("changed", payload["error"])

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

    def test_planning_directory_swap_at_commit_cannot_redirect_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "swapped-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()

            def swap_planning_directory() -> str:
                planning.rename(displaced)
                try:
                    planning.symlink_to(external, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"Symlink creation is unavailable: {exc}")
                return "2026-08-06T00:00:00Z"

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint.utc_now", side_effect=swap_planning_directory
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_planning_directory_swap_during_atomic_write_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "late-swapped-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_write = entrypoint._atomic_write_json_at

            def swap_then_write(*args, **kwargs):
                planning.rename(displaced)
                try:
                    planning.symlink_to(external, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"Symlink creation is unavailable: {exc}")
                return original_write(*args, **kwargs)

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._atomic_write_json_at", side_effect=swap_then_write
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_planning_directory_swap_after_pre_restore_validation_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "post-validation-swapped-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_validate = entrypoint._validate_pinned_planning
            validation_calls = 0

            def swap_after_fourth_validation(*args, **kwargs):
                nonlocal validation_calls
                original_validate(*args, **kwargs)
                validation_calls += 1
                if validation_calls == 4:
                    planning.rename(displaced)
                    try:
                        planning.symlink_to(external, target_is_directory=True)
                    except OSError as exc:
                        self.skipTest(f"Symlink creation is unavailable: {exc}")

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._validate_pinned_planning",
                side_effect=swap_after_fourth_validation,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_planning_directory_swap_at_lock_release_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "lock-release-swapped-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_lock = entrypoint.config_mutation_lock

            @contextmanager
            def swap_at_lock_release(*args, **kwargs):
                with original_lock(*args, **kwargs):
                    yield
                planning.rename(displaced)
                try:
                    planning.symlink_to(external, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"Symlink creation is unavailable: {exc}")

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint.config_mutation_lock",
                side_effect=swap_at_lock_release,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_planning_directory_swap_after_final_validation_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "final-validation-swapped-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_validate = entrypoint._validate_pinned_planning
            validation_calls = 0

            def swap_after_final_validation(*args, **kwargs):
                nonlocal validation_calls
                original_validate(*args, **kwargs)
                validation_calls += 1
                if validation_calls == 6:
                    planning.rename(displaced)
                    try:
                        planning.symlink_to(external, target_is_directory=True)
                    except OSError as exc:
                        self.skipTest(f"Symlink creation is unavailable: {exc}")

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._validate_pinned_planning",
                side_effect=swap_after_final_validation,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_planning_directory_swap_during_artifact_republish_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "republish-swapped-planning-run"
            run_root = repo / ".manageroo" / "runs" / run_id
            artifacts = run_root / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            planning_state = planning.stat()
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_fstat = entrypoint.os.fstat
            swapped = False

            def swap_after_republish_identity_snapshot(descriptor):
                nonlocal swapped
                opened = original_fstat(descriptor)
                claimed_artifacts = list(run_root.glob(".artifacts.answer-*"))
                if (
                    not swapped
                    and claimed_artifacts
                    and (opened.st_dev, opened.st_ino)
                    == (planning_state.st_dev, planning_state.st_ino)
                ):
                    claimed_planning = claimed_artifacts[0] / "planning"
                    claimed_planning.rename(claimed_artifacts[0] / displaced.name)
                    try:
                        claimed_planning.symlink_to(external, target_is_directory=True)
                    except OSError as exc:
                        self.skipTest(f"Symlink creation is unavailable: {exc}")
                    swapped = True
                return opened

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint.os.fstat",
                side_effect=swap_after_republish_identity_snapshot,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertTrue(swapped)
            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_artifact_republish_rejects_in_place_mutation_after_snapshot_read(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_root = repo / ".manageroo" / "runs" / "republish-in-place-race"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            original = {
                "decisions": [
                    {"id": "deployment", "question": "Choose", "options": ["one"]}
                ]
            }
            replacement = {
                "decisions": [
                    {"id": "region", "question": "Choose", "options": ["east"]}
                ]
            }
            atomic_write_json(blocking, original)
            expected_sha256 = entrypoint.sha256_json(
                {"decisions": original["decisions"]}
            )
            original_match = entrypoint._blocking_decisions_payload_matches
            held_descriptor = os.open(blocking, os.O_WRONLY)
            mutated = False

            def mutate_after_snapshot_read(payload, expected):
                nonlocal mutated
                matches = original_match(payload, expected)
                if not mutated:
                    changed = (
                        json.dumps(replacement, indent=2, sort_keys=True) + "\n"
                    ).encode("utf-8")
                    os.ftruncate(held_descriptor, 0)
                    os.lseek(held_descriptor, 0, os.SEEK_SET)
                    os.write(held_descriptor, changed)
                    os.fsync(held_descriptor)
                    mutated = True
                return matches

            try:
                with entrypoint._pinned_planning_directory(run_root) as (
                    pinned_planning,
                    planning_descriptor,
                    planning_state,
                    artifacts_descriptor,
                    artifacts_state,
                    run_descriptor,
                ), patch(
                    "manageroo.entrypoint._blocking_decisions_payload_matches",
                    side_effect=mutate_after_snapshot_read,
                ):
                    with self.assertRaisesRegex(
                        entrypoint.SafetyError,
                        "changed during decision persistence",
                    ):
                        entrypoint._republish_pinned_artifacts(
                            run_descriptor,
                            artifacts_descriptor,
                            artifacts_state,
                            planning_descriptor,
                            planning_state,
                            pinned_planning,
                            expected_sha256,
                        )
            finally:
                os.close(held_descriptor)

            self.assertTrue(mutated)
            self.assertEqual(read_json(blocking), original)

    def test_planning_directory_swap_after_republish_validation_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "post-republish-validation-swap-run"
            run_root = repo / ".manageroo" / "runs" / run_id
            artifacts = run_root / "artifacts"
            planning = artifacts / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            run_state = run_root.stat()
            displaced = artifacts / "planning-original"
            external = root / "external"
            external.mkdir()
            original_fsync = entrypoint.os.fsync
            swapped = False

            def swap_after_republish_validation(descriptor):
                nonlocal swapped
                original_fsync(descriptor)
                opened = entrypoint.os.fstat(descriptor)
                if (
                    not swapped
                    and (opened.st_dev, opened.st_ino)
                    == (run_state.st_dev, run_state.st_ino)
                ):
                    planning.rename(displaced)
                    try:
                        planning.symlink_to(external, target_is_directory=True)
                    except OSError as exc:
                        self.skipTest(f"Symlink creation is unavailable: {exc}")
                    swapped = True

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint.os.fsync",
                side_effect=swap_after_republish_validation,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertTrue(swapped)
            self.assertEqual(code, 2)
            self.assertIn("Cannot save decision answers", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((displaced / "resolved-decisions.json").exists())

    def test_answer_fails_closed_without_descriptor_relative_filesystem_access(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "unsupported-filesystem-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._descriptor_relative_planning_supported",
                return_value=False,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("descriptor-relative no-follow", stderr.getvalue())
            self.assertFalse((planning / "resolved-decisions.json").exists())

    def test_blocking_decisions_mutation_at_commit_cannot_save_stale_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "commit-race-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )

            def mutate_blocking_decisions() -> str:
                atomic_write_json(
                    blocking,
                    {
                        "decisions": [
                            {"id": "region", "question": "Choose", "options": ["east"]}
                        ]
                    },
                )
                return "2026-08-06T00:00:00Z"

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint.utc_now", side_effect=mutate_blocking_decisions
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("changed while answers were being entered", stderr.getvalue())
            self.assertFalse((planning / "resolved-decisions.json").exists())

    def test_concurrent_blocking_decisions_replacement_restores_original(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "post-check-race-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            original = {
                "decisions": [
                    {"id": "deployment", "question": "Choose", "options": ["one"]}
                ]
            }
            atomic_write_json(blocking, original)
            replacement = {
                "decisions": [
                    {"id": "region", "question": "Choose", "options": ["east"]}
                ]
            }
            original_match = entrypoint._blocking_decisions_match
            match_calls = 0

            def mutate_after_match(*args, **kwargs):
                nonlocal match_calls
                matches = original_match(*args, **kwargs)
                match_calls += 1
                if match_calls == 3:
                    atomic_write_json(blocking, replacement)
                return matches

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._blocking_decisions_match",
                side_effect=mutate_after_match,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("changed", stderr.getvalue())
            self.assertEqual(read_json(blocking), original)
            self.assertFalse((planning / "resolved-decisions.json").exists())
            self.assertEqual(list(planning.glob(".blocking-decisions.json.answer-*")), [])
            recoverable = list(
                planning.glob(".blocking-decisions.json.replacement-*")
            )
            self.assertEqual(len(recoverable), 1)
            self.assertEqual(read_json(recoverable[0]), replacement)

    def test_open_blocking_decisions_inode_mutation_cannot_commit_stale_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "open-inode-race-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            replacement = {
                "decisions": [
                    {"id": "region", "question": "Choose", "options": ["east"]}
                ]
            }
            held_descriptor = os.open(blocking, os.O_WRONLY)
            original_match = entrypoint._blocking_decisions_match
            match_calls = 0

            def mutate_claimed_inode_after_match(*args, **kwargs):
                nonlocal match_calls
                matches = original_match(*args, **kwargs)
                match_calls += 1
                if match_calls == 3:
                    payload = (
                        json.dumps(replacement, indent=2, sort_keys=True) + "\n"
                    ).encode("utf-8")
                    os.ftruncate(held_descriptor, 0)
                    os.lseek(held_descriptor, 0, os.SEEK_SET)
                    os.write(held_descriptor, payload)
                    os.fsync(held_descriptor)
                return matches

            stderr = io.StringIO()
            try:
                with patch("builtins.input", return_value="1"), patch(
                    "manageroo.entrypoint._blocking_decisions_match",
                    side_effect=mutate_claimed_inode_after_match,
                ):
                    with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                        code = _decisions_main(["answer", run_id, "--repo", str(repo)])
            finally:
                os.close(held_descriptor)

            self.assertEqual(code, 2)
            self.assertIn("changed", stderr.getvalue())
            self.assertEqual(read_json(blocking), replacement)
            self.assertFalse((planning / "resolved-decisions.json").exists())
            self.assertEqual(list(planning.glob(".blocking-decisions.json.answer-*")), [])

    def test_blocking_decisions_replacement_after_restore_read_cannot_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "restore-read-race-run"
            planning = (
                repo / ".manageroo" / "runs" / run_id / "artifacts" / "planning"
            )
            planning.mkdir(parents=True)
            blocking = planning / "blocking-decisions.json"
            atomic_write_json(
                blocking,
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            replacement = {
                "decisions": [
                    {"id": "region", "question": "Choose", "options": ["east"]}
                ]
            }
            original_read = entrypoint._read_json_at
            read_calls = 0

            def mutate_after_restore_read(*args, **kwargs):
                nonlocal read_calls
                payload = original_read(*args, **kwargs)
                read_calls += 1
                if read_calls == 6:
                    atomic_write_json(blocking, replacement)
                return payload

            stderr = io.StringIO()
            with patch("builtins.input", return_value="1"), patch(
                "manageroo.entrypoint._read_json_at",
                side_effect=mutate_after_restore_read,
            ):
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertGreaterEqual(read_calls, 6)
            self.assertEqual(code, 2)
            self.assertIn("changed", stderr.getvalue())
            self.assertEqual(read_json(blocking), replacement)
            self.assertFalse((planning / "resolved-decisions.json").exists())
            self.assertEqual(list(planning.glob(".blocking-decisions.json.answer-*")), [])

    def test_answer_rejects_external_symlinked_planning_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            run_id = "symlinked-planning-run"
            artifacts = repo / ".manageroo" / "runs" / run_id / "artifacts"
            artifacts.mkdir(parents=True)
            external = root / "external"
            external.mkdir()
            atomic_write_json(
                external / "blocking-decisions.json",
                {
                    "decisions": [
                        {"id": "deployment", "question": "Choose", "options": ["one"]}
                    ]
                },
            )
            try:
                (artifacts / "planning").symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink creation is unavailable: {exc}")

            stderr = io.StringIO()
            with patch(
                "builtins.input", side_effect=AssertionError("input must not be called")
            ):
                with redirect_stderr(stderr):
                    code = _decisions_main(["answer", run_id, "--repo", str(repo)])

            self.assertEqual(code, 2)
            self.assertIn("Planning artifact path cannot contain symlinks", stderr.getvalue())
            self.assertFalse((external / "resolved-decisions.json").exists())
            self.assertFalse((external / "cache").exists())


if __name__ == "__main__":
    unittest.main()
