from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from manageroo.clawpatch_release import (
    _UnresolvedFinding,
    _fix_command,
    _next_finding,
    _patch_attempt_from_show,
    _platform_command,
    _preserve_unresolved_source,
    _review_all_features,
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

        with self.assertRaisesRegex(SafetyError, "exit code: 6"):
            _fix_command(Path("/repo"), ["clawpatch", "fix", "--finding", "fnd_one"])

        self.assertEqual(
            run.call_args.args[0],
            ["clawpatch", "fix", "--finding", "fnd_one", "--json"],
        )

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

            report = release_sweep(repo, apply=True, branch="current")

        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(execute_fix.call_args.args[1], "fnd_one")
        self.assertEqual(
            execute_fix.call_args.kwargs["inspected"]["next"],
            "clawpatch triage --finding fnd_one --status <status>",
        )
        self.assertNotIn("publish_clawpatch_state", execute_fix.call_args.kwargs)

    @patch("manageroo.clawpatch_release._triage_unresolved")
    @patch("manageroo.clawpatch_release._preserve_unresolved_source")
    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_unresolved_finding_is_preserved_and_queue_finishes_without_complete_proof(
        self,
        _version,
        _processes,
        json_clawpatch,
        execute_fix,
        final_closure,
        preserve,
        triage,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0},
                {"features": 1},
                {"reviewed": 1, "findings": 1},
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
                {"total": 0, "items": []},
                {"total": 1, "items": [{"id": "fnd_one"}]},
                {"activeLocks": 0, "lockFiles": 0},
            ]
            execute_fix.side_effect = _UnresolvedFinding(
                "validation stayed open", finding_id="fnd_one", outcome="open"
            )
            preserve.return_value = {
                "created": True,
                "ref": "stash@{0}",
                "sha": "abc123",
                "paths": ["app.py"],
            }
            triage.return_value = {"finding": "fnd_one", "status": "uncertain"}

            report = release_sweep(repo, apply=True, branch="current")

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertEqual(report["unresolved_count"], 1)
        self.assertEqual(report["proof_path"], "")
        final_closure.assert_not_called()
        preserve.assert_called_once_with(repo.resolve(), "fnd_one", "open")
        triage.assert_called_once()


if __name__ == "__main__":
    unittest.main()
