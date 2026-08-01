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
    _command_from_next,
    _fix_command,
    _next_from_output,
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

    def test_reads_exact_next_command_from_json_or_plain_output(self):
        self.assertEqual(
            _next_from_output('{"next":"clawpatch review --limit 3 --jobs 2"}\n'),
            "clawpatch review --limit 3 --jobs 2",
        )
        self.assertEqual(
            _next_from_output("map complete\nnext: `clawpatch review --limit 3`\n"),
            "clawpatch review --limit 3",
        )

    def test_next_command_is_parsed_without_shell_and_rejects_placeholders(self):
        self.assertEqual(
            _command_from_next("clawpatch review --limit 3 --jobs 2"),
            ["clawpatch", "review", "--limit", "3", "--jobs", "2"],
        )
        with self.assertRaisesRegex(SafetyError, "placeholder"):
            _command_from_next("clawpatch triage --finding fnd_one --status <status>")
        with self.assertRaisesRegex(SafetyError, "Clawpatch command"):
            _command_from_next("git status")

    @patch("manageroo.clawpatch_release._run")
    def test_fix_exit_six_stops_immediately(self, run):
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
        self.assertIn("printed next", report["lifecycle"])

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._must_clawpatch")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_zero_open_flow_reaches_final_closure(
        self, _version, _processes, json_clawpatch, must_clawpatch, final_closure
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.return_value = {"activeLocks": 0, "lockFiles": 0}
            must_clawpatch.side_effect = [
                "next: clawpatch report --status open\n",
                "# clawpatch report\n\nfindings: 0\n",
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
    @patch("manageroo.clawpatch_release._must_clawpatch")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.1")
    def test_fix_flow_uses_only_execute_fix_contract(
        self, _version, _processes, json_clawpatch, must_clawpatch, execute_fix, final_closure
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.return_value = {"activeLocks": 0, "lockFiles": 0}
            must_clawpatch.side_effect = [
                "next: clawpatch fix --finding fnd_one\n",
                "next: clawpatch report --status open\n",
                "# clawpatch report\n\nfindings: 0\n",
            ]
            execute_fix.return_value = (
                {"finding_id": "fnd_one", "revalidation": {"finding": "fnd_one", "outcome": "fixed"}},
                False,
            )
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")

        self.assertEqual(report["finding_count"], 1)
        self.assertNotIn("publish_clawpatch_state", execute_fix.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
