from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import call, patch

from manageroo.clawpatch_release import (
    _MissingFinding,
    _UnresolvedFinding,
    _checkpoint_can_follow_supervisor_upgrade,
    _fix_command,
    _is_clawpatch_argv,
    _json_clawpatch,
    _load_release_progress,
    _must_clawpatch,
    _next_finding,
    _patch_attempt_from_show,
    _parse_json_output,
    _platform_command,
    _preserve_unresolved_source,
    _release_clawpatch_env,
    _revalidate,
    _reopen_current_finding,
    _review_all_features,
    _write_release_progress,
    _windows_clawpatch_processes,
    release_sweep,
)
from manageroo.entrypoint import _clawpatch_main
from manageroo.errors import SafetyError


class ClawpatchReleaseSweepTests(unittest.TestCase):
    @staticmethod
    def completed(argv: list[str], output: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, output, None)

    @staticmethod
    def init_repo(repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        (repo / ".gitignore").write_text(".clawpatch/\n.manageroo/\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)

    def test_json_parser_accepts_clawpatch_payload_before_progress_lines(self):
        output = (
            '{"features":35,"new":1,"changed":7,"stale":0,'
            '"source":"heuristic","usedAgent":false,'
            '"reason":"heuristic mapper selected","next":"clawpatch review --limit 3"}\n'
            "clawpatch map start source=heuristic existing=34 dryRun=false\n"
            "clawpatch map mapper-start mapper=python\n"
            "clawpatch map done features=35 usedAgent=false elapsed=0s\n"
        )

        payload = _parse_json_output(output, command="map --json")

        self.assertEqual(payload["features"], 35)
        self.assertEqual(payload["next"], "clawpatch review --limit 3")

    @patch.dict(
        "manageroo.clawpatch_release.os.environ",
        {"CLAWPATCH_CODEX_SANDBOX": "bypass"},
    )
    def test_release_environment_requires_explicit_authorization_for_sandbox_bypass(self):
        unauthorized = _release_clawpatch_env(trusted_host_codex_sandbox_bypass=False)
        authorized = _release_clawpatch_env(trusted_host_codex_sandbox_bypass=True)

        self.assertNotIn("CLAWPATCH_CODEX_SANDBOX", unauthorized)
        self.assertEqual(authorized["CLAWPATCH_CODEX_SANDBOX"], "bypass")

    def test_process_matcher_ignores_clawpatch_mentions_inside_gbrain_context(self):
        gbrain = [
            "bun",
            "/home/Tommy/.bun/bin/gbrain",
            "call",
            "volunteer_context",
            '{"window":"assistant: run clawpatch fix --finding fnd_one"}',
        ]

        self.assertFalse(_is_clawpatch_argv(gbrain))
        self.assertTrue(
            _is_clawpatch_argv(
                ["node", "/home/Tommy/.local/bin/clawpatch", "fix", "--finding", "fnd_one"]
            )
        )
        self.assertTrue(
            _is_clawpatch_argv(
                ["python", "/home/Tommy/.local/bin/clawpatch-supervise", "--repo", "."]
            )
        )

    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_next_uses_structured_open_finding_and_validates_show_handoff(self, json_clawpatch):
        json_clawpatch.return_value = {
            "finding": {"id": "fnd_one", "status": "open"},
            "next": "clawpatch show --finding fnd_one",
        }
        finding_id, payload = _next_finding(Path("/repo"), env={})
        self.assertEqual(finding_id, "fnd_one")
        self.assertEqual(payload["finding"]["status"], "open")

        json_clawpatch.return_value = {
            "finding": {"id": "fnd_one", "status": "uncertain"},
            "next": "clawpatch show --finding fnd_one",
        }
        with self.assertRaisesRegex(SafetyError, "non-open"):
            _next_finding(Path("/repo"), env={})

    def test_patch_attempt_comes_from_clawpatch_show_record(self):
        payload = {
            "patchAttempts": [
                {
                    "patchAttemptId": "pat_one",
                    "findingIds": ["fnd_one"],
                    "filesChanged": ["src/app.py"],
                }
            ]
        }
        record = _patch_attempt_from_show(payload, "pat_one", "fnd_one")
        self.assertEqual(record["filesChanged"], ["src/app.py"])

    @patch("manageroo.clawpatch_release.shutil.which")
    def test_windows_resolves_clawpatch_command_shim_without_a_shell(self, which):
        which.return_value = r"C:\Users\Test\AppData\Roaming\npm\clawpatch.cmd"
        command = _platform_command(
            ["clawpatch", "next", "--json"], platform_name="nt"
        )
        self.assertEqual(command[0], which.return_value)
        self.assertEqual(command[1:], ["next", "--json"])

    @patch("manageroo.clawpatch_release._run")
    @patch("manageroo.clawpatch_release.shutil.which", return_value="powershell.exe")
    def test_windows_process_inventory_uses_native_powershell(self, _which, run):
        run.return_value = self.completed(
            ["powershell.exe"],
            json.dumps(
                {
                    "ProcessId": 42,
                    "CommandLine": "node C:/Users/Test/AppData/Roaming/npm/node_modules/clawpatch review",
                }
            ),
        )
        processes = _windows_clawpatch_processes(Path("C:/repo"))
        self.assertEqual(processes[0]["pid"], 42)
        self.assertIn("conservative", processes[0]["cwd"])
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")

    def test_unresolved_source_attempt_is_preserved_in_verified_named_stash(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            source.write_text("after\n", encoding="utf-8")

            preserved = _preserve_unresolved_source(repo, "fnd_one", "open")

            self.assertTrue(preserved["created"])
            self.assertIn("manageroo clawpatch unresolved fnd_one", preserved["message"])
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--short"],
                    cwd=repo,
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                "",
            )
            stashed = subprocess.run(
                ["git", "stash", "show", "--name-only", preserved["ref"]],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.splitlines()
            self.assertEqual(stashed, ["app.py"])

    def test_exhausted_checkpoint_follows_only_a_disjoint_supervisor_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            finding_id = "fnd_one"
            finding_path = repo / ".clawpatch" / "findings" / f"{finding_id}.json"
            finding_path.parent.mkdir(parents=True)
            finding_path.write_text(
                json.dumps(
                    {
                        "findingId": finding_id,
                        "evidence": [{"path": "src/manageroo/release_ready.py"}],
                    }
                ),
                encoding="utf-8",
            )
            old_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            (repo / "README.md").write_text("controller docs\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "controller upgrade"], cwd=repo, check=True)
            progress = {
                "finding_id": finding_id,
                "head_before": old_head,
                "phase": "fix-attempts-exhausted",
            }

            self.assertTrue(_checkpoint_can_follow_supervisor_upgrade(repo, progress))

            source = repo / "src" / "manageroo" / "release_ready.py"
            source.parent.mkdir(parents=True)
            source.write_text("changed finding source\n", encoding="utf-8")
            subprocess.run(["git", "add", str(source.relative_to(repo))], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "finding source changed"], cwd=repo, check=True)
            self.assertFalse(_checkpoint_can_follow_supervisor_upgrade(repo, progress))

    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_complete_review_uses_mapped_feature_count_and_proves_zero_pending(
        self, json_clawpatch
    ):
        json_clawpatch.side_effect = [
            {"reviewed": 12, "findings": 4},
            {"dryRun": True, "wouldReview": 0},
        ]
        result = _review_all_features(Path("/repo"), env={}, mapped_features=12)
        self.assertEqual(result["review"]["reviewed"], 12)
        self.assertEqual(
            json_clawpatch.call_args_list[0].args[1],
            ["clawpatch", "review", "--limit", "12", "--json"],
        )
        self.assertEqual(
            json_clawpatch.call_args_list[1].args[1],
            ["clawpatch", "review", "--limit", "12", "--dry-run", "--json"],
        )

    @patch("manageroo.clawpatch_release._run")
    def test_fix_exit_six_marks_attempt_unresolved(self, run):
        run.return_value = self.completed(
            ["clawpatch", "fix"],
            "error: validation failed after applying fix\n",
            6,
        )

        with self.assertRaisesRegex(SafetyError, "exit code: 6") as raised:
            _fix_command(Path("/repo"), ["clawpatch", "fix", "--finding", "fnd_one"])

        self.assertEqual(raised.exception.outcome, "fix-validation-failed")

        self.assertEqual(
            run.call_args.args[0],
            ["clawpatch", "fix", "--finding", "fnd_one", "--json"],
        )
        self.assertTrue(run.call_args.kwargs["kill_process_group"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)

    @patch("manageroo.clawpatch_release._run")
    def test_fix_timeout_is_retryable_and_kills_the_complete_child_group(self, run):
        run.return_value = self.completed(
            ["clawpatch", "fix"],
            "partial child output\nTIMEOUT\n",
            124,
        )

        with self.assertRaisesRegex(SafetyError, "exit code: 124") as raised:
            _fix_command(Path("/repo"), ["clawpatch", "fix", "--finding", "fnd_one"])

        self.assertEqual(raised.exception.outcome, "timeout")
        self.assertTrue(run.call_args.kwargs["kill_process_group"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)

    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_uncertain_read_only_revalidation_escalates_without_rerunning_fix(
        self, json_clawpatch
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            source.write_text("clawpatch repair\n", encoding="utf-8")
            json_clawpatch.side_effect = [
                {
                    "finding": "fnd_one",
                    "outcome": "uncertain",
                    "reason": "targeted tests could not create a temporary directory",
                },
                {"finding": "fnd_one", "outcome": "fixed"},
            ]
            env = {"PATH": "/bin"}

            result = _revalidate(
                repo,
                "fnd_one",
                env=env,
                expected_paths=["app.py"],
            )

        self.assertEqual(result["outcome"], "fixed")
        self.assertTrue(result["managerooSandboxEscalated"])
        self.assertEqual(result["managerooInitialOutcome"], "uncertain")
        self.assertEqual(json_clawpatch.call_count, 2)
        self.assertNotIn("CLAWPATCH_CODEX_SANDBOX", env)
        self.assertNotIn(
            "CLAWPATCH_CODEX_SANDBOX",
            json_clawpatch.call_args_list[0].kwargs["env"],
        )
        self.assertEqual(
            json_clawpatch.call_args_list[1].kwargs["env"]["CLAWPATCH_CODEX_SANDBOX"],
            "workspace-write",
        )

    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_workspace_write_revalidation_cannot_silently_change_the_repair(
        self, json_clawpatch
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            source.write_text("clawpatch repair\n", encoding="utf-8")

            def revalidate_side_effect(*_args, **_kwargs):
                if json_clawpatch.call_count == 1:
                    return {"finding": "fnd_one", "outcome": "uncertain"}
                source.write_text("revalidator changed source\n", encoding="utf-8")
                return {"finding": "fnd_one", "outcome": "fixed"}

            json_clawpatch.side_effect = revalidate_side_effect

            with self.assertRaisesRegex(SafetyError, "must not alter source") as raised:
                _revalidate(repo, "fnd_one", env={}, expected_paths=["app.py"])

        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.outcome, "revalidation-mutated-source")

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_nonfix_clawpatch_timeout_stops_without_a_hidden_retry(self, run_clawpatch, sleep):
        argv = ["clawpatch", "show", "--finding", "fnd_one", "--json"]
        run_clawpatch.return_value = self.completed(argv, "partial\nTIMEOUT", 124)

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(SafetyError, "timed-out commands are not retried"):
                _must_clawpatch(repo, argv, env={})

        self.assertEqual(run_clawpatch.call_count, 1)
        sleep.assert_not_called()

    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_missing_show_finding_stops_immediately_without_transient_retries(
        self, run_clawpatch
    ):
        argv = ["clawpatch", "show", "--finding", "fnd_old", "--json"]
        run_clawpatch.return_value = self.completed(
            argv,
            "error: finding not found: fnd_old",
            1,
        )

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(_MissingFinding, "fnd_old"):
                _must_clawpatch(repo, argv, env={})

        self.assertEqual(run_clawpatch.call_count, 1)

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_nonfix_clawpatch_transient_failures_have_a_finite_retry_limit(
        self, run_clawpatch, sleep
    ):
        argv = ["clawpatch", "map", "--json"]
        run_clawpatch.return_value = self.completed(argv, "provider unavailable", 1)

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(SafetyError, "after 3 attempts"):
                _must_clawpatch(repo, argv, env={})

        self.assertEqual(run_clawpatch.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(1), call(2)])

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_json_clawpatch_announces_every_attempt_and_resets_phase_time(
        self, run_clawpatch, _sleep
    ):
        argv = ["clawpatch", "map", "--json"]
        run_clawpatch.side_effect = [
            self.completed(argv, "temporary provider failure", 1),
            self.completed(argv, json.dumps({"features": 4}), 0),
        ]
        events = []

        payload = _json_clawpatch(Path("/repo"), argv, env={}, progress=events.append)

        self.assertEqual(payload["features"], 4)
        self.assertEqual([event["phase"] for event in events], ["map", "map"])
        self.assertEqual([event["attempt"] for event in events], [1, 2])
        self.assertEqual([event["max_attempts"] for event in events], [3, 3])
        self.assertEqual([event["command"] for event in events], ["clawpatch map --json"] * 2)

    @patch("manageroo.clawpatch_release._run")
    def test_fix_requires_matching_finding_and_patch_attempt(self, run):
        run.return_value = self.completed(
            ["clawpatch", "fix"],
            json.dumps({"finding": "fnd_other", "patchAttempt": "pat_one", "status": "applied"}),
        )
        with self.assertRaisesRegex(SafetyError, "wrong finding"):
            _fix_command(Path("/repo"), ["clawpatch", "fix", "--finding", "fnd_one"])

        run.return_value = self.completed(
            ["clawpatch", "fix"],
            json.dumps({"finding": "fnd_one", "status": "applied"}),
        )
        with self.assertRaisesRegex(SafetyError, "patch-attempt"):
            _fix_command(Path("/repo"), ["clawpatch", "fix", "--finding", "fnd_one"])

    @patch("manageroo.entrypoint.release_sweep")
    def test_public_cli_has_no_batch_or_review_override_controls(self, sweep):
        sweep.return_value = {"ok": True, "apply": True, "finding_count": 0, "open_findings": 0}
        output = StringIO()
        with redirect_stdout(output):
            code = _clawpatch_main(
                [
                    "release-sweep", "--repo", ".", "--apply", "--branch", "current",
                    "--push", "final", "--publish-clawpatch-state",
                ]
            )
        self.assertEqual(code, 0)
        self.assertNotIn("review_limit", sweep.call_args.kwargs)
        self.assertNotIn("jobs", sweep.call_args.kwargs)
        self.assertNotIn("max_findings", sweep.call_args.kwargs)
        self.assertNotIn("skip_review", sweep.call_args.kwargs)
        self.assertTrue(sweep.call_args.kwargs["publish_clawpatch_state"])

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    def test_apply_refuses_preexisting_source_changes(self, _processes, _version):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            (repo / "app.py").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
            (repo / "app.py").write_text("dirty\n", encoding="utf-8")

            with self.assertRaisesRegex(SafetyError, "pre-existing source changes"):
                release_sweep(repo, apply=True, branch="current")

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[{"pid": 42}])
    def test_apply_refuses_a_second_clawpatch_process(self, _processes, _version):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(SafetyError, "already active"):
                release_sweep(repo, apply=True, branch="current")

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_dry_run_does_not_run_clawpatch(self, _version):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            report = release_sweep(repo, apply=False)
        self.assertTrue(report["ok"])
        self.assertFalse(report["apply"])
        self.assertIn("next/show", report["lifecycle"])

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_zero_open_flow_reaches_final_closure(
        self, _version, _processes, json_clawpatch, final_closure
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 4},
                {"reviewed": 4, "findings": 0},
                {"dryRun": True, "wouldReview": 0},
                {"finding": None, "status": "open", "next": "clawpatch report --status open"},
            ]
            final_closure.return_value = {"pushed": False}

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                publish_clawpatch_state=True,
            )

        self.assertEqual(report["open_findings"], 0)
        self.assertTrue(final_closure.call_args.kwargs["publish_clawpatch_state"])

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_fix_flow_uses_only_execute_fix_contract(
        self, _version, _processes, json_clawpatch, execute_fix, final_closure
    ):
        progress_events = []
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 3},
                {"reviewed": 3, "findings": 1},
                {"dryRun": True, "wouldReview": 0},
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "next": "clawpatch show --finding fnd_one",
                },
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "validation": ["python3 -m unittest"],
                    "patchAttempts": [],
                    "next": "clawpatch triage --finding fnd_one --status <status>",
                },
                {"finding": None, "status": "open", "next": "clawpatch report --status open"},
            ]
            execute_fix.return_value = (
                {"finding_id": "fnd_one", "revalidation": {"finding": "fnd_one", "outcome": "fixed"}},
                False,
            )
            final_closure.return_value = {"pushed": False}

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                progress=progress_events.append,
            )

        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(execute_fix.call_args.args[1], "fnd_one")
        self.assertEqual(
            execute_fix.call_args.kwargs["inspected"]["next"],
            "clawpatch triage --finding fnd_one --status <status>",
        )
        self.assertNotIn("publish_clawpatch_state", execute_fix.call_args.kwargs)
        self.assertEqual(progress_events[0]["phase"], "preflight")
        finding_event = next(event for event in progress_events if event["phase"] == "finding")
        self.assertEqual(finding_event["current"], 1)
        self.assertEqual(finding_event["total"], 1)
        self.assertEqual(finding_event["finding_id"], "fnd_one")
        self.assertEqual(finding_event["command"], "clawpatch show --finding fnd_one")
        self.assertEqual(finding_event["inspection"]["finding"]["id"], "fnd_one")

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._reopen_current_finding")
    @patch("manageroo.clawpatch_release._preserve_unresolved_source")
    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_unresolved_finding_is_preserved_reopened_and_retried_as_the_same_finding(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
        preserve,
        reopen,
        sleep,
    ):
        progress_events = []
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 1},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            queue = {
                "finding": {"id": "fnd_one", "status": "open"},
                "next": "clawpatch show --finding fnd_one",
            }
            inspected = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": ["python3 -m unittest"],
                "patchAttempts": [],
            }
            next_finding.side_effect = [("fnd_one", queue), (None, {})]
            show_finding.return_value = inspected
            success = {
                "finding_id": "fnd_one",
                "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
            }
            execute_fix.side_effect = [
                _UnresolvedFinding(
                    "validation stayed open", finding_id="fnd_one", outcome="open"
                ),
                (success, False),
            ]
            preserve.return_value = {
                "created": True,
                "ref": "stash@{0}",
                "sha": "abc123",
                "paths": ["app.py"],
            }
            reopen.return_value = inspected
            final_closure.return_value = {"pushed": False}

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                progress=progress_events.append,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual([call.args[1] for call in execute_fix.call_args_list], ["fnd_one", "fnd_one"])
        preserve.assert_called_once_with(repo.resolve(), "fnd_one", "open")
        reopen.assert_called_once()
        self.assertEqual(reopen.call_args.args, (repo.resolve(), "fnd_one"))
        self.assertIn("validation stayed open", reopen.call_args.kwargs["failure"])
        self.assertIn("stash@{0}", reopen.call_args.kwargs["failure"])
        self.assertIn("app.py", reopen.call_args.kwargs["failure"])
        self.assertEqual(reopen.call_args.kwargs["current_number"], 1)
        self.assertEqual(reopen.call_args.kwargs["total"], 1)
        self.assertIn(call(1), sleep.call_args_list)
        final_closure.assert_called_once()
        retry_event = next(event for event in progress_events if event["phase"] == "retry")
        self.assertEqual(retry_event["current"], 1)
        self.assertEqual(retry_event["total"], 1)
        self.assertEqual(retry_event["finding_id"], "fnd_one")
        self.assertEqual(retry_event["retry"], 1)
        self.assertEqual(
            [event["finding_id"] for event in progress_events if event["phase"] == "finding"],
            ["fnd_one"],
        )

    @patch("manageroo.clawpatch_release._reopen_current_finding")
    @patch("manageroo.clawpatch_release._preserve_unresolved_source")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_uncertain_after_revalidation_escalation_preserves_once_and_does_not_refix(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        preserve,
        reopen,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 1},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.return_value = (
                "fnd_one",
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "next": "clawpatch show --finding fnd_one",
                },
            )
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            execute_fix.side_effect = _UnresolvedFinding(
                "validation infrastructure remained uncertain",
                finding_id="fnd_one",
                outcome="uncertain",
                retryable=False,
            )
            preserve.return_value = {
                "created": True,
                "ref": "stash@{0}",
                "sha": "abc123",
                "paths": ["app.py"],
            }

            with self.assertRaisesRegex(SafetyError, "will not rerun the source fix"):
                release_sweep(repo, apply=True, branch="current")

        execute_fix.assert_called_once()
        preserve.assert_called_once_with(repo.resolve(), "fnd_one", "uncertain")
        reopen.assert_not_called()

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._reopen_current_finding")
    @patch("manageroo.clawpatch_release._preserve_unresolved_source")
    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_source_fix_recovery_starts_a_new_bounded_cycle_without_advancing(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
        preserve,
        reopen,
        _sleep,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 1},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.side_effect = [
                (
                    "fnd_one",
                    {
                        "finding": {"id": "fnd_one", "status": "open"},
                        "next": "clawpatch show --finding fnd_one",
                    },
                ),
                (None, {"finding": None, "next": "none"}),
            ]
            inspected = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            show_finding.return_value = inspected
            reopen.return_value = inspected
            execute_fix.side_effect = [
                _UnresolvedFinding(
                    "repair remained open", finding_id="fnd_one", outcome="open"
                )
                for _ in range(3)
            ] + [
                (
                    {"finding_id": "fnd_one", "commit": "abc123"},
                    False,
                )
            ]
            preserve.return_value = {
                "created": True,
                "ref": "stash@{0}",
                "sha": "abc123",
                "paths": ["app.py"],
            }

            final_closure.return_value = {"status": {"openFindings": 0}}
            progress_events = []

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                progress=progress_events.append,
            )

            checkpoint = _load_release_progress(repo)
            self.assertIsNone(checkpoint)
            self.assertEqual(report["finding_count"], 1)
            cycles = [event for event in progress_events if event["phase"] == "retry-cycle"]
            self.assertEqual(len(cycles), 1)
            self.assertEqual(cycles[0]["cycle"], 2)
            self.assertEqual(cycles[0]["finding_id"], "fnd_one")
            self.assertIn("stash@{0}", cycles[0]["preserved_stash"])

        self.assertEqual(execute_fix.call_count, 4)
        self.assertEqual(preserve.call_count, 3)
        self.assertEqual(reopen.call_count, 3)
        self.assertIn("stash@{0}", reopen.call_args.kwargs["failure"])
        self.assertIn("app.py", reopen.call_args.kwargs["failure"])
        self.assertEqual(next_finding.call_count, 2)
        final_closure.assert_called_once()

    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._show_finding")
    def test_reopen_current_finding_uses_clawpatch_state_and_requires_same_next_finding(
        self, show_finding, json_clawpatch, next_finding
    ):
        show_finding.side_effect = [
            {
                "finding": {"id": "fnd_one", "status": "uncertain"},
                "validation": [],
                "patchAttempts": [],
            },
            {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            },
        ]
        json_clawpatch.return_value = {"finding": "fnd_one", "status": "open"}
        next_finding.return_value = (
            "fnd_one",
            {
                "finding": {"id": "fnd_one", "status": "open"},
                "next": "clawpatch show --finding fnd_one",
            },
        )

        inspected = _reopen_current_finding(
            Path("/repo"),
            "fnd_one",
            env={},
            failure="project validation failed: focused symlink test still fails",
        )

        self.assertEqual(inspected["finding"]["status"], "open")
        self.assertEqual(
            json_clawpatch.call_args.args[1],
            [
                "clawpatch",
                "triage",
                "--finding",
                "fnd_one",
                "--status",
                "open",
                "--note",
                "Manageroo retry recovery evidence: project validation failed: focused symlink test still fails",
                "--json",
            ],
        )
        next_finding.assert_called_once_with(
            Path("/repo"), env={}, progress=None, current="?", total="?"
        )

    def test_release_progress_is_durable_and_bound_to_the_current_finding(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch="main",
                head_before="abc123",
                retry_count=2,
                phase="fix",
            )

            progress = _load_release_progress(repo)

        self.assertEqual(progress["finding_id"], "fnd_one")
        self.assertEqual(progress["branch"], "main")
        self.assertEqual(progress["head_before"], "abc123")
        self.assertEqual(progress["retry_count"], 2)
        self.assertEqual(progress["phase"], "fix")

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._reopen_current_finding")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_interrupted_dirty_attempt_is_preserved_and_resumed_from_durable_progress(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        show_finding,
        reopen,
        next_finding,
        execute_fix,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=head,
                retry_count=1,
                phase="fix",
            )
            source.write_text("interrupted patch\n", encoding="utf-8")
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 1},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            inspected = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            show_finding.return_value = inspected
            reopen.return_value = inspected
            next_finding.return_value = (None, {})
            execute_fix.return_value = (
                {
                    "finding_id": "fnd_one",
                    "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                },
                False,
            )
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")

            self.assertEqual(report["finding_count"], 1)
            self.assertEqual(execute_fix.call_args.args[1], "fnd_one")
            self.assertFalse((repo / ".manageroo/cache/clawpatch-release-progress.json").exists())
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--short"],
                    cwd=repo,
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout,
                "",
            )
            stash_message = subprocess.run(
                ["git", "stash", "list", "-1", "--format=%gs"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            self.assertIn("controller-interrupted", stash_message)

    def test_missing_interrupted_finding_clears_only_the_stale_checkpoint_and_uses_current_queue(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            _write_release_progress(
                repo,
                finding_id="fnd_old",
                branch=branch,
                head_before=head,
                retry_count=1,
                phase="retry",
            )
            inspection = {
                "finding": {"id": "fnd_new", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            with (
                patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1"),
                patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[]),
                patch("manageroo.clawpatch_release._json_clawpatch") as json_clawpatch,
                patch("manageroo.clawpatch_release._review_all_features") as review_all,
                patch("manageroo.clawpatch_release._show_finding") as show_finding,
                patch("manageroo.clawpatch_release._next_finding") as next_finding,
                patch("manageroo.clawpatch_release._execute_fix") as execute_fix,
                patch("manageroo.clawpatch_release._final_closure") as final_closure,
            ):
                json_clawpatch.side_effect = [
                    {"activeLocks": 0, "lockFiles": 0},
                    {"features": 1},
                ]
                review_all.return_value = {
                    "review": {"reviewed": 1, "findings": 1},
                    "completion": {"dryRun": True, "wouldReview": 0},
                }
                show_finding.side_effect = [
                    _MissingFinding("finding not found", finding_id="fnd_old"),
                    inspection,
                ]
                next_finding.side_effect = [
                    (
                        "fnd_new",
                        {
                            "finding": {"id": "fnd_new", "status": "open"},
                            "next": "clawpatch show --finding fnd_new",
                        },
                    ),
                    (None, {}),
                ]
                execute_fix.return_value = (
                    {
                        "finding_id": "fnd_new",
                        "revalidation": {"finding": "fnd_new", "outcome": "fixed"},
                    },
                    False,
                )
                final_closure.return_value = {"pushed": False}

                report = release_sweep(repo, apply=True, branch="current")

            self.assertEqual(report["finding_count"], 1)
            self.assertEqual(execute_fix.call_args.args[1], "fnd_new")
            self.assertFalse((repo / ".manageroo/cache/clawpatch-release-progress.json").exists())

    def test_missing_interrupted_finding_with_source_edits_keeps_checkpoint_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout.strip()
            _write_release_progress(
                repo,
                finding_id="fnd_old",
                branch=branch,
                head_before=head,
                retry_count=1,
                phase="fix",
            )
            source.write_text("interrupted repair\n", encoding="utf-8")
            with (
                patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1"),
                patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[]),
                patch("manageroo.clawpatch_release._json_clawpatch") as json_clawpatch,
                patch("manageroo.clawpatch_release._review_all_features") as review_all,
                patch(
                    "manageroo.clawpatch_release._show_finding",
                    side_effect=_MissingFinding("finding not found", finding_id="fnd_old"),
                ),
                patch("manageroo.clawpatch_release._execute_fix") as execute_fix,
            ):
                json_clawpatch.side_effect = [
                    {"activeLocks": 0, "lockFiles": 0},
                    {"features": 1},
                ]
                review_all.return_value = {
                    "review": {"reviewed": 1, "findings": 1},
                    "completion": {"dryRun": True, "wouldReview": 0},
                }

                with self.assertRaisesRegex(SafetyError, "source edits remain"):
                    release_sweep(repo, apply=True, branch="current")

            execute_fix.assert_not_called()
            self.assertEqual(json_clawpatch.call_count, 1)
            self.assertEqual(
                json_clawpatch.call_args.args[1], ["clawpatch", "status", "--json"]
            )
            self.assertEqual(source.read_text(encoding="utf-8"), "interrupted repair\n")
            self.assertTrue((repo / ".manageroo/cache/clawpatch-release-progress.json").is_file())


if __name__ == "__main__":
    unittest.main()
