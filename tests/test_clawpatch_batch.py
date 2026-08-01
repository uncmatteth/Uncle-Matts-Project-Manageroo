import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.clawpatch_batch import _run, batch_fix_open_findings, open_finding_ids
from manageroo.errors import SafetyError


class ClawpatchBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def completed(self, argv, code=0, output="", error=None):
        return subprocess.CompletedProcess(argv, code, output, error)

    @patch("manageroo.clawpatch_batch.subprocess.run")
    def test_run_captures_stdout_and_stderr_separately(self, subprocess_run):
        subprocess_run.return_value = self.completed(
            ["git"], output=str(self.repo) + "\n", error="warning on stderr\n"
        )

        result = _run(["git", "rev-parse", "--show-toplevel"], cwd=self.repo)

        self.assertEqual(result.stdout, str(self.repo) + "\n")
        self.assertEqual(result.stderr, "warning on stderr\n")
        self.assertIs(subprocess_run.call_args.kwargs["stderr"], subprocess.PIPE)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_open_finding_ids_uses_status_filtered_report_and_deduplicates(self, run, _which):
        run.side_effect = [
            self.completed(
                ["git"],
                output=str(self.repo) + "\n",
                error="warning: repository diagnostic\n",
            ),
            self.completed(
                ["clawpatch"],
                output=(
                    "# clawpatch report\n\nfindings: 2\n\n"
                    "id: fnd_one\nstatus: open\n\n"
                    "id: fnd_two\nstatus: open\n\n"
                    "id: fnd_one\n"
                ),
                error="id: fnd_stderr_only\n",
            ),
        ]
        ids, _ = open_finding_ids(self.repo)
        self.assertEqual(ids, ["fnd_one", "fnd_two"])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["clawpatch", "report", "--status", "open"],
        )

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_dry_run_never_fixes_or_commits(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\nid: fnd_two\n"),
        ]
        report = batch_fix_open_findings(self.repo, apply=False)
        self.assertTrue(report["ok"])
        self.assertEqual(report["finding_ids"], ["fnd_one", "fnd_two"])
        self.assertEqual(len(run.call_args_list), 3)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_apply_requires_clean_tree_before_first_fix(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\n"),
            self.completed(["git"], output=" M existing.py\n"),
        ]
        with self.assertRaises(SafetyError):
            batch_fix_open_findings(self.repo, apply=True)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn(["clawpatch", "fix", "--finding", "fnd_one"], commands)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_stops_at_first_failed_fix(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\nid: fnd_two\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["clawpatch"], code=1, output="fix failed\n"),
        ]
        report = batch_fix_open_findings(self.repo, apply=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["stopped_at"], "fnd_one")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn(["clawpatch", "fix", "--finding", "fnd_two"], commands)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_successful_fix_is_staged_by_exact_path_and_committed_per_finding(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n", error="root warning\n"),
            self.completed(["git"], output=str(self.repo) + "\n", error="root warning\n"),
            self.completed(["clawpatch"], output="id: fnd_one\n"),
            self.completed(["git"], output="", error="status warning\n"),
            self.completed(["git"], output="", error="status warning\n"),
            self.completed(["clawpatch"], output="fixed\n", error="fix warning\n"),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["git"], output="blob123\n"),
            self.completed(["git"], output=" M file.py\n", error="status warning\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output="100644 blob123 0\tfile.py\0"),
            self.completed(["git"], output="committed\n"),
            self.completed(["git"], output="abc123\n", error="head warning\n"),
        ]
        (self.repo / "file.py").write_text("fixed\n", encoding="utf-8")
        report = batch_fix_open_findings(self.repo, apply=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["results"][0]["commit"], "abc123")
        self.assertEqual(report["results"][0]["git_status_after_fix"], " M file.py\n")
        self.assertEqual(report["results"][0]["fix_output"], "fixed\nfix warning\n")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["git", "add", "--", "file.py"], commands)
        self.assertNotIn(["git", "add", "-A"], commands)
        self.assertIn(["git", "commit", "-m", "clawpatch fix: fnd_one"], commands)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_unrelated_change_after_fix_snapshot_is_not_staged(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["clawpatch"], output="fixed\n"),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["git"], output="blob123\n"),
            self.completed(["git"], output=" M file.py\n M unrelated.py\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output="100644 blob123 0\tfile.py\0"),
            self.completed(["git"], output="committed\n"),
            self.completed(["git"], output="abc123\n"),
        ]
        (self.repo / "file.py").write_text("fixed\n", encoding="utf-8")

        report = batch_fix_open_findings(self.repo, apply=True)

        self.assertTrue(report["ok"])
        add_commands = [
            call.args[0] for call in run.call_args_list if call.args[0][:2] == ["git", "add"]
        ]
        self.assertEqual(add_commands, [["git", "add", "--", "file.py"]])
        self.assertNotIn("unrelated.py", add_commands[0])

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_staged_content_drift_stops_before_commit(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["clawpatch"], output="fixed\n"),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["git"], output="captured-blob\n"),
            self.completed(["git"], output=" M file.py\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output="100644 different-blob 0\tfile.py\0"),
        ]
        (self.repo / "file.py").write_text("fixed\n", encoding="utf-8")

        report = batch_fix_open_findings(self.repo, apply=True)

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["results"][0]["error"],
            "staged content did not match the Clawpatch fix snapshot",
        )
        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn(["git", "commit", "-m", "clawpatch fix: fnd_one"], commands)

    @patch("manageroo.clawpatch_batch.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_batch._run")
    def test_concurrently_staged_unrelated_path_stops_before_commit(self, run, _which):
        run.side_effect = [
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["git"], output=str(self.repo) + "\n"),
            self.completed(["clawpatch"], output="id: fnd_one\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["clawpatch"], output="fixed\n"),
            self.completed(["git"], output="file.py\0"),
            self.completed(["git"], output=""),
            self.completed(["git"], output=""),
            self.completed(["git"], output="captured-blob\n"),
            self.completed(["git"], output=" M file.py\n M unrelated.py\n"),
            self.completed(["git"], output=""),
            self.completed(["git"], output="file.py\0unrelated.py\0"),
        ]
        (self.repo / "file.py").write_text("fixed\n", encoding="utf-8")

        report = batch_fix_open_findings(self.repo, apply=True)

        self.assertFalse(report["ok"])
        self.assertEqual(
            report["results"][0]["error"],
            "staged paths did not exactly match the Clawpatch fix snapshot",
        )
        commands = [call.args[0] for call in run.call_args_list]
        self.assertNotIn(["git", "commit", "-m", "clawpatch fix: fnd_one"], commands)


if __name__ == "__main__":
    unittest.main()
