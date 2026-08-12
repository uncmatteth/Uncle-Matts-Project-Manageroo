import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.codex import CodexAdapter, _BWRAP_LOOPBACK_FAILURE
from manageroo.capability_router import route_capabilities
from manageroo.errors import AgentExecutionError
from manageroo.runner import CommandResult, _platform_argv
from tests.support import symlink_or_skip


def _result(argv, cwd, *, exit_code=0, stdout="", stderr=""):
    return CommandResult(
        argv=list(argv),
        cwd=str(cwd),
        started_at="start",
        finished_at="finish",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


class _Runner:
    def __init__(self, results, output_path: Path | None = None):
        self.results = list(results)
        self.calls = []
        self.profile_snapshots = []
        self.output_path = output_path

    def run(self, argv, *, cwd, **kwargs):
        self.calls.append(list(argv))
        if "--profile" in argv:
            profile_name = argv[argv.index("--profile") + 1]
            codex_home = Path(os.environ["CODEX_HOME"])
            profile_path = codex_home / f"{profile_name}.config.toml"
            self.profile_snapshots.append(profile_path.read_text(encoding="utf-8"))
        result = self.results.pop(0)
        if result.exit_code == 0 and self.output_path is not None:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text('{"ok": true}', encoding="utf-8")
        return result


def _request(root: Path) -> AgentRequest:
    prompt = root / "prompt.md"
    schema = root / "schema.json"
    output = root / "output.json"
    prompt.write_text("Do bounded work.", encoding="utf-8")
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    return AgentRequest(
        role="implementer",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=root,
        sandbox="workspace-write",
        timeout_seconds=30,
    )


def _run_prompt_input_or_skip(
    test_case: unittest.TestCase,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        _platform_argv(argv, env),
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        test_case.skipTest(
            "installed Codex CLI does not expose the debug prompt-input test surface"
        )
    return result


class CodexSandboxFallbackTests(unittest.TestCase):
    def test_caller_cannot_request_unprotected_codex_sandbox(self):
        for sandbox in ("danger-full-access", "unknown-mode"):
            with self.subTest(sandbox=sandbox), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                request = _request(root)
                request.sandbox = sandbox
                request.output_path = root / "output" / "result.json"
                runner = _Runner([])

                with self.assertRaisesRegex(AgentExecutionError, "protected sandbox mode"):
                    CodexAdapter("codex", runner).run(request)

                self.assertEqual(runner.calls, [])
                self.assertFalse(request.output_path.parent.exists())

    def test_doctor_preflights_the_native_codex_sandbox_on_every_supported_platform(self):
        help_output = " ".join(CodexAdapter.REQUIRED_FLAGS)
        for system_name, native_sandbox in (
            ("Linux", "linux"),
            ("Darwin", "macos"),
            ("Windows", "windows"),
        ):
            with self.subTest(system_name=system_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                runner = _Runner(
                    [
                        _result(["codex", "--version"], root, stdout="codex-cli 1.0"),
                        _result(["codex", "exec", "--help"], root, stdout=help_output),
                        _result(["codex", "sandbox"], root),
                    ]
                )

                with patch(
                    "manageroo.adapters.codex.shutil.which", return_value="/tools/codex"
                ), patch(
                    "manageroo.adapters.codex.platform.system", return_value=system_name
                ):
                    doctor = CodexAdapter("codex", runner).doctor(root)

                self.assertTrue(doctor["ok"], doctor)
                self.assertTrue(doctor["sandbox_preflight"]["ok"])
                self.assertEqual(doctor["sandbox_preflight"]["helper"], native_sandbox)
                self.assertEqual(runner.calls[2][0:2], ["codex", "sandbox"])
                self.assertIn(":workspace", runner.calls[2])
                self.assertIn(str(root), runner.calls[2])
                self.assertIn("--", runner.calls[2])

    def test_doctor_fails_closed_with_platform_specific_sandbox_setup(self):
        help_output = " ".join(CodexAdapter.REQUIRED_FLAGS)
        for system_name, expected_text in (
            ("Linux", "bubblewrap"),
            ("Darwin", "Seatbelt"),
            ("Windows", "PowerShell"),
        ):
            with self.subTest(system_name=system_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                runner = _Runner(
                    [
                        _result(["codex", "--version"], root, stdout="codex-cli 1.0"),
                        _result(["codex", "exec", "--help"], root, stdout=help_output),
                        _result(
                            ["codex", "sandbox"],
                            root,
                            exit_code=1,
                            stderr="sandbox bootstrap failed",
                        ),
                    ]
                )

                with patch(
                    "manageroo.adapters.codex.shutil.which", return_value="/tools/codex"
                ), patch(
                    "manageroo.adapters.codex.platform.system", return_value=system_name
                ), patch(
                    "manageroo.adapters.codex.platform.freedesktop_os_release",
                    return_value={"ID": "ubuntu", "VERSION_ID": "24.04"},
                ):
                    doctor = CodexAdapter("codex", runner).doctor(root)

                self.assertFalse(doctor["ok"])
                preflight = doctor["sandbox_preflight"]
                self.assertIn(expected_text, preflight["guidance"])
                self.assertTrue(preflight["next_commands"])
                self.assertIn("chatgpt.com", preflight["reference"])
                commands = "\n".join(preflight["next_commands"])
                if system_name == "Linux":
                    self.assertIn("apparmor_parser", commands)
                else:
                    self.assertNotIn("apt install", commands)

    def test_windows_sandbox_rerun_command_quotes_python_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = _Runner(
                [
                    _result(["codex", "sandbox"], root, exit_code=1, stderr="failed"),
                ]
            )
            with patch(
                "manageroo.adapters.codex.sys.executable",
                r"C:\Program Files\Python\python.exe",
            ):
                from manageroo.adapters.codex import codex_sandbox_preflight

                report = codex_sandbox_preflight(
                    "codex", runner, root, system_name="Windows"
                )

            self.assertIn(
                '"C:\\Program Files\\Python\\python.exe"',
                report["next_commands"][0],
            )

    def test_task_capsule_uses_bounded_ephemeral_profile_without_leaking_skill_paths_to_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            request = _request(root)
            request.metadata["capability_route"] = {
                "catalog_paths": [
                    str(root / "skills" / "pdf" / "SKILL.md"),
                    str(root / "skills" / "diagnose" / "SKILL.md"),
                ]
            }
            runner = _Runner([_result(["codex", "exec"], root)], output_path=request.output_path)

            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                response = CodexAdapter("codex", runner).run(request)

            self.assertTrue(response.data["ok"])
            argv = runner.calls[0]
            self.assertIn("--profile", argv)
            self.assertNotIn("--config", argv)
            self.assertLess(sum(len(part) for part in argv), 1000)
            self.assertNotIn(str(root / "skills"), " ".join(argv))
            profile = runner.profile_snapshots[0]
            self.assertEqual(profile.count("enabled = false"), 4)
            self.assertIn('name = "diagnose"', profile)
            profile_data = tomllib.loads(profile)
            disabled_paths = {
                item.get("path")
                for item in profile_data["skills"]["config"]
                if "path" in item
            }
            self.assertIn(str(root / "skills" / "diagnose" / "SKILL.md"), disabled_paths)
            self.assertEqual(list(codex_home.glob("manageroo-*.config.toml")), [])

    def test_profile_name_collision_never_deletes_preexisting_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            request = _request(root)
            request.metadata["capability_catalog_paths"] = [str(root / "skills" / "one" / "SKILL.md")]
            existing = codex_home / ("manageroo-" + "a" * 24 + ".config.toml")
            existing.write_text("KEEP ME\n", encoding="utf-8")

            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False), patch(
                "manageroo.adapters.codex.secrets.token_hex", return_value="a" * 24
            ):
                with self.assertRaises(AgentExecutionError):
                    with CodexAdapter("codex", _Runner([]))._ephemeral_skill_profile(request):
                        pass

            self.assertEqual(existing.read_text(encoding="utf-8"), "KEEP ME\n")

    def test_failed_profile_preparation_does_not_consume_worker_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            request = _request(root)
            request.metadata["capability_catalog"] = [
                {"name": f"skill-{index}", "path": f"/skills/{index}/SKILL.md"}
                for index in range(600)
            ]
            budgeted = BudgetedAdapter(
                CodexAdapter("codex", _Runner([])),
                max_total_worker_calls=1,
            )

            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                with self.assertRaisesRegex(AgentExecutionError, "skill identities"):
                    budgeted.run(request)

            self.assertEqual(budgeted.calls, 0)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_real_codex_profile_removes_controlled_skill_from_model_visible_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            skill = codex_home / "skills" / "manageroo-isolation-sentinel" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: manageroo-isolation-sentinel\n"
                "description: Manageroo isolation sentinel.\n---\n",
                encoding="utf-8",
            )
            request = _request(root)
            request.metadata["capability_catalog_paths"] = [str(skill)]
            env = {**os.environ, "CODEX_HOME": str(codex_home)}
            adapter = CodexAdapter("codex", _Runner([]))

            baseline = _run_prompt_input_or_skip(
                self,
                ["codex", "debug", "prompt-input", "probe"],
                cwd=root,
                env=env,
            )
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                with adapter._ephemeral_skill_profile(request) as profile:
                    isolated = subprocess.run(
                        _platform_argv(
                            ["codex", "--profile", profile, "debug", "prompt-input", "probe"],
                            env,
                        ),
                        cwd=root,
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=30,
                        check=True,
                    )

            self.assertIn("manageroo-isolation-sentinel", baseline.stdout)
            self.assertNotIn("manageroo-isolation-sentinel", isolated.stdout)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_real_codex_profile_disables_repository_skill_by_name_when_path_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            mirror = root / "isolated-mirror"
            skill = mirror / ".agents" / "skills" / "mirror-sentinel" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: mirror-sentinel\ndescription: Mirror sentinel.\n---\n",
                encoding="utf-8",
            )
            request = _request(root)
            request.metadata["capability_catalog"] = [
                {"name": "mirror-sentinel", "path": str(root / "source-repo" / ".agents" / "skills" / "mirror-sentinel" / "SKILL.md")}
            ]
            env = {**os.environ, "CODEX_HOME": str(codex_home)}
            adapter = CodexAdapter("codex", _Runner([]))

            baseline = _run_prompt_input_or_skip(
                self,
                ["codex", "-C", str(mirror), "debug", "prompt-input", "probe"],
                cwd=mirror,
                env=env,
            )
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                with adapter._ephemeral_skill_profile(request) as profile:
                    isolated = subprocess.run(
                        _platform_argv(
                            [
                                "codex",
                                "--profile",
                                profile,
                                "-C",
                                str(mirror),
                                "debug",
                                "prompt-input",
                                "probe",
                            ],
                            env,
                        ),
                        cwd=mirror,
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=30,
                        check=True,
                    )

            self.assertIn("mirror-sentinel", baseline.stdout)
            self.assertNotIn("mirror-sentinel", isolated.stdout)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_real_codex_profile_covers_symlinked_skill_directory_and_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            skills = codex_home / "skills"
            targets = root / "targets"
            directory_target = targets / "symlink-directory-sentinel" / "SKILL.md"
            entrypoint_target = targets / "entrypoint-target" / "SKILL.md"
            directory_target.parent.mkdir(parents=True)
            entrypoint_target.parent.mkdir(parents=True)
            directory_target.write_text(
                "---\nname: symlink-directory-sentinel\ndescription: Sentinel.\n---\n",
                encoding="utf-8",
            )
            entrypoint_target.write_text(
                "---\nname: symlink-entrypoint-sentinel\ndescription: Sentinel.\n---\n",
                encoding="utf-8",
            )
            skills.mkdir(parents=True)
            symlink_or_skip(
                self,
                directory_target.parent,
                skills / "symlink-directory-sentinel",
                target_is_directory=True,
            )
            entrypoint_dir = skills / "symlink-entrypoint-sentinel"
            entrypoint_dir.mkdir()
            symlink_or_skip(self, entrypoint_target, entrypoint_dir / "SKILL.md")
            request = _request(root)
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                route = route_capabilities("Do ordinary local work.", roots=[skills])
            request.metadata["capability_catalog"] = route["catalog_entries"]
            env = {**os.environ, "CODEX_HOME": str(codex_home)}
            adapter = CodexAdapter("codex", _Runner([]))

            baseline = _run_prompt_input_or_skip(
                self,
                ["codex", "debug", "prompt-input", "probe"],
                cwd=root,
                env=env,
            )
            with patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}, clear=False):
                with adapter._ephemeral_skill_profile(request) as profile:
                    isolated = subprocess.run(
                        _platform_argv(
                            ["codex", "--profile", profile, "debug", "prompt-input", "probe"],
                            env,
                        ),
                        cwd=root,
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=30,
                        check=True,
                    )

            for sentinel in ("symlink-directory-sentinel", "symlink-entrypoint-sentinel"):
                if sentinel in baseline.stdout:
                    self.assertNotIn(sentinel, isolated.stdout)
            self.assertIn("symlink-directory-sentinel", {item["name"] for item in route["catalog_entries"]})
            self.assertIn("symlink-entrypoint-sentinel", {item["name"] for item in route["catalog_entries"]})

    def test_successful_worker_cannot_spoof_diagnostic_to_trigger_unrestricted_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            initial_argv = ["codex", "exec"]
            runner = _Runner(
                [_result(initial_argv, root, stdout=_BWRAP_LOOPBACK_FAILURE)],
                output_path=request.output_path,
            )
            with patch.dict(
                "os.environ",
                {"MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK": "1"},
                clear=False,
            ):
                response = CodexAdapter("codex", runner).run(request)
            self.assertTrue(response.data["ok"])
            self.assertEqual(len(runner.calls), 1)
            self.assertNotIn("danger-full-access", runner.calls[0])

    def test_capability_guard_runs_before_each_concrete_codex_fallback_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            request = _request(root)
            calls = 0

            def before_launch(candidate: AgentRequest, is_codex: bool) -> AgentRequest:
                nonlocal calls
                calls += 1
                self.assertTrue(is_codex)
                if calls == 2:
                    raise AgentExecutionError("capability changed between provider launches")
                return candidate

            request.before_launch = before_launch
            runner = _Runner(
                [
                    _result(
                        ["codex", "exec"],
                        root,
                        exit_code=1,
                        stderr=_BWRAP_LOOPBACK_FAILURE,
                    ),
                    _result(["codex", "exec"], root),
                ],
                output_path=request.output_path,
            )
            with patch.dict(
                "os.environ",
                {
                    "CODEX_HOME": str(codex_home),
                    "MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK": "1",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    AgentExecutionError,
                    "capability changed between provider launches",
                ):
                    CodexAdapter("codex", runner).run(request)

            self.assertEqual(calls, 2)
            self.assertEqual(len(runner.calls), 1)

    def test_genuine_host_sandbox_failure_cannot_escalate_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner(
                [_result(["codex", "exec"], root, exit_code=1, stderr=_BWRAP_LOOPBACK_FAILURE)]
            )
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(AgentExecutionError, "refused to escalate automatically"):
                    CodexAdapter("codex", runner).run(request)
            self.assertEqual(len(runner.calls), 1)
            self.assertNotIn("danger-full-access", runner.calls[0])

    def test_explicit_opt_in_allows_retry_only_after_failed_host_sandbox_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner(
                [
                    _result(["codex", "exec"], root, exit_code=1, stderr=_BWRAP_LOOPBACK_FAILURE),
                    _result(["codex", "exec"], root, exit_code=0),
                ],
                output_path=request.output_path,
            )
            with patch.dict(
                "os.environ",
                {"MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK": "1"},
                clear=True,
            ):
                response = CodexAdapter("codex", runner).run(request)
            self.assertTrue(response.data["ok"])
            self.assertEqual(len(runner.calls), 2)
            self.assertNotIn("danger-full-access", runner.calls[0])
            self.assertIn("danger-full-access", runner.calls[1])


if __name__ == "__main__":
    unittest.main()
