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
    _clawpatch_version,
    _commit_attempt,
    _external_state_home,
    _execute_fix,
    _fix_command,
    _is_clawpatch_argv,
    _json_clawpatch,
    _load_release_progress,
    _must_clawpatch,
    _next_finding,
    _patch_attempt_from_show,
    _parse_json_output,
    _platform_command,
    _prepare_fresh_release,
    _publish_final_state,
    _push_and_verify,
    _release_clawpatch_env,
    _require_synchronized_remote_branch,
    _revalidate,
    _review_all_features,
    _run_project_gates,
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
        manageroo = repo / ".manageroo"
        manageroo.mkdir()
        (manageroo / "config.toml").write_text(
            "[safety]\n"
            'allowed_programs = ["git"]\n\n'
            "[[verification.gates]]\n"
            'id = "clean-baseline"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            'argv = ["git", "status", "--porcelain"]\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)

    @staticmethod
    def init_plain_repo(repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        (repo / ".gitignore").write_text(".clawpatch/\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_external_sweep_runs_in_plain_git_repo_without_manageroo_files(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            manageroo_state = root / "manageroo-owned-state"
            self.init_plain_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 1},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.side_effect = [
                ("fnd_one", {"finding": {"id": "fnd_one", "status": "open"}}),
                (None, {"finding": None}),
            ]
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "open"},
                "patchAttempts": [],
            }

            def complete_fix(*_args, **_kwargs):
                self.assertFalse((repo / ".manageroo").exists())
                self.assertEqual(
                    subprocess.check_output(
                        ["git", "status", "--porcelain"], cwd=repo, text=True
                    ),
                    "",
                )
                return ({"finding_id": "fnd_one", "commit": "abc123"}, False)

            execute_fix.side_effect = complete_fix
            final_closure.return_value = {"pushed": False}

            with patch(
                "manageroo.clawpatch_release._external_state_home",
                return_value=manageroo_state,
                create=True,
            ):
                report = release_sweep(
                    repo,
                    apply=True,
                    branch="current",
                    integration_mode="external",
                )

            proof_path = Path(report["proof_path"])
            self.assertIn(manageroo_state, proof_path.parents)
            self.assertTrue(proof_path.is_file())
            self.assertFalse((repo / ".manageroo").exists())
            self.assertFalse((repo / ".git" / "manageroo").exists())
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True),
                "",
            )

    @patch("manageroo.clawpatch_release.sys.base_prefix", "/usr")
    @patch(
        "manageroo.clawpatch_release.sys.prefix",
        "/home/test/.local/share/clawpatch-supervise/venv",
    )
    def test_dedicated_external_venv_owns_its_state_beside_the_install(self):
        self.assertEqual(
            _external_state_home(),
            Path("/home/test/.local/share/clawpatch-supervise/state"),
        )

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_external_fresh_migrates_legacy_checkpoint_before_exact_cleanup(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=["app.py"],
            )
            source.write_text("interrupted ClawPatch repair\n", encoding="utf-8")
            manageroo_state = root / "manageroo-owned-state"
            json_clawpatch.side_effect = [
                {"created": True},
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 0},
            ]
            review_all.return_value = {
                "review": {"reviewed": 0, "findings": 0},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            with patch(
                "manageroo.clawpatch_release._external_state_home",
                return_value=manageroo_state,
            ):
                report = release_sweep(
                    repo,
                    apply=True,
                    branch="current",
                    fresh=True,
                    integration_mode="external",
                )

            self.assertTrue(report["ok"])
            self.assertEqual(source.read_text(encoding="utf-8"), "before\n")
            self.assertFalse(
                (repo / ".manageroo/cache/clawpatch-release-progress.json").exists()
            )
            self.assertFalse(
                next(manageroo_state.rglob("clawpatch-release-progress.json"), None)
            )
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True),
                "",
            )

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_external_fresh_discards_current_source_changes_without_checkpoint(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            self.init_plain_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            source.write_text("discard this external fresh work\n", encoding="utf-8")
            stale = repo / ".clawpatch" / "findings" / "stale.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}\n", encoding="utf-8")
            manageroo_state = root / "manageroo-owned-state"
            json_clawpatch.side_effect = [
                {"created": True},
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 0},
            ]
            review_all.return_value = {
                "review": {"reviewed": 0, "findings": 0},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            with patch(
                "manageroo.clawpatch_release._external_state_home",
                return_value=manageroo_state,
            ):
                report = release_sweep(
                    repo,
                    apply=True,
                    branch="current",
                    fresh=True,
                    integration_mode="external",
                )

            self.assertTrue(report["ok"])
            self.assertEqual(source.read_text(encoding="utf-8"), "before\n")
            self.assertFalse(stale.exists())
            self.assertEqual(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True),
                "",
            )

    @patch("manageroo.clawpatch_release.shutil.which", return_value="/usr/bin/clawpatch")
    @patch("manageroo.clawpatch_release._must_run")
    def test_clawpatch_release_sweep_requires_072_or_newer(self, must_run, _which):
        must_run.return_value = "0.7.1\n"
        with self.assertRaisesRegex(SafetyError, "0.7.2 or newer"):
            _clawpatch_version(Path("/repo"))

        must_run.return_value = "0.7.2\n"
        self.assertEqual(_clawpatch_version(Path("/repo")), "0.7.2")

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



    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_fresh_run_deletes_only_old_clawpatch_state_and_preserves_committed_config(
        self, json_clawpatch, _processes
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            state = repo / ".clawpatch"
            (state / "findings").mkdir(parents=True)
            config_text = '{"schemaVersion":1,"commands":{"test":"npm run test"}}\n'
            (state / "config.json").write_text(config_text, encoding="utf-8")
            (state / "findings" / "stale.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "add", "-f", ".clawpatch/config.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "config"], cwd=repo, check=True)
            checkpoint = repo / ".manageroo/cache/clawpatch-release-progress.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text("{}\n", encoding="utf-8")

            def initialize(*_args, **_kwargs):
                self.assertFalse(state.exists())
                state.mkdir()
                (state / "config.json").write_text('{"detected":true}\n', encoding="utf-8")
                return {"created": True}

            json_clawpatch.side_effect = initialize
            _prepare_fresh_release(repo, env={"PATH": "test"})

            self.assertFalse((state / "findings" / "stale.json").exists())
            self.assertFalse(checkpoint.exists())
            self.assertEqual((state / "config.json").read_text(encoding="utf-8"), config_text)
            self.assertEqual(
                json_clawpatch.call_args.args[1],
                ["clawpatch", "init", "--json"],
            )

    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_fresh_run_discards_only_checkpoint_owned_interrupted_source(
        self, json_clawpatch, _processes
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            unrelated = repo / "notes.txt"
            source.write_text("original\n", encoding="utf-8")
            unrelated.write_text("original notes\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py", "notes.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)

            finding_id = "fnd_sig-feat-library-abc123-1234_abcdef1234"
            state = repo / ".clawpatch"
            finding_path = state / "findings" / f"{finding_id}.json"
            finding_path.parent.mkdir(parents=True)
            finding_path.write_text(
                json.dumps(
                    {
                        "findingId": finding_id,
                        "status": "open",
                        "evidence": [{"path": "app.py"}],
                    }
                ),
                encoding="utf-8",
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id=finding_id,
                branch="master",
                head_before=head,
                phase="stopped",
                owned_paths=["app.py"],
            )
            source.write_text("interrupted Clawpatch repair\n", encoding="utf-8")

            def initialize(*_args, **_kwargs):
                state.mkdir()
                return {"created": True}

            json_clawpatch.side_effect = initialize
            _prepare_fresh_release(repo, env={"PATH": "test"})

            self.assertEqual(source.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "original notes\n")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "stash", "list"], cwd=repo, text=True
                ),
                "",
            )
            self.assertFalse(
                (repo / ".manageroo/cache/clawpatch-release-progress.json").exists()
            )

            unrelated.write_text("operator work\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyError, "refuses unrelated source changes"):
                _prepare_fresh_release(repo, env={"PATH": "test"})
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "operator work\n")

    def test_explicit_state_publication_commits_new_safe_clawpatch_state(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            (repo / ".gitignore").write_text(".manageroo/\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "track clawpatch state"], cwd=repo, check=True)
            feature = repo / ".clawpatch" / "features" / "feat_one.json"
            feature.parent.mkdir(parents=True)
            feature.write_text('{"featureId":"feat_one"}\n', encoding="utf-8")

            commit = _publish_final_state(repo, branch="master")

            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            self.assertEqual(commit, head)
            committed = subprocess.check_output(
                ["git", "show", "--pretty=", "--name-only", "HEAD"], cwd=repo, text=True
            ).splitlines()
            self.assertEqual(committed, [".clawpatch/features/feat_one.json"])
            self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True), "")

    @patch("manageroo.clawpatch_release._require_branch")
    @patch("manageroo.clawpatch_release._validate_attempt_paths")
    @patch("manageroo.clawpatch_release._source_paths")
    @patch("manageroo.clawpatch_release._must_run")
    def test_commit_accepts_reported_file_that_normalizes_to_no_staged_diff(
        self, must_run, source_paths, validate_attempt_paths, _require_branch
    ):
        files = ["package.json", "test/access.test.js", "test/package-entry.test.js"]
        source_paths.return_value = ["package.json", "test/package-entry.test.js"]
        must_run.side_effect = [
            "",
            "package.json\0test/package-entry.test.js\0",
            "",
            "",
            "abc123",
            "package.json\ntest/package-entry.test.js\n",
        ]

        commit = _commit_attempt(Path("C:/repo"), "fnd_one", files, branch="master")

        self.assertEqual(commit, "abc123")
        validate_attempt_paths.assert_called_once_with(Path("C:/repo"), files)
        self.assertEqual(
            must_run.call_args_list[0].args[0],
            ["git", "add", "--", *files],
        )

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

    def test_pushable_branch_must_match_the_live_origin_sha_before_any_fix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            remote = root / "remote.git"
            repo.mkdir()
            self.init_repo(repo)
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            self.assertEqual(_require_synchronized_remote_branch(repo, branch), head)

            (repo / "local-only.txt").write_text("ahead\n", encoding="utf-8")
            subprocess.run(["git", "add", "local-only.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "local only"], cwd=repo, check=True)
            with self.assertRaisesRegex(SafetyError, "not synchronized"):
                _require_synchronized_remote_branch(repo, branch)

    def test_exact_path_commit_and_push_verification_match_the_live_remote_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            remote = root / "remote.git"
            repo.mkdir()
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo, check=True)

            source.write_text("clawpatch repair\n", encoding="utf-8")
            state = repo / ".clawpatch" / "runs" / "state.json"
            state.parent.mkdir(parents=True)
            state.write_text("{}\n", encoding="utf-8")
            commit = _commit_attempt(repo, "fnd_one", ["app.py"], branch=branch)
            _push_and_verify(repo, branch, first=False)

            committed_paths = subprocess.check_output(
                ["git", "show", "--pretty=", "--name-only", commit], cwd=repo, text=True
            ).splitlines()
            local = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            remote_sha = subprocess.check_output(
                ["git", "ls-remote", "origin", f"refs/heads/{branch}"],
                cwd=repo,
                text=True,
            ).split()[0]

        self.assertEqual(committed_paths, ["app.py"])
        self.assertEqual(remote_sha, local)

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
                "phase": "stopped",
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

    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._run")
    def test_fix_exit_six_marks_attempt_unresolved(self, run, _processes):
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

    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._run")
    def test_fix_timeout_is_not_retried_and_kills_the_complete_child_group(self, run, _processes):
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
    def test_open_revalidation_returns_the_documented_same_finding_continuation(
        self, json_clawpatch
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            source.write_text("partial clawpatch repair\n", encoding="utf-8")
            json_clawpatch.return_value = {
                "finding": "fnd_one",
                "outcome": "open",
                "reasoning": "the same finding still needs another Clawpatch fix",
            }

            result = _revalidate(
                repo,
                "fnd_one",
                env={},
                expected_paths=["app.py"],
            )

        self.assertEqual(result["outcome"], "open")
        self.assertEqual(json_clawpatch.call_count, 1)

    @patch("manageroo.clawpatch_release._push_and_verify")
    @patch("manageroo.clawpatch_release._commit_attempt", return_value="partial123")
    @patch(
        "manageroo.clawpatch_release._revalidate",
        return_value={"finding": "fnd_one", "outcome": "open"},
    )
    @patch("manageroo.clawpatch_release._run_project_gates", return_value=[])
    @patch("manageroo.clawpatch_release._validate_attempt_paths")
    @patch(
        "manageroo.clawpatch_release._patch_attempt_from_show",
        return_value={"filesChanged": ["app.py"]},
    )
    @patch(
        "manageroo.clawpatch_release._show_finding",
        return_value={"finding": {"id": "fnd_one", "status": "uncertain"}},
    )
    @patch(
        "manageroo.clawpatch_release._fix_command",
        return_value={"patchAttempt": "pat_one"},
    )
    @patch("manageroo.clawpatch_release._require_no_process")
    @patch("manageroo.clawpatch_release._source_paths", return_value=[])
    def test_execute_fix_commits_and_pushes_open_attempt_as_continuation(
        self,
        _source_paths,
        _no_process,
        _fix,
        _show,
        _patch_attempt,
        _validate_paths,
        _gates,
        _revalidation,
        commit_attempt,
        push_and_verify,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()

            record, pushed = _execute_fix(
                repo,
                "fnd_one",
                inspected={"finding": {"id": "fnd_one", "status": "open"}},
                env={},
                push_mode="each",
                branch=branch,
                pushed=False,
                require_project_gates=False,
            )

        self.assertEqual(record["revalidation"]["outcome"], "open")
        self.assertEqual(record["commit"], "partial123")
        self.assertTrue(pushed)
        commit_attempt.assert_called_once_with(
            repo,
            "fnd_one",
            ["app.py"],
            branch=branch,
            outcome="open",
        )
        push_and_verify.assert_called_once_with(repo, branch, first=True)

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

        self.assertEqual(raised.exception.outcome, "revalidation-mutated-source")

    @patch("manageroo.clawpatch_release._run_clawpatch")
    def test_nonfix_clawpatch_timeout_stops_without_a_hidden_retry(self, run_clawpatch):
        argv = ["clawpatch", "show", "--finding", "fnd_one", "--json"]
        run_clawpatch.return_value = self.completed(argv, "partial\nTIMEOUT", 124)

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(SafetyError, "this command is not retried"):
                _must_clawpatch(repo, argv, env={})

        self.assertEqual(run_clawpatch.call_count, 1)

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



    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._run")
    def test_fix_requires_matching_finding_and_patch_attempt(self, run, _processes):
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

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
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

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[{"pid": 42}])
    def test_apply_refuses_a_second_clawpatch_process(self, _processes, _version):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            with self.assertRaisesRegex(SafetyError, "already active"):
                release_sweep(repo, apply=True, branch="current")

    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
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
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
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
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_lock_cleanup_uses_clawpatch_072_stale_only_contract(
        self, _version, _processes, json_clawpatch, final_closure
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 1, "lockFiles": 1, "openFindings": 0},
                {"removed": 1},
                {"features": 0},
                {"reviewed": 0, "findings": 0},
                {"dryRun": True, "wouldReview": 0},
                {"finding": None, "status": "open", "next": "clawpatch report --status open"},
            ]
            final_closure.return_value = {"pushed": False}

            release_sweep(repo, apply=True, branch="current")

        self.assertEqual(
            json_clawpatch.call_args_list[1].args[1],
            ["clawpatch", "clean-locks", "--stale-only", "--json"],
        )

    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._run_project_gates")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_red_repository_baseline_blocks_before_map_review_or_fix(
        self,
        _version,
        _processes,
        json_clawpatch,
        run_project_gates,
        execute_fix,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.return_value = {
                "activeLocks": 0,
                "lockFiles": 0,
                "openFindings": 96,
            }
            run_project_gates.side_effect = SafetyError(
                "repository baseline validation failed: tests/test_inventory.py"
            )

            with self.assertRaisesRegex(
                SafetyError,
                "repository baseline validation failed: tests/test_inventory.py",
            ):
                release_sweep(repo, apply=True, branch="current")

        run_project_gates.assert_called_once_with(
            repo.resolve(),
            finding_id="baseline-preflight",
            required=True,
        )
        self.assertEqual(json_clawpatch.call_count, 1)
        self.assertEqual(
            json_clawpatch.call_args.args[1],
            ["clawpatch", "status", "--json"],
        )
        execute_fix.assert_not_called()


    def test_project_gate_failure_surfaces_the_exact_command_output(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            (repo / ".manageroo" / "config.toml").write_text(
                "[safety]\n"
                'allowed_programs = ["git"]\n\n'
                "[[verification.gates]]\n"
                'id = "known-failure"\n'
                'kind = "test"\n'
                "required = true\n"
                "timeout_seconds = 60\n"
                'argv = ["git", "rev-parse", "--verify", "refs/heads/does-not-exist"]\n',
                encoding="utf-8",
            )

            with self.assertRaises(SafetyError) as raised:
                _run_project_gates(repo, finding_id="baseline-preflight")

        message = str(raised.exception)
        self.assertIn("known-failure", message)
        self.assertIn("git rev-parse --verify refs/heads/does-not-exist", message)
        self.assertIn("exit code: 128", message)
        self.assertIn("fatal: Needed a single revision", message)

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
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

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_open_revalidation_commits_and_reenters_same_finding_without_a_cap(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
    ):
        progress_events = []
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 1},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 0},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            queue = {
                "finding": {"id": "fnd_one", "status": "open"},
                "next": "clawpatch show --finding fnd_one",
            }
            next_finding.side_effect = [
                ("fnd_one", queue),
                ("fnd_one", queue),
                (None, {"finding": None}),
            ]
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            execute_fix.side_effect = [
                (
                    {
                        "finding_id": "fnd_one",
                        "revalidation": {"finding": "fnd_one", "outcome": "open"},
                        "commit": "partial123",
                    },
                    False,
                ),
                (
                    {
                        "finding_id": "fnd_one",
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                        "commit": "fixed456",
                    },
                    False,
                ),
            ]
            final_closure.return_value = {"pushed": False}

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                progress=progress_events.append,
            )

        self.assertEqual(execute_fix.call_count, 2)
        self.assertEqual(next_finding.call_count, 3)
        self.assertEqual(show_finding.call_count, 2)
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(len(report["continuations"]), 1)
        self.assertEqual(report["continuations"][0]["commit"], "partial123")
        self.assertEqual(
            [event["current"] for event in progress_events if event["phase"] == "finding"],
            [1, 1],
        )
        self.assertTrue(any(event["phase"] == "continuing" for event in progress_events))
        self.assertFalse(any(event["phase"] == "stopped" for event in progress_events))
        final_closure.assert_called_once()

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_missing_selected_finding_stops_without_remap_review_or_queue_advance(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
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
                "completion": {"wouldReview": 0},
            }
            next_finding.return_value = (
                "fnd_old",
                {"finding": {"id": "fnd_old", "status": "open"}},
            )
            show_finding.side_effect = _MissingFinding(
                "finding not found", finding_id="fnd_old"
            )

            with self.assertRaisesRegex(SafetyError, "stopped without remapping"):
                release_sweep(repo, apply=True, branch="current")

        execute_fix.assert_not_called()
        final_closure.assert_not_called()
        self.assertEqual(next_finding.call_count, 1)
        self.assertEqual(review_all.call_count, 1)
        self.assertEqual(
            [call.args[1] for call in json_clawpatch.call_args_list],
            [
                ["clawpatch", "status", "--json"],
                ["clawpatch", "map", "--json"],
            ],
        )

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_failed_fix_stops_once_without_stash_triage_retry_or_queue_advance(
        self,
        _version,
        _processes,
        json_clawpatch,
        review_all,
        next_finding,
        show_finding,
        execute_fix,
        final_closure,
    ):
        progress_events = []
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
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
            next_finding.return_value = ("fnd_one", queue)
            show_finding.return_value = inspected

            def fail_once(*_args, **_kwargs):
                source.write_text("clawpatch-owned failed repair\n", encoding="utf-8")
                raise _UnresolvedFinding(
                    "validation stayed open",
                    finding_id="fnd_one",
                    outcome="fix-validation-failed",
                )

            execute_fix.side_effect = fail_once

            with self.assertRaisesRegex(SafetyError, "stopped"):
                release_sweep(
                    repo,
                    apply=True,
                    branch="current",
                    progress=progress_events.append,
                )

            checkpoint = _load_release_progress(repo)
            source_text = source.read_text(encoding="utf-8")
            stash_list = subprocess.run(
                ["git", "stash", "list"],
                cwd=repo,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            ).stdout

        execute_fix.assert_called_once()
        final_closure.assert_not_called()
        self.assertEqual(next_finding.call_count, 1)
        self.assertEqual(source_text, "clawpatch-owned failed repair\n")
        self.assertEqual(stash_list, "")
        self.assertEqual(checkpoint["phase"], "stopped")
        self.assertEqual(checkpoint["owned_paths"], ["app.py"])
        self.assertNotIn(
            "triage",
            [
                argument
                for invocation in json_clawpatch.call_args_list
                for argument in invocation.args[1]
            ],
        )
        self.assertFalse(any(event["phase"] == "retry" for event in progress_events))





    def test_release_progress_is_durable_and_bound_to_the_current_finding(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch="main",
                head_before="abc123",
                phase="fix",
                owned_paths=[],
            )

            progress = _load_release_progress(repo)

        self.assertEqual(progress["finding_id"], "fnd_one")
        self.assertEqual(progress["branch"], "main")
        self.assertEqual(progress["head_before"], "abc123")
        self.assertEqual(progress["owned_paths"], [])
        self.assertEqual(progress["phase"], "fix")






if __name__ == "__main__":
    unittest.main()
