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
    _UnresolvedFinding,
    _fix_command,
    _load_release_progress,
    _must_clawpatch,
    _next_finding,
    _patch_attempt_from_show,
    _parse_json_output,
    _platform_command,
    _preserve_unresolved_source,
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

    @patch("manageroo.clawpatch_release.time.sleep")
    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_nonfix_clawpatch_timeout_restarts_the_same_command(self, run_clawpatch, sleep):
        argv = ["clawpatch", "show", "--finding", "fnd_one", "--json"]
        run_clawpatch.side_effect = [
            self.completed(argv, "partial\nTIMEOUT", 124),
            self.completed(argv, json.dumps({"finding": {"id": "fnd_one"}}), 0),
        ]

        output = _must_clawpatch(Path("/repo"), argv, env={})

        self.assertEqual(json.loads(output)["finding"]["id"], "fnd_one")
        self.assertEqual(run_clawpatch.call_count, 2)
        sleep.assert_called_once_with(1)

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
                {"activeLocks": 0, "lockFiles": 0},
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
                {"activeLocks": 0, "lockFiles": 0},
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
        reopen.assert_called_once_with(repo.resolve(), "fnd_one", env=json_clawpatch.call_args_list[0].kwargs["env"])
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

        inspected = _reopen_current_finding(Path("/repo"), "fnd_one", env={})

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
                "Manageroo retry recovery: the previous Clawpatch-owned repair did not reach fixed.",
                "--json",
            ],
        )
        next_finding.assert_called_once_with(Path("/repo"), env={})

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


if __name__ == "__main__":
    unittest.main()
