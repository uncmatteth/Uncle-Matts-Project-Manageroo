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
    _fix_command,
    _finish_finding,
    _json_command,
    _paths_after_gates,
    _release_clawpatch_env,
    release_sweep,
)
from manageroo.entrypoint import _clawpatch_main
from manageroo.errors import SafetyError


class ClawpatchReleaseSweepTests(unittest.TestCase):
    @staticmethod
    def completed(argv: list[str], output: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, code, output, None)

    @staticmethod
    def git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=repo,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()

    @patch("manageroo.clawpatch_release._must_run")
    def test_json_command_accepts_clawpatch_progress_before_final_json(self, must_run):
        must_run.return_value = (
            "clawpatch map start source=heuristic\n"
            "clawpatch map done features=34\n"
            '{"features":34,"next":"clawpatch review --limit 3"}\n'
        )
        self.assertEqual(_json_command(Path("/repo"), "map")["features"], 34)

    @patch("manageroo.clawpatch_release._must_run")
    def test_json_command_scopes_trusted_host_bypass_to_clawpatch_child(self, must_run):
        must_run.return_value = '{"features":34}\n'
        child_env = {"CLAWPATCH_CODEX_SANDBOX": "bypass"}

        self.assertEqual(
            _json_command(Path("/repo"), "map", clawpatch_env=child_env)["features"],
            34,
        )
        self.assertEqual(must_run.call_args.kwargs["env"], child_env)

    @patch.dict("manageroo.clawpatch_release.os.environ", {}, clear=True)
    def test_release_env_extends_clawpatch_worker_timeout_without_default_bypass(self):
        child_env = _release_clawpatch_env(trusted_host_codex_sandbox_bypass=False)

        self.assertEqual(child_env["CLAWPATCH_CODEX_TIMEOUT_MS"], "1800000")
        self.assertNotIn("CLAWPATCH_CODEX_SANDBOX", child_env)

    @patch("manageroo.clawpatch_release._must_run")
    def test_json_command_rejects_non_whitespace_after_final_json(self, must_run):
        must_run.return_value = '{"features":34}\nunsafe trailing output\n'
        with self.assertRaisesRegex(SafetyError, "valid JSON"):
            _json_command(Path("/repo"), "map")

    @patch("manageroo.clawpatch_release._run")
    def test_fix_exit_six_advances_to_controller_gates_and_revalidation(self, run):
        run.return_value = self.completed(
            ["clawpatch", "fix"],
            "error: validation failed after applying fix\n",
            6,
        )

        result = _fix_command(
            Path("/repo"),
            "fnd_one",
            state_dir=None,
            clawpatch_env={"PATH": "/tools"},
        )

        self.assertEqual(result["status"], "validation-pending")
        self.assertEqual(result["exit_code"], 6)

    @patch(
        "manageroo.clawpatch_release._changed_paths",
        return_value=["BUILD-VALIDATION.json", "src/app.py"],
    )
    def test_gate_generated_release_proof_joins_exact_fix_commit(self, _changed):
        self.assertEqual(
            _paths_after_gates(Path("/repo"), ["src/app.py"]),
            ["BUILD-VALIDATION.json", "src/app.py"],
        )

    @patch("manageroo.clawpatch_release.atomic_write_json")
    @patch("manageroo.clawpatch_release._paths_after_gates", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch(
        "manageroo.clawpatch_release._json_command",
        return_value={"finding": "fnd_one", "outcome": "open"},
    )
    @patch("manageroo.clawpatch_release._must_run")
    def test_open_revalidation_creates_explicit_partial_checkpoint(
        self, must_run, _json, _gates, _paths, _write
    ):
        def fake(argv, **_kwargs):
            if argv[:3] == ["git", "diff", "--cached"]:
                return "src/app.py\0"
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/release\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "abc123\n"
            return ""

        must_run.side_effect = fake
        checkpoint: dict = {"completed": []}
        record = _finish_finding(
            Path("/repo"),
            finding_id="fnd_one",
            paths=["src/app.py"],
            checkpoint=checkpoint,
            push_mode="none",
            branch="feature/release",
            state_dir=None,
            clawpatch_env=None,
        )

        self.assertFalse(record["cleared"])
        self.assertEqual(checkpoint["partial"][0]["finding_id"], "fnd_one")
        self.assertIn(
            ["git", "commit", "-m", "clawpatch partial: fnd_one"],
            [call.args[0] for call in must_run.call_args_list],
        )

    @patch("manageroo.clawpatch_release.atomic_write_json")
    @patch("manageroo.clawpatch_release._paths_after_gates", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._json_command", return_value={"outcome": "fixed"})
    @patch("manageroo.clawpatch_release._must_run")
    def test_finish_finding_rechecks_branch_before_commit(
        self, must_run, _json, _gates, _paths, _write
    ):
        def fake(argv, **_kwargs):
            if argv[:3] == ["git", "diff", "--cached"]:
                return "src/app.py\0"
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/other\n"
            return ""

        must_run.side_effect = fake

        with self.assertRaisesRegex(SafetyError, "cannot commit the finding"):
            _finish_finding(
                Path("/repo"),
                finding_id="fnd_one",
                paths=["src/app.py"],
                checkpoint={"completed": []},
                push_mode="none",
                branch="feature/release",
                state_dir=None,
                clawpatch_env=None,
            )

        commands = [call.args[0] for call in must_run.call_args_list]
        self.assertNotIn(
            ["git", "commit", "-m", "clawpatch fix: fnd_one"],
            commands,
        )

    @patch("manageroo.clawpatch_release.atomic_write_json")
    @patch("manageroo.clawpatch_release._paths_after_gates", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._json_command", return_value={"outcome": "fixed"})
    @patch("manageroo.clawpatch_release._must_run")
    def test_finish_finding_rechecks_branch_before_each_push(
        self, must_run, _json, _gates, _paths, _write
    ):
        branch_checks = iter(["feature/release\n", "feature/other\n"])

        def fake(argv, **_kwargs):
            if argv[:3] == ["git", "diff", "--cached"]:
                return "src/app.py\0"
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return next(branch_checks)
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "abc123\n"
            return ""

        must_run.side_effect = fake

        with patch("manageroo.clawpatch_release._push") as push:
            with self.assertRaisesRegex(SafetyError, "cannot push the release branch"):
                _finish_finding(
                    Path("/repo"),
                    finding_id="fnd_one",
                    paths=["src/app.py"],
                    checkpoint={"completed": [], "pushed": False},
                    push_mode="each",
                    branch="feature/release",
                    state_dir=None,
                    clawpatch_env=None,
                )

        push.assert_not_called()
        self.assertIn(
            ["git", "commit", "-m", "clawpatch fix: fnd_one"],
            [call.args[0] for call in must_run.call_args_list],
        )

    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._run")
    def test_default_is_a_non_mutating_plan(self, run, _which):
        run.side_effect = [
            self.completed(["git"], "/repo\n"),
            self.completed(["clawpatch"], "clawpatch 0.7.1\n"),
            self.completed(["git"], "main\n"),
            self.completed(["git"], "abc123\n"),
            self.completed(["git"], ""),
        ]

        report = release_sweep(Path("/repo"))

        self.assertTrue(report["ok"])
        self.assertFalse(report["apply"])
        self.assertIn("clawpatch next --status open", report["lifecycle"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertFalse(any("init" in command or "fix" in command for command in commands))

    @patch("manageroo.entrypoint.release_sweep")
    def test_public_command_forwards_explicit_mutation_controls(self, sweep):
        sweep.return_value = {"ok": True, "apply": True}
        output = StringIO()
        with redirect_stdout(output):
            code = _clawpatch_main([
                "release-sweep", "--repo", ".", "--apply", "--branch", "current",
                "--push", "final", "--max-findings", "4",
                "--trusted-host-codex-sandbox-bypass", "--json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(sweep.call_args.kwargs["push_mode"], "final")
        self.assertEqual(sweep.call_args.kwargs["max_findings"], 4)
        self.assertTrue(sweep.call_args.kwargs["apply"])
        self.assertTrue(sweep.call_args.kwargs["trusted_host_codex_sandbox_bypass"])

    def test_tracked_clawpatch_config_delegates_validation_to_manageroo_gates(self):
        config = json.loads(
            (Path(__file__).resolve().parents[1] / "clawpatch.config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            config["commands"],
            {"typecheck": None, "lint": None, "format": None, "test": None},
        )

    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="clawpatch 0.7.1")
    @patch("manageroo.clawpatch_release._json_command")
    @patch("manageroo.clawpatch_release._fix_command")
    def test_real_git_repository_gets_one_validated_exact_path_commit(
        self, fix_command, clawpatch, _version, _gates
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.git(repo, "init", "-q", "-b", "feature/release")
            self.git(repo, "config", "user.name", "Test")
            self.git(repo, "config", "user.email", "test@example.invalid")
            (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
            (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
            self.git(repo, "add", ".gitignore", "app.py")
            self.git(repo, "commit", "-q", "-m", "base")

            next_count = 0

            def fake(_repo, command, *args, **_kwargs):
                nonlocal next_count
                if command in {"doctor", "init", "map", "review", "show"}:
                    return {}
                if command == "next":
                    next_count += 1
                    return {"finding": {"findingId": "fnd_real"}} if next_count == 1 else {"finding": None}
                if command == "revalidate" and "--all" not in args:
                    return {"finding": "fnd_real", "outcome": "fixed"}
                if command == "revalidate":
                    return {"revalidated": 0, "open": 0, "uncertain": 0}
                if command == "report":
                    return {"total": 0, "items": []}
                raise AssertionError((command, args))

            clawpatch.side_effect = fake
            def fake_fix(*_args, **_kwargs):
                (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
                return {"status": "applied", "changedFiles": "app.py"}

            fix_command.side_effect = fake_fix
            report = release_sweep(repo, apply=True, branch="current")

            self.assertTrue(report["ok"])
            self.assertEqual(self.git(repo, "status", "--porcelain", "--untracked-files=all"), "")
            self.assertEqual(self.git(repo, "log", "-1", "--pretty=%s"), "clawpatch fix: fnd_real")
            self.assertEqual(self.git(repo, "show", "--pretty=", "--name-only", "HEAD"), "app.py")
            self.assertTrue(all(call.kwargs.get("state_dir") for call in clawpatch.call_args_list))

    def test_final_proof_rejects_missing_malformed_and_nonzero_counts(self):
        cases = (
            ("missing open", {}, {"total": 0}, "missing or malformed 'open' count"),
            (
                "missing uncertain",
                {"open": 0},
                {"total": 0},
                "missing or malformed 'uncertain' count",
            ),
            (
                "string open",
                {"open": "0", "uncertain": 0},
                {"total": 0},
                "missing or malformed 'open' count",
            ),
            (
                "boolean uncertain",
                {"open": 0, "uncertain": False},
                {"total": 0},
                "missing or malformed 'uncertain' count",
            ),
            (
                "nonzero open",
                {"open": 1, "uncertain": 0},
                {"total": 0},
                "still reports open or uncertain findings",
            ),
            (
                "missing total",
                {"open": 0, "uncertain": 0},
                {},
                "missing or malformed 'total' count",
            ),
            (
                "boolean total",
                {"open": 0, "uncertain": 0},
                {"total": False},
                "missing or malformed 'total' count",
            ),
            (
                "nonzero total",
                {"open": 0, "uncertain": 0},
                {"total": 1},
                "still reports open findings",
            ),
        )

        for label, final_validation, final_report, error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                repo = Path(temp)
                self.git(repo, "init", "-q", "-b", "feature/release")
                self.git(repo, "config", "user.name", "Test")
                self.git(repo, "config", "user.email", "test@example.invalid")
                (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
                self.git(repo, "add", "app.py")
                self.git(repo, "commit", "-q", "-m", "base")

                def fake_json(_repo, command, *args, **_kwargs):
                    if command in {"doctor", "init", "map"}:
                        return {}
                    if command == "next":
                        return {"finding": None}
                    if command == "revalidate" and "--all" in args:
                        return final_validation
                    if command == "report":
                        return final_report
                    raise AssertionError((command, args))

                with (
                    patch(
                        "manageroo.clawpatch_release._clawpatch_version",
                        return_value="clawpatch 0.7.1",
                    ),
                    patch(
                        "manageroo.clawpatch_release._json_command",
                        side_effect=fake_json,
                    ),
                    patch("manageroo.clawpatch_release._run_manageroo_gates") as gates,
                ):
                    with self.assertRaisesRegex(SafetyError, error):
                        release_sweep(
                            repo,
                            apply=True,
                            branch="current",
                            skip_review=True,
                        )

                gates.assert_not_called()
                self.assertFalse(
                    (repo / ".git" / "manageroo" / "clawpatch-release-proof.json").exists()
                )

    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._changed_paths", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._run")
    def test_apply_revalidates_before_staging_exact_paths(self, run, _which, _changed, _gates):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / ".git").mkdir()
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "config.json").write_text("{}", encoding="utf-8")

            def fake(argv, **_kwargs):
                joined = " ".join(argv)
                if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                    return self.completed(argv, str(repo) + "\n")
                if argv[:2] == ["clawpatch", "--version"]:
                    return self.completed(argv, "clawpatch 0.7.1\n")
                if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                    return self.completed(argv, "feature/release\n")
                if argv[:3] == ["git", "rev-parse", "HEAD"]:
                    return self.completed(argv, "abc123\n")
                if argv[:2] == ["git", "status"]:
                    return self.completed(argv, "")
                if "doctor" in argv or "init" in argv or "map" in argv or "review" in argv:
                    return self.completed(argv, "{}")
                if "next" in argv:
                    count = sum("next" in call.args[0] for call in run.call_args_list)
                    payload = '{"finding":{"findingId":"fnd_one"}}' if count == 1 else '{"finding":null}'
                    return self.completed(argv, payload)
                if "show" in argv:
                    return self.completed(argv, '{"finding":{"findingId":"fnd_one"}}')
                if "fix" in argv:
                    return self.completed(argv, '{"status":"applied","changedFiles":"src/app.py"}')
                if "revalidate" in argv and "--all" not in argv:
                    return self.completed(argv, '{"finding":"fnd_one","outcome":"fixed"}')
                if "revalidate" in argv:
                    return self.completed(argv, '{"revalidated":0,"open":0,"uncertain":0}')
                if "report" in argv:
                    return self.completed(argv, '{"total":0,"items":[]}')
                if argv[:2] == ["git", "add"]:
                    return self.completed(argv)
                if argv[:3] == ["git", "diff", "--cached"]:
                    return self.completed(argv, "src/app.py\0")
                if argv[:2] == ["git", "commit"]:
                    return self.completed(argv, "committed\n")
                raise AssertionError(argv)

            run.side_effect = fake
            report = release_sweep(repo, apply=True, branch="current")

        self.assertTrue(report["ok"])
        commands = [call.args[0] for call in run.call_args_list]
        revalidate_index = next(i for i, command in enumerate(commands) if "revalidate" in command and "--all" not in command)
        add_index = commands.index(["git", "add", "--", "src/app.py"])
        self.assertLess(revalidate_index, add_index)
        self.assertNotIn(["git", "add", "-A"], commands)

    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._changed_paths", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._run")
    def test_uncertain_revalidation_stops_without_commit(self, run, _which, _changed, _gates):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / ".git").mkdir()
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "config.json").write_text("{}", encoding="utf-8")

            def fake(argv, **_kwargs):
                if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                    return self.completed(argv, str(repo) + "\n")
                if argv[:2] == ["clawpatch", "--version"]:
                    return self.completed(argv, "clawpatch 0.7.1\n")
                if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                    return self.completed(argv, "feature/release\n")
                if argv[:3] == ["git", "rev-parse", "HEAD"]:
                    return self.completed(argv, "abc123\n")
                if argv[:2] == ["git", "status"]:
                    return self.completed(argv, "")
                if "next" in argv:
                    return self.completed(argv, '{"finding":{"findingId":"fnd_one"}}')
                if "fix" in argv:
                    return self.completed(argv, '{"status":"applied"}')
                if "revalidate" in argv:
                    return self.completed(argv, '{"outcome":"uncertain"}')
                return self.completed(argv, "{}")

            run.side_effect = fake
            with self.assertRaisesRegex(SafetyError, "did not clear"):
                release_sweep(repo, apply=True, branch="current", skip_review=True)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertFalse(any(command[:2] == ["git", "commit"] for command in commands))

    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._path_digests", return_value={"src/app.py": "digest"})
    @patch("manageroo.clawpatch_release._changed_paths", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._run")
    def test_resumes_a_checkpointed_fix_without_applying_it_twice(
        self, run, _which, _changed, _digests, _gates
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            state = repo / ".git" / "manageroo"
            state.mkdir(parents=True)
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "config.json").write_text("{}", encoding="utf-8")
            (state / "clawpatch-release-sweep.json").write_text(json.dumps({
                "phase": "fixed",
                "head": "abc123",
                "branch": "feature/release",
                "active_finding": "fnd_resume",
                "paths": ["src/app.py"],
                "path_digests": {"src/app.py": "digest"},
                "completed": [],
                "pushed": False,
            }), encoding="utf-8")

            def fake(argv, **_kwargs):
                if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                    return self.completed(argv, str(repo) + "\n")
                if argv[:2] == ["clawpatch", "--version"]:
                    return self.completed(argv, "clawpatch 0.7.1\n")
                if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                    return self.completed(argv, "feature/release\n")
                if argv[:3] == ["git", "rev-parse", "HEAD"]:
                    return self.completed(argv, "abc123\n")
                if argv[:2] == ["git", "status"]:
                    return self.completed(argv, " M src/app.py\n")
                if "revalidate" in argv and "--all" not in argv:
                    return self.completed(argv, '{"outcome":"fixed"}')
                if "revalidate" in argv:
                    return self.completed(argv, '{"revalidated":0,"open":0,"uncertain":0}')
                if "report" in argv:
                    return self.completed(argv, '{"total":0}')
                if "next" in argv:
                    return self.completed(argv, '{"finding":null}')
                if argv[:2] == ["git", "add"]:
                    return self.completed(argv)
                if argv[:3] == ["git", "diff", "--cached"]:
                    return self.completed(argv, "src/app.py\0")
                if argv[:2] == ["git", "commit"]:
                    return self.completed(argv)
                raise AssertionError(argv)

            status_calls = 0
            def clean_after_commit(argv, **kwargs):
                nonlocal status_calls
                if argv[:2] == ["git", "status"]:
                    status_calls += 1
                    if status_calls > 1:
                        return self.completed(argv, "")
                return fake(argv, **kwargs)

            run.side_effect = clean_after_commit
            report = release_sweep(repo, apply=True, branch="current")

        self.assertTrue(report["ok"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertFalse(any("fix" in command for command in commands))
        self.assertTrue(any(command[:2] == ["git", "commit"] for command in commands))

    @patch("manageroo.clawpatch_release._run_manageroo_gates", return_value=[])
    @patch("manageroo.clawpatch_release._path_digests", return_value={"src/app.py": "digest"})
    @patch("manageroo.clawpatch_release._changed_paths", return_value=["src/app.py"])
    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._run")
    def test_resume_rejects_checkpoint_from_another_same_head_branch(
        self, run, _which, _changed, _digests, gates
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            state = repo / ".git" / "manageroo"
            state.mkdir(parents=True)
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "config.json").write_text("{}", encoding="utf-8")
            (state / "clawpatch-release-sweep.json").write_text(json.dumps({
                "phase": "fixed",
                "head": "abc123",
                "branch": "feature/release",
                "active_finding": "fnd_resume",
                "paths": ["src/app.py"],
                "path_digests": {"src/app.py": "digest"},
                "completed": [],
                "pushed": False,
            }), encoding="utf-8")

            def fake(argv, **_kwargs):
                if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                    return self.completed(argv, str(repo) + "\n")
                if argv[:2] == ["clawpatch", "--version"]:
                    return self.completed(argv, "clawpatch 0.7.1\n")
                if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                    return self.completed(argv, "feature/other\n")
                if argv[:3] == ["git", "rev-parse", "HEAD"]:
                    return self.completed(argv, "abc123\n")
                if argv[:2] == ["git", "status"]:
                    return self.completed(argv, " M src/app.py\n")
                raise AssertionError(argv)

            run.side_effect = fake
            with self.assertRaisesRegex(SafetyError, "cannot resume the checkpoint"):
                release_sweep(repo, apply=True, branch="current", push_mode="each")

        gates.assert_not_called()
        commands = [call.args[0] for call in run.call_args_list]
        self.assertFalse(any(command[:2] == ["git", "commit"] for command in commands))
        self.assertFalse(any(command[:2] == ["git", "push"] for command in commands))


if __name__ == "__main__":
    unittest.main()
