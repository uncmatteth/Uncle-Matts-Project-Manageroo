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
    _final_closure,
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
    _rebuilt_generation_owns_checkpoint_source,
    _require_synchronized_remote_branch,
    _resume_stopped_attempt,
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
                {"created": True, "next": "clawpatch map"},
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
                (repo / "app.py").write_text("fixed\n", encoding="utf-8")
                return (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": ["app.py"],
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                        "commit": "",
                    },
                    False,
                )

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
            self.assertEqual(
                [invocation.args[1] for invocation in json_clawpatch.call_args_list],
                [
                    ["clawpatch", "init", "--json"],
                    ["clawpatch", "status", "--json"],
                    ["clawpatch", "map", "--json"],
                ],
            )

    @patch("manageroo.clawpatch_release.sys.base_prefix", "/usr")
    @patch(
        "manageroo.clawpatch_release.sys.prefix",
        "/home/test/.local/share/clawpatch-supervise/venv",
    )
    def test_dedicated_external_venv_owns_its_state_beside_the_install(self):
        self.assertEqual(
            _external_state_home(),
            Path("/home/test/.local/share/clawpatch-supervise/state").resolve(),
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
    def test_external_fresh_refuses_current_source_changes_without_checkpoint(
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
                with self.assertRaisesRegex(
                    SafetyError,
                    "A fresh Clawpatch run refuses unrelated source changes: app.py",
                ):
                    release_sweep(
                        repo,
                        apply=True,
                        branch="current",
                        fresh=True,
                        integration_mode="external",
                    )

            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "discard this external fresh work\n",
            )
            self.assertTrue(stale.exists())

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
        fallback = _release_clawpatch_env(
            trusted_host_codex_sandbox_bypass=False,
            allow_sandbox_bypass_fallback=True,
        )
        authorized = _release_clawpatch_env(trusted_host_codex_sandbox_bypass=True)

        self.assertNotIn("CLAWPATCH_CODEX_SANDBOX", unauthorized)
        self.assertNotIn("CLAWPATCH_CODEX_SANDBOX", fallback)
        self.assertEqual(fallback["MANAGEROO_CLAWPATCH_ALLOW_BYPASS_FALLBACK"], "1")
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

        finding_id, _payload = _next_finding(
            Path("/repo"), env={}, status="uncertain"
        )
        self.assertEqual(finding_id, "fnd_one")
        self.assertEqual(
            json_clawpatch.call_args.args[1],
            ["clawpatch", "next", "--status", "uncertain", "--json"],
        )

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
    def test_complete_review_uses_bounded_worker_waves_until_zero_pending(
        self, json_clawpatch
    ):
        json_clawpatch.side_effect = [
            {"dryRun": True, "wouldReview": 12, "jobs": 4},
            {"run": "run-1", "reviewed": 4, "findings": 1, "jobs": 4},
            {"dryRun": True, "wouldReview": 8, "jobs": 4},
            {"run": "run-2", "reviewed": 4, "findings": 2, "jobs": 4},
            {"dryRun": True, "wouldReview": 4, "jobs": 4},
            {"run": "run-3", "reviewed": 4, "findings": 1, "jobs": 4},
            {"dryRun": True, "wouldReview": 0, "jobs": 4},
        ]
        result = _review_all_features(Path("/repo"), env={}, mapped_features=12)
        self.assertEqual(result["review"]["reviewed"], 12)
        self.assertEqual(result["review"]["findings"], 4)
        self.assertEqual(result["review"]["runs"], ["run-1", "run-2", "run-3"])
        self.assertEqual(
            json_clawpatch.call_args_list[0].args[1],
            ["clawpatch", "review", "--limit", "12", "--dry-run", "--json"],
        )
        self.assertEqual(
            json_clawpatch.call_args_list[1].args[1],
            ["clawpatch", "review", "--limit", "4", "--json"],
        )
        self.assertEqual(
            json_clawpatch.call_args_list[3].args[1],
            ["clawpatch", "review", "--limit", "4", "--json"],
        )
        self.assertEqual(
            json_clawpatch.call_args_list[5].args[1],
            ["clawpatch", "review", "--limit", "4", "--json"],
        )

    @patch("manageroo.clawpatch_release._json_clawpatch")
    def test_complete_review_stops_when_a_batch_does_not_reduce_pending_features(
        self, json_clawpatch
    ):
        json_clawpatch.side_effect = [
            {"dryRun": True, "wouldReview": 12, "jobs": 4},
            {"run": "run-1", "reviewed": 4, "findings": 1, "jobs": 4},
            {"dryRun": True, "wouldReview": 12, "jobs": 4},
        ]

        with self.assertRaisesRegex(SafetyError, "did not reduce pending features"):
            _review_all_features(Path("/repo"), env={}, mapped_features=12)

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
    def test_external_uncertain_revalidation_uses_trusted_host_after_workspace_block(
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
                {"finding": "fnd_one", "outcome": "uncertain"},
                {
                    "finding": "fnd_one",
                    "outcome": "uncertain",
                    "reasoning": "Gradle socket-based lock service was sandbox-blocked",
                },
                {"finding": "fnd_one", "outcome": "fixed"},
            ]
            env = {"MANAGEROO_CLAWPATCH_ALLOW_BYPASS_FALLBACK": "1"}

            result = _revalidate(
                repo,
                "fnd_one",
                env=env,
                expected_paths=["app.py"],
            )

        self.assertEqual(result["outcome"], "fixed")
        self.assertTrue(result["managerooHostSandboxBypassed"])
        self.assertEqual(result["managerooWorkspaceWriteOutcome"], "uncertain")
        self.assertEqual(json_clawpatch.call_count, 3)
        self.assertEqual(
            json_clawpatch.call_args_list[1].kwargs["env"]["CLAWPATCH_CODEX_SANDBOX"],
            "workspace-write",
        )
        self.assertEqual(
            json_clawpatch.call_args_list[2].kwargs["env"]["CLAWPATCH_CODEX_SANDBOX"],
            "bypass",
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
    def test_execute_fix_leaves_open_attempt_for_local_iteration_controller(
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
        self.assertEqual(record["commit"], "")
        self.assertFalse(pushed)
        commit_attempt.assert_not_called()
        push_and_verify.assert_not_called()

    @patch("manageroo.clawpatch_release._push_and_verify")
    @patch(
        "manageroo.clawpatch_release._revalidate",
        return_value={"finding": "fnd_one", "outcome": "open"},
    )
    @patch("manageroo.clawpatch_release._run_project_gates", return_value=[])
    @patch("manageroo.clawpatch_release._show_finding")
    def test_stopped_open_attempt_remains_local_for_same_finding_iteration(
        self,
        show_finding,
        _gates,
        revalidate,
        push_and_verify,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
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
            source.write_text("partial Clawpatch repair\n", encoding="utf-8")
            checkpoint = {
                "finding_id": "fnd_one",
                "branch": branch,
                "head_before": head,
                "phase": "stopped",
                "owned_paths": ["app.py"],
            }
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "uncertain"},
                "validation": [],
                "patchAttempts": [
                    {
                        "patchAttemptId": "pat_one",
                        "status": "applied",
                        "findingIds": ["fnd_one"],
                        "filesChanged": ["app.py"],
                        "git": {"baseSha": head},
                    }
                ],
            }

            record, pushed = _resume_stopped_attempt(
                repo,
                checkpoint,
                env={},
                push_mode="each",
                branch=branch,
                pushed=False,
                require_project_gates=False,
            )

            status = subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo, text=True
            )

        self.assertTrue(record["resumed"])
        self.assertEqual(record["patch_attempt"], "pat_one")
        self.assertEqual(record["revalidation"]["outcome"], "open")
        self.assertEqual(record["commit"], "")
        self.assertIn("app.py", status)
        self.assertFalse(pushed)
        revalidate.assert_called_once()
        push_and_verify.assert_not_called()

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._revalidate")
    @patch("manageroo.clawpatch_release._run_project_gates", return_value=[])
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_relaunch_consumes_exact_stopped_attempt_then_reenters_same_open_finding(
        self,
        _version,
        _processes,
        show_finding,
        _gates,
        revalidate,
        json_clawpatch,
        review_all,
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
            source.write_text("first partial Clawpatch repair\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "clawpatch continuation: fnd_one"],
                cwd=repo,
                check=True,
            )
            attempt_base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            source.write_text("second partial Clawpatch repair\n", encoding="utf-8")
            inspection = {
                "finding": {"id": "fnd_one", "status": "uncertain"},
                "validation": [],
                "patchAttempts": [
                    {
                        "patchAttemptId": "pat_one",
                        "status": "applied",
                        "findingIds": ["fnd_one"],
                        "filesChanged": ["app.py"],
                        "git": {"baseSha": attempt_base},
                    }
                ],
            }
            show_finding.side_effect = [
                inspection,
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "validation": [],
                    "patchAttempts": [inspection["patchAttempts"][0]],
                },
            ]
            revalidate.return_value = {"finding": "fnd_one", "outcome": "open"}
            json_clawpatch.return_value = {
                "activeLocks": 0,
                "lockFiles": 0,
                "openFindings": 1,
            }
            queue = {
                "finding": {"id": "fnd_one", "status": "open"},
                "next": "clawpatch show --finding fnd_one",
            }
            next_finding.side_effect = [(None, {"finding": None})]
            def complete_fix(*_args, **_kwargs):
                source.write_text("completed Clawpatch repair\n", encoding="utf-8")
                return (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": ["app.py"],
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                        "commit": "",
                    },
                    False,
                )

            execute_fix.side_effect = complete_fix
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")

        self.assertEqual(len(report["continuations"]), 1)
        self.assertTrue(report["continuations"][0]["resumed"])
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(execute_fix.call_count, 1)
        self.assertEqual(next_finding.call_count, 1)
        review_all.assert_not_called()
        self.assertEqual(
            [invocation.args[1] for invocation in json_clawpatch.call_args_list],
            [["clawpatch", "status", "--json"]],
        )
        self.assertIsNone(_load_release_progress(repo))

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_relaunch_reenters_same_finding_after_empty_planned_attempt(
        self,
        _version,
        _processes,
        show_finding,
        resume_stopped,
        json_clawpatch,
        review_all,
        next_finding,
        execute_fix,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            clawpatch_state = repo / ".clawpatch"
            clawpatch_state.mkdir()
            (clawpatch_state / "project.json").write_text("{}\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=[],
            )
            planned = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [
                    {
                        "patchAttemptId": "pat_interrupted",
                        "status": "planned",
                        "findingIds": ["fnd_one"],
                        "filesChanged": [],
                        "git": {"baseSha": head},
                    }
                ],
            }
            show_finding.side_effect = [planned, planned]
            json_clawpatch.return_value = {
                "activeLocks": 0,
                "lockFiles": 0,
                "openFindings": 1,
            }
            queue = {
                "finding": {"id": "fnd_one", "status": "open"},
                "next": "clawpatch show --finding fnd_one",
            }
            next_finding.side_effect = [("fnd_one", queue), (None, {"finding": None})]
            def complete_fix(*_args, **_kwargs):
                (repo / "fixed.py").write_text("fixed\n", encoding="utf-8")
                return (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": ["fixed.py"],
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                        "commit": "",
                    },
                    False,
                )

            execute_fix.side_effect = complete_fix
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")

        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(execute_fix.call_count, 1)
        self.assertEqual(next_finding.call_count, 2)
        resume_stopped.assert_not_called()
        review_all.assert_not_called()
        self.assertIsNone(_load_release_progress(repo))

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_relaunch_consumes_exact_fixed_zero_source_checkpoint_and_advances_queue(
        self,
        _version,
        _processes,
        show_finding,
        resume_stopped,
        json_clawpatch,
        review_all,
        next_finding,
        execute_fix,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            clawpatch_state = repo / ".clawpatch"
            clawpatch_state.mkdir()
            (clawpatch_state / "project.json").write_text("{}\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_overlap",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=[],
            )
            show_finding.return_value = {
                "finding": {"id": "fnd_overlap", "status": "fixed"},
                "validation": [],
                "patchAttempts": [
                    {
                        "patchAttemptId": "pat_already_fixed",
                        "status": "applied",
                        "findingIds": ["fnd_overlap"],
                        "filesChanged": [],
                        "git": {"baseSha": head},
                    }
                ],
            }
            json_clawpatch.return_value = {
                "activeLocks": 0,
                "lockFiles": 0,
                "openFindings": 0,
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")
            final_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            status = subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo, text=True
            )

        self.assertEqual(final_head, head)
        self.assertEqual(status, "")
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(report["results"][0]["finding_id"], "fnd_overlap")
        self.assertEqual(report["results"][0]["patch_attempt"], "pat_already_fixed")
        self.assertEqual(report["results"][0]["files_changed"], [])
        self.assertEqual(report["results"][0]["commit"], "")
        self.assertEqual(report["results"][0]["revalidation"]["outcome"], "fixed")
        self.assertEqual(next_finding.call_count, 1)
        execute_fix.assert_not_called()
        resume_stopped.assert_not_called()
        review_all.assert_not_called()
        self.assertIsNone(_load_release_progress(repo))

    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_empty_checkpoint_without_matching_planned_attempt_stays_stopped(
        self,
        _version,
        _processes,
        show_finding,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "project.json").write_text("{}\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=[],
            )
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [
                    {
                        "patchAttemptId": "pat_other_head",
                        "status": "planned",
                        "findingIds": ["fnd_one"],
                        "filesChanged": [],
                        "git": {"baseSha": "not-current-head"},
                    }
                ],
            }

            with self.assertRaisesRegex(SafetyError, "no matching planned attempt"):
                release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["head_before"], head)

    @patch("manageroo.clawpatch_release._show_finding")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_fixed_zero_source_checkpoint_without_applied_attempt_stays_stopped(
        self,
        _version,
        _processes,
        show_finding,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            (repo / ".clawpatch").mkdir()
            (repo / ".clawpatch" / "project.json").write_text("{}\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=[],
            )
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "fixed"},
                "validation": [],
                "patchAttempts": [],
            }

            with self.assertRaisesRegex(SafetyError, "applied zero-file patch attempt"):
                release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["head_before"], head)

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_rebuilt_clawpatch_generation_discards_only_fingerprinted_interrupted_source(
        self,
        _version,
        _processes,
        resume_stopped,
        json_clawpatch,
        review_all,
        next_finding,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            test = repo / "test_app.py"
            source.write_text("before\n", encoding="utf-8")
            test.write_text("before test\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py", "test_app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            source.write_text("interrupted repair\n", encoding="utf-8")
            test.write_text("interrupted regression test\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_old",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=["app.py", "test_app.py"],
            )
            state = repo / ".clawpatch"
            (state / "features").mkdir(parents=True)
            (state / "findings").mkdir()
            (state / "patches").mkdir()
            (state / "runs").mkdir()
            (state / "reports").mkdir()
            (state / "project.json").write_text(
                json.dumps(
                    {
                        "createdAt": "2099-01-01T00:00:00.000Z",
                        "git": {"headSha": head, "currentBranch": branch},
                    }
                ),
                encoding="utf-8",
            )
            (state / "features" / "feat_new.json").write_text("{}\n", encoding="utf-8")
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 0},
                "completion": {"wouldReview": 0},
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")
            source_text = source.read_text(encoding="utf-8")
            test_text = test.read_text(encoding="utf-8")
            checkpoint = _load_release_progress(repo)

        self.assertEqual(source_text, "before\n")
        self.assertEqual(test_text, "before test\n")
        self.assertEqual(report["reset_recovery"]["finding_id"], "fnd_old")
        self.assertIsNone(checkpoint)
        resume_stopped.assert_not_called()
        self.assertEqual(
            [invocation.args[1] for invocation in json_clawpatch.call_args_list],
            [["clawpatch", "status", "--json"], ["clawpatch", "map", "--json"]],
        )

    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_rebuilt_generation_preserves_source_when_fingerprint_changed_after_checkpoint(
        self,
        _version,
        _processes,
        resume_stopped,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
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
            source.write_text("interrupted repair\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_old",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=["app.py"],
            )
            source.write_text("operator edit after interruption\n", encoding="utf-8")
            state = repo / ".clawpatch"
            for directory in ("findings", "patches", "runs", "reports"):
                (state / directory).mkdir(parents=True, exist_ok=True)
            (state / "project.json").write_text(
                json.dumps(
                    {
                        "createdAt": "2099-01-01T00:00:00.000Z",
                        "git": {"headSha": head, "currentBranch": branch},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SafetyError, "exact source changes remain"):
                release_sweep(repo, apply=True, branch="current")
            source_text = source.read_text(encoding="utf-8")
            checkpoint = _load_release_progress(repo)

        self.assertEqual(source_text, "operator edit after interruption\n")
        self.assertIsNotNone(checkpoint)
        resume_stopped.assert_called_once()

    def test_rebuilt_generation_accepts_exact_legacy_v2_checkpoint_owned_files(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
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
            source.write_text("legacy interrupted repair\n", encoding="utf-8")
            _write_release_progress(
                repo,
                finding_id="fnd_old",
                branch=branch,
                head_before=head,
                phase="stopped",
                owned_paths=["app.py"],
            )
            progress_path = repo / ".manageroo" / "cache" / "clawpatch-release-progress.json"
            raw = json.loads(progress_path.read_text(encoding="utf-8"))
            raw["version"] = 2
            raw.pop("owned_source_fingerprint")
            progress_path.write_text(json.dumps(raw), encoding="utf-8")
            state = repo / ".clawpatch"
            for directory in ("findings", "patches", "runs", "reports"):
                (state / directory).mkdir(parents=True, exist_ok=True)
            (state / "project.json").write_text(
                json.dumps(
                    {
                        "createdAt": "2099-01-01T00:00:00.000Z",
                        "git": {"headSha": head, "currentBranch": branch},
                    }
                ),
                encoding="utf-8",
            )

            progress = _load_release_progress(repo)

            self.assertTrue(_rebuilt_generation_owns_checkpoint_source(repo, progress))

    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_rebuilt_generation_retires_empty_checkpoint_after_head_advances(
        self,
        _version,
        _processes,
        resume_stopped,
        json_clawpatch,
        review_all,
        next_finding,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            stopped_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id="fnd_deleted_generation",
                branch=branch,
                head_before=stopped_head,
                phase="stopped",
                owned_paths=[],
            )

            state = repo / ".clawpatch"
            (state / "features").mkdir(parents=True)
            (state / "findings").mkdir()
            (state / "patches").mkdir()
            (state / "runs").mkdir()
            (state / "reports").mkdir()
            (state / "project.json").write_text(
                json.dumps(
                    {
                        "createdAt": "2099-01-01T00:00:00.000Z",
                        "git": {"headSha": stopped_head, "currentBranch": branch},
                    }
                ),
                encoding="utf-8",
            )
            (state / "features" / "feat_new.json").write_text("{}\n", encoding="utf-8")
            source.write_text("first committed repair\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "add", "-f", ".clawpatch/project.json", ".clawpatch/features/feat_new.json"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "commit", "-q", "-m", "clawpatch fix"], cwd=repo, check=True)
            second = repo / "second.py"
            second.write_text("second committed repair\n", encoding="utf-8")
            (state / "findings" / "fnd_new.json").write_text("{}\n", encoding="utf-8")
            subprocess.run(["git", "add", "second.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "add", "-f", ".clawpatch/findings/fnd_new.json"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "commit", "-q", "-m", "clawpatch fix"], cwd=repo, check=True)

            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
            ]
            review_all.return_value = {
                "review": {"reviewed": 1, "findings": 0},
                "completion": {"wouldReview": 0},
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertIsNone(checkpoint)
        self.assertEqual(
            report["reset_recovery"],
            {
                "finding_id": "fnd_deleted_generation",
                "owned_paths": [],
                "generation": "rebuilt",
            },
        )
        resume_stopped.assert_not_called()
        self.assertEqual(
            [invocation.args[1] for invocation in json_clawpatch.call_args_list],
            [["clawpatch", "status", "--json"], ["clawpatch", "map", "--json"]],
        )

    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_empty_checkpoint_is_preserved_when_old_finding_still_exists(
        self,
        _version,
        _processes,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            stopped_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id="fnd_still_present",
                branch=branch,
                head_before=stopped_head,
                phase="stopped",
                owned_paths=[],
            )
            state = repo / ".clawpatch"
            (state / "findings").mkdir(parents=True)
            (state / "project.json").write_text(
                json.dumps(
                    {
                        "createdAt": "2099-01-01T00:00:00.000Z",
                        "git": {"headSha": stopped_head, "currentBranch": branch},
                    }
                ),
                encoding="utf-8",
            )
            (state / "findings" / "fnd_still_present.json").write_text(
                "{}\n", encoding="utf-8"
            )
            source.write_text("committed change\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(
                [
                    "git",
                    "add",
                    "-f",
                    ".clawpatch/project.json",
                    ".clawpatch/findings/fnd_still_present.json",
                ],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "commit", "-q", "-m", "later commit"], cwd=repo, check=True)

            with self.assertRaisesRegex(SafetyError, "no longer matches the current Git HEAD"):
                release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["finding_id"], "fnd_still_present")


    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._next_finding")
    @patch("manageroo.clawpatch_release._review_all_features")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._resume_stopped_attempt")
    @patch("manageroo.clawpatch_release._run_project_gates", return_value=[])
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_one_command_clears_completed_stale_checkpoint_from_exact_git_history(
        self,
        _version,
        _processes,
        _gates,
        resume_stopped,
        json_clawpatch,
        review_all,
        next_finding,
        final_closure,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            stopped_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=stopped_head,
                phase="stopped",
                owned_paths=["app.py"],
            )

            source.write_text("completed Clawpatch repair\n", encoding="utf-8")
            state = repo / ".clawpatch" / "project.json"
            state.parent.mkdir()
            state.write_text('{"step": 1}\n', encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "add", "-f", ".clawpatch/project.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "clawpatch fix"], cwd=repo, check=True)
            state.write_text('{"step": 2}\n', encoding="utf-8")
            subprocess.run(["git", "add", "-f", ".clawpatch/project.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "clawpatch fix"], cwd=repo, check=True)

            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 0},
            ]
            review_all.return_value = {
                "review": {"reviewed": 0, "findings": 0},
                "completion": {"dryRun": True, "wouldReview": 0},
            }
            next_finding.return_value = (None, {"finding": None})
            final_closure.return_value = {"pushed": False}

            report = release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertTrue(report["ok"])
        self.assertIsNone(checkpoint)
        resume_stopped.assert_not_called()
        self.assertEqual(
            [invocation.args[1] for invocation in json_clawpatch.call_args_list],
            [["clawpatch", "status", "--json"], ["clawpatch", "map", "--json"]],
        )

    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_one_command_preserves_checkpoint_when_commit_contains_unowned_source(
        self,
        _version,
        _processes,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            source = repo / "app.py"
            unrelated = repo / "other.py"
            source.write_text("before\n", encoding="utf-8")
            unrelated.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py", "other.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "source"], cwd=repo, check=True)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
            ).strip()
            stopped_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            _write_release_progress(
                repo,
                finding_id="fnd_one",
                branch=branch,
                head_before=stopped_head,
                phase="stopped",
                owned_paths=["app.py"],
            )
            source.write_text("repair\n", encoding="utf-8")
            unrelated.write_text("unowned change\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py", "other.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "clawpatch fix"], cwd=repo, check=True)

            with self.assertRaisesRegex(SafetyError, "no longer matches"):
                release_sweep(repo, apply=True, branch="current")
            checkpoint = _load_release_progress(repo)

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["head_before"], stopped_head)

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
                {"dryRun": True, "wouldReview": 4, "jobs": 4},
                {"reviewed": 4, "findings": 0},
                {"dryRun": True, "wouldReview": 0, "jobs": 4},
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

    @patch("manageroo.clawpatch_release._prepare_fresh_release")
    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_completed_queue_requires_a_fresh_zero_finding_review_generation(
        self,
        _version,
        _processes,
        json_clawpatch,
        execute_fix,
        final_closure,
        prepare_fresh,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            json_clawpatch.side_effect = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
                {"dryRun": True, "wouldReview": 1, "jobs": 1},
                {"reviewed": 1, "findings": 1},
                {"dryRun": True, "wouldReview": 0, "jobs": 1},
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "next": "clawpatch show --finding fnd_one",
                },
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "validation": [],
                    "patchAttempts": [],
                },
                {"finding": None, "status": "open"},
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
                {"dryRun": True, "wouldReview": 1, "jobs": 1},
                {"reviewed": 1, "findings": 0},
                {"dryRun": True, "wouldReview": 0, "jobs": 1},
                {"finding": None, "status": "open"},
            ]
            execute_fix.return_value = (
                {
                    "finding_id": "fnd_one",
                    "files_changed": [],
                    "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                    "commit": "",
                },
                False,
            )
            final_closure.side_effect = [
                {"pushed": False, "needs_fresh_review": True},
                {"pushed": False, "needs_fresh_review": False},
            ]

            report = release_sweep(repo, apply=True, branch="current")

        self.assertEqual(execute_fix.call_count, 1)
        self.assertEqual(final_closure.call_count, 2)
        prepare_fresh.assert_called_once()
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(len(report["review_generations"]), 2)
        self.assertFalse(report["review_generations"][0]["clean"])
        self.assertTrue(report["review_generations"][1]["clean"])

    @patch("manageroo.clawpatch_release._prepare_fresh_release")
    @patch("manageroo.clawpatch_release._final_closure")
    @patch("manageroo.clawpatch_release._execute_fix")
    @patch("manageroo.clawpatch_release._json_clawpatch")
    @patch("manageroo.clawpatch_release._active_clawpatch_processes", return_value=[])
    @patch("manageroo.clawpatch_release._clawpatch_version", return_value="0.7.2")
    def test_fresh_review_same_tree_repetition_stops_as_nonconvergent(
        self,
        _version,
        _processes,
        json_clawpatch,
        execute_fix,
        final_closure,
        prepare_fresh,
    ):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            self.init_repo(repo)
            first_generation = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
                {"dryRun": True, "wouldReview": 1, "jobs": 1},
                {"reviewed": 1, "findings": 1},
                {"dryRun": True, "wouldReview": 0, "jobs": 1},
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "next": "clawpatch show --finding fnd_one",
                },
                {
                    "finding": {"id": "fnd_one", "status": "open"},
                    "validation": [],
                    "patchAttempts": [],
                },
                {"finding": None, "status": "open"},
            ]
            second_generation = [
                {"activeLocks": 0, "lockFiles": 0, "openFindings": 0},
                {"features": 1},
                {"dryRun": True, "wouldReview": 1, "jobs": 1},
                {"reviewed": 1, "findings": 1},
                {"dryRun": True, "wouldReview": 0, "jobs": 1},
                {
                    "finding": {"id": "fnd_two", "status": "open"},
                    "next": "clawpatch show --finding fnd_two",
                },
                {
                    "finding": {"id": "fnd_two", "status": "open"},
                    "validation": [],
                    "patchAttempts": [],
                },
                {"finding": None, "status": "open"},
            ]
            json_clawpatch.side_effect = first_generation + second_generation
            execute_fix.side_effect = [
                (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": [],
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                        "commit": "",
                    },
                    False,
                ),
                (
                    {
                        "finding_id": "fnd_two",
                        "files_changed": [],
                        "revalidation": {"finding": "fnd_two", "outcome": "fixed"},
                        "commit": "",
                    },
                    False,
                ),
            ]
            final_closure.side_effect = [
                {"pushed": False, "needs_fresh_review": True},
                {"pushed": False, "needs_fresh_review": True},
            ]

            with self.assertRaisesRegex(SafetyError, "did not converge"):
                release_sweep(repo, apply=True, branch="current")

        self.assertEqual(execute_fix.call_count, 2)
        self.assertEqual(final_closure.call_count, 2)
        prepare_fresh.assert_called_once()

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
                {"dryRun": True, "wouldReview": 3, "jobs": 3},
                {"reviewed": 3, "findings": 1},
                {"dryRun": True, "wouldReview": 0, "jobs": 3},
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
            def complete_fix(*_args, **_kwargs):
                (repo / "fixed.py").write_text("fixed\n", encoding="utf-8")
                return (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": ["fixed.py"],
                        "revalidation": {"finding": "fnd_one", "outcome": "fixed"},
                    },
                    False,
                )

            execute_fix.side_effect = complete_fix
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
                (None, {"finding": None}),
            ]
            show_finding.return_value = {
                "finding": {"id": "fnd_one", "status": "open"},
                "validation": [],
                "patchAttempts": [],
            }
            calls = 0

            def fix_side_effect(*_args, **_kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    (repo / "partial.py").write_text("partial\n", encoding="utf-8")
                    outcome = "open"
                    paths = ["partial.py"]
                else:
                    (repo / "final.py").write_text("final\n", encoding="utf-8")
                    outcome = "fixed"
                    paths = ["final.py"]
                return (
                    {
                        "finding_id": "fnd_one",
                        "files_changed": paths,
                        "revalidation": {"finding": "fnd_one", "outcome": outcome},
                        "commit": "",
                    },
                    False,
                )

            execute_fix.side_effect = fix_side_effect
            final_closure.return_value = {"pushed": False}

            report = release_sweep(
                repo,
                apply=True,
                branch="current",
                progress=progress_events.append,
            )

        self.assertEqual(execute_fix.call_count, 2)
        self.assertEqual(next_finding.call_count, 2)
        self.assertEqual(show_finding.call_count, 1)
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(len(report["continuations"]), 1)
        self.assertTrue(report["continuations"][0]["temporary_local_commit"])
        self.assertEqual(
            [event["attempt"] for event in progress_events if event["phase"] == "fix"],
            [1, 2],
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
    def test_failed_fix_retries_only_until_no_progress_then_stops_without_queue_advance(
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

        self.assertEqual(execute_fix.call_count, 2)
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
        self.assertEqual(
            [event["attempt"] for event in progress_events if event["phase"] == "fix"],
            [1, 2],
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
