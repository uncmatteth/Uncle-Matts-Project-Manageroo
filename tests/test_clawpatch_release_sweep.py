from __future__ import annotations

import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from manageroo.clawpatch_release import (
    SUPERVISOR_REPOSITORY,
    TRANSIENT_EXIT_CODE,
    format_release_sweep,
    release_sweep,
    supervisor_argv,
    supervisor_state_root,
)
from manageroo.errors import SafetyError
from manageroo.entrypoint import _clawpatch_main

ROOT = Path(__file__).resolve().parents[1]


class StandaloneClawpatchAdapterTests(unittest.TestCase):
    def test_repository_release_gate_approves_its_executable(self):
        config_path = ROOT / ".manageroo" / "config.toml"
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)

        allowed = config.get("safety", {}).get("allowed_programs", [])
        for gate in config.get("verification", {}).get("gates", []):
            executable = Path(gate["argv"][0]).name
            self.assertIn(executable, allowed, msg=f"unapproved gate executable: {executable}")

    def test_manageroo_cli_preserves_transient_supervisor_exit(self):
        report = {
            "ok": False,
            "apply": True,
            "exit_code": 75,
            "transient": True,
        }
        with patch("manageroo.entrypoint.release_sweep", return_value=report), redirect_stdout(
            StringIO()
        ):
            result = _clawpatch_main(["release-sweep", "--apply"])

        self.assertEqual(result, 75)

    def test_dry_run_is_a_read_only_standalone_plan(self):
        def run(*_args, **_kwargs):
            self.fail("plan mode must not start the standalone supervisor")

        with tempfile.TemporaryDirectory() as temp:
            report = release_sweep(Path(temp), branch="current", timeout_minutes=60, run=run)

        self.assertTrue(report["ok"])
        self.assertFalse(report["apply"])
        self.assertEqual(report["repository"], SUPERVISOR_REPOSITORY)
        self.assertIn("--fresh", report["command"])
        self.assertIn("--timeout-minutes", report["command"])
        self.assertIn("CLAWPATCH SUPERVISOR: PLAN", format_release_sweep(report))

    def test_supervisor_argv_forwards_every_release_option(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            resolved_repo = repo.resolve()
            argv = supervisor_argv(
                repo,
                branch="release/test",
                push_mode="final",
                publish_clawpatch_state=True,
                trusted_host_codex_sandbox_bypass=True,
                fresh=False,
                timeout_minutes=42,
                executable="/opt/clawpatch-supervise",
            )

        self.assertEqual(
            argv,
            [
                "/opt/clawpatch-supervise",
                "--repo",
                str(resolved_repo),
                "--branch",
                "release/test",
                "--push",
                "final",
                "--timeout-minutes",
                "42",
                "--resume-stopped",
                "--publish-clawpatch-state",
                "--trusted-host-codex-sandbox-bypass",
            ],
        )

    def test_adapter_forwards_exact_argv_without_a_shell(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0)

        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "clawpatch-supervise"
            executable.write_text("", encoding="utf-8")
            with patch(
                "manageroo.clawpatch_release._supervisor_path",
                return_value=str(executable),
            ), patch(
                "manageroo.clawpatch_release.supervisor_runtime_gate_ready",
                return_value=True,
            ), patch(
                "manageroo.clawpatch_release.supervisor_runtime_lock"
            ) as runtime_lock:
                report = release_sweep(
                    Path(temp),
                    apply=True,
                    branch="current",
                    push_mode="none",
                    fresh=False,
                    timeout_minutes=60,
                    run=run,
                )

        self.assertTrue(report["ok"])
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], str(executable))
        self.assertIn("--resume-stopped", argv)
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["check"], False)
        runtime_lock.assert_not_called()

    def test_transient_exit_code_is_preserved_for_service_policy(self):
        def run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, TRANSIENT_EXIT_CODE)

        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "clawpatch-supervise"
            executable.write_text("", encoding="utf-8")
            with patch(
                "manageroo.clawpatch_release._supervisor_path",
                return_value=str(executable),
            ), patch(
                "manageroo.clawpatch_release.supervisor_runtime_gate_ready",
                return_value=True,
            ):
                report = release_sweep(Path(temp), apply=True, run=run)

        self.assertFalse(report["ok"])
        self.assertTrue(report["transient"])
        self.assertEqual(report["exit_code"], 75)

    def test_terminal_exit_code_is_preserved(self):
        def run(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 2)

        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.clawpatch_release._supervisor_path",
            return_value="/opt/clawpatch-supervise",
        ), patch(
            "manageroo.clawpatch_release.supervisor_runtime_gate_ready",
            return_value=True,
        ):
            report = release_sweep(Path(temp), apply=True, run=run)

        self.assertFalse(report["ok"])
        self.assertFalse(report["transient"])
        self.assertEqual(report["exit_code"], 2)

    def test_process_start_error_becomes_safety_error(self):
        def run(_argv, **_kwargs):
            raise OSError("not executable")

        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.clawpatch_release._supervisor_path",
            return_value="/opt/clawpatch-supervise",
        ), patch(
            "manageroo.clawpatch_release.supervisor_runtime_gate_ready",
            return_value=True,
        ), self.assertRaisesRegex(SafetyError, "Could not start.*not executable"):
            release_sweep(Path(temp), apply=True, run=run)

    def test_state_root_is_queried_from_standalone_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            state = Path(temp) / "state"
            repo.mkdir()

            def run(argv, **kwargs):
                self.assertEqual(argv[-1], "--print-state-path")
                self.assertEqual(kwargs["shell"], False)
                return subprocess.CompletedProcess(argv, 0, str(state) + "\n", "")

            with patch(
                "manageroo.clawpatch_release._supervisor_path",
                return_value="/opt/clawpatch-supervise",
            ):
                self.assertEqual(supervisor_state_root(repo, run=run), state.resolve())

    def test_state_root_must_remain_outside_target_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()

            def run(argv, **_kwargs):
                return subprocess.CompletedProcess(argv, 0, str(repo / ".state") + "\n", "")

            with patch(
                "manageroo.clawpatch_release._supervisor_path",
                return_value="/opt/clawpatch-supervise",
            ), self.assertRaises(SafetyError):
                supervisor_state_root(repo, run=run)

    def test_state_root_rejects_failed_malformed_and_unsafe_results(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            invalid_results = {
                "nonzero": subprocess.CompletedProcess([], 2, "", "query failed"),
                "multiline": subprocess.CompletedProcess([], 0, "/state/one\n/state/two\n", ""),
                "relative": subprocess.CompletedProcess([], 0, "relative/state\n", ""),
                "equal to repo": subprocess.CompletedProcess([], 0, str(repo) + "\n", ""),
                "inside repo": subprocess.CompletedProcess([], 0, str(repo / "state") + "\n", ""),
            }

            with patch(
                "manageroo.clawpatch_release._supervisor_path",
                return_value="/opt/clawpatch-supervise",
            ):
                for label, result in invalid_results.items():
                    with self.subTest(label=label), self.assertRaises(SafetyError):
                        supervisor_state_root(repo, run=lambda *_args, **_kwargs: result)

    def test_state_root_timeout_becomes_safety_error(self):
        def run(argv, **_kwargs):
            raise subprocess.TimeoutExpired(argv, 30)

        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.clawpatch_release._supervisor_path",
            return_value="/opt/clawpatch-supervise",
        ), self.assertRaisesRegex(SafetyError, "Could not query.*timed out"):
            supervisor_state_root(Path(temp), run=run)

    def test_format_release_sweep_distinguishes_every_outcome(self):
        self.assertEqual(
            format_release_sweep({"apply": True, "ok": True}),
            "CLAWPATCH SUPERVISOR: COMPLETE\n",
        )
        self.assertEqual(
            format_release_sweep(
                {"apply": True, "ok": False, "transient": True, "exit_code": 75}
            ),
            "CLAWPATCH SUPERVISOR: RETRYABLE STOP\nexit code: 75\n",
        )
        self.assertEqual(
            format_release_sweep(
                {"apply": True, "ok": False, "transient": False, "exit_code": 2}
            ),
            "CLAWPATCH SUPERVISOR: STOPPED\nexit code: 2\n",
        )

    def test_supervisor_argv_rejects_invalid_timeout(self):
        with self.assertRaises(SafetyError):
            supervisor_argv(Path("."), timeout_minutes=0)

    def test_supervisor_argv_rejects_invalid_push_mode(self):
        with self.assertRaises(SafetyError):
            supervisor_argv(Path("."), push_mode="sometimes")
