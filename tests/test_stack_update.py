import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import symlink_or_skip

from manageroo.stack_update import (
    AUTOREVIEW_COMMIT,
    CLAWPATCH_PACKAGE,
    CLAWPATCH_SUPERVISOR_COMMIT,
    CLAWPATCH_SUPERVISOR_SOURCE,
    GITNEXUS_PACKAGE,
    MANAGEROO_SKILLS_REFERENCE,
    _run,
    _replace_autoreview,
    _update_autoreview,
    apply_stack_updates,
    format_stack_update,
    stack_update_plan,
)
from manageroo.trufflehog import TRUFFLEHOG_VERSION


def _hold_autoreview_lock_before_owner_publication(
    destination,
    publication_paused,
    publish_owner,
    owner_entered,
    release_owner,
) -> None:
    import manageroo.stack_update_policy as policy

    original_write = policy.os.write

    def delayed_write(descriptor, data):
        publication_paused.set()
        if not publish_owner.wait(timeout=5):
            raise TimeoutError("test did not release owner publication")
        return original_write(descriptor, data)

    policy.os.write = delayed_write
    with policy._destination_lock(Path(destination)):
        owner_entered.set()
        if not release_owner.wait(timeout=5):
            raise TimeoutError("test did not release lock owner")


def _enter_autoreview_lock(destination, lock_opened, entered) -> None:
    import manageroo.stack_update_policy as policy

    original_open = policy.os.open

    def observed_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        lock_opened.set()
        return descriptor

    policy.os.open = observed_open
    with policy._destination_lock(Path(destination)):
        entered.set()


def _load_supervisor_runtime_gate():
    import importlib.util

    from manageroo.assets import asset_path

    gate_path = asset_path("supervisor_gate/manageroo_supervisor_gate.py")
    spec = importlib.util.spec_from_file_location("test_supervisor_runtime_gate", gate_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load supervisor runtime gate")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def _run_standalone_gate_until_released(executable, active, release) -> None:
    gate = _load_supervisor_runtime_gate()

    def run_supervisor():
        active.set()
        if not release.wait(timeout=5):
            return 2
        return 0

    gate._run_supervisor = run_supervisor
    original_argv = sys.argv
    try:
        sys.argv = [executable, "--repo", "."]
        gate.main()
    finally:
        sys.argv = original_argv


def _attempt_standalone_gate(executable, entered, result_queue) -> None:
    from contextlib import redirect_stderr
    from io import StringIO

    gate = _load_supervisor_runtime_gate()

    def run_supervisor():
        entered.set()
        return 0

    gate._run_supervisor = run_supervisor
    original_argv = sys.argv
    try:
        sys.argv = [executable, "--repo", "."]
        with redirect_stderr(StringIO()):
            result_queue.put(gate.main())
    finally:
        sys.argv = original_argv


class StackUpdateTests(unittest.TestCase):
    def test_manageroo_skill_reference_uses_the_public_repository_owner(self):
        self.assertEqual(
            MANAGEROO_SKILLS_REFERENCE,
            "https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo/"
            "tree/main/src/manageroo/assets/skills",
        )

    def test_plan_updates_only_a_proven_native_supervisor_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            scripts = home / ".local" / "share" / "clawpatch-supervise" / "venv" / "bin"
            scripts.mkdir(parents=True)
            executable = scripts / "clawpatch-supervise"
            python = scripts / "python"
            executable.write_text("", encoding="utf-8")
            python.write_text("", encoding="utf-8")
            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: str(executable) if name == "clawpatch-supervise" else None,
            ):
                plan = stack_update_plan(["clawpatch-supervise"])

        tool = plan["tools"][0]
        self.assertEqual(tool["pinned_commit"], CLAWPATCH_SUPERVISOR_COMMIT)
        self.assertEqual(Path(tool["commands"][0][-1]).name, "supervisor_gate")
        self.assertEqual(tool["commands"][1][-1], CLAWPATCH_SUPERVISOR_SOURCE)
        self.assertEqual(tool["commands"][2], [str(executable.resolve()), "--version"])

    def test_plan_rejects_native_supervisor_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            scripts = home / ".local" / "share" / "clawpatch-supervise" / "venv" / "bin"
            scripts.mkdir(parents=True)
            external_scripts = home / "unrelated-venv" / "bin"
            external_scripts.mkdir(parents=True)
            external_executable = external_scripts / "clawpatch-supervise"
            external_python = external_scripts / "python"
            external_executable.write_text("", encoding="utf-8")
            external_python.write_text("", encoding="utf-8")
            executable = scripts / "clawpatch-supervise"
            symlink_or_skip(self, external_executable, executable)
            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: str(executable) if name == "clawpatch-supervise" else None,
            ):
                plan = stack_update_plan(["clawpatch-supervise"])

        tool = plan["tools"][0]
        self.assertEqual(tool["commands"], [])
        self.assertIn("ownership", tool["note"])

    def test_plan_does_not_update_an_unowned_supervisor_path(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "unowned" / "clawpatch-supervise"
            executable.parent.mkdir()
            executable.write_text("", encoding="utf-8")
            with patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: str(executable) if name == "clawpatch-supervise" else None,
            ):
                plan = stack_update_plan(["clawpatch-supervise"])

        self.assertEqual(plan["tools"][0]["commands"], [])
        self.assertIn("not in a Manageroo native-installer location", plan["tools"][0]["note"])

    def test_apply_refuses_to_update_a_running_supervisor(self):
        planned = {
            "ok": True,
            "executes_changes": False,
            "selected_tools": ["clawpatch-supervise"],
            "tools": [
                {
                    "name": "clawpatch-supervise",
                    "commands": [
                        ["python", "-m", "pip", "install", "gate"],
                        ["python", "-m", "pip", "install", "pinned"],
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "clawpatch-supervise"
            executable.write_text("", encoding="utf-8")
            with patch(
                "manageroo.stack_update.stack_update_plan", return_value=planned
            ), patch(
                "manageroo.stack_update.shutil.which",
                return_value=str(executable),
            ), patch(
                "manageroo.stack_update._supervisor_update_blocker",
                return_value="supervisor process 42 is still running",
            ), patch(
                "manageroo.stack_update.supervisor_runtime_gate_ready",
                side_effect=[False, True],
            ), patch(
                "manageroo.stack_update._run",
                return_value={"ok": True, "exit_code": 0, "output": ""},
            ) as run:
                result = apply_stack_updates(["clawpatch-supervise"])

        self.assertFalse(result["ok"])
        self.assertIn("still running", result["results"][0]["error"])
        run.assert_called_once_with(planned["tools"][0]["commands"][0])

    def test_apply_refuses_when_supervisor_runtime_lock_is_held(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "venv" / "bin" / "clawpatch-supervise"
            executable.parent.mkdir(parents=True)
            executable.write_text("", encoding="utf-8")
            active = multiprocessing.Event()
            release = multiprocessing.Event()
            process = multiprocessing.Process(
                target=_run_standalone_gate_until_released,
                args=(str(executable), active, release),
            )
            process.start()
            self.assertTrue(active.wait(timeout=5))
            planned = {
                "ok": True,
                "executes_changes": False,
                "selected_tools": ["clawpatch-supervise"],
                "tools": [
                    {
                        "name": "clawpatch-supervise",
                        "commands": [["python", "-m", "pip", "install", "pinned"]],
                    }
                ],
            }
            try:
                with patch(
                    "manageroo.stack_update.stack_update_plan", return_value=planned
                ), patch(
                    "manageroo.stack_update.shutil.which", return_value=str(executable)
                ), patch(
                    "manageroo.stack_update._supervisor_update_blocker", return_value=None
                ), patch("manageroo.stack_update._run") as run:
                    result = apply_stack_updates(["clawpatch-supervise"])
            finally:
                release.set()
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)

        self.assertFalse(result["ok"])
        self.assertIn("lock", result["results"][0]["error"])
        run.assert_not_called()

    def test_unverified_gate_migration_rechecks_legacy_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "clawpatch-supervise"
            executable.write_text("", encoding="utf-8")
            planned = {
                "ok": True,
                "executes_changes": False,
                "selected_tools": ["clawpatch-supervise"],
                "tools": [
                    {
                        "name": "clawpatch-supervise",
                        "commands": [
                            ["python", "-m", "pip", "install", "gate"],
                            ["python", "-m", "pip", "install", "pinned"],
                        ],
                    }
                ],
            }
            with patch(
                "manageroo.stack_update.stack_update_plan", return_value=planned
            ), patch(
                "manageroo.stack_update.shutil.which", return_value=str(executable)
            ), patch(
                "manageroo.stack_update.supervisor_runtime_gate_ready",
                return_value=True,
            ), patch(
                "manageroo.stack_update._supervisor_update_blocker",
                return_value="legacy supervisor process 42 is still running",
            ) as blocker, patch("manageroo.stack_update._run") as run:
                result = apply_stack_updates(["clawpatch-supervise"])

        self.assertFalse(result["ok"])
        self.assertIn("still running", result["results"][0]["error"])
        blocker.assert_called_once_with(str(executable))
        run.assert_not_called()

    def test_windows_owned_supervisor_updates_without_ps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_app_data = root / "LocalAppData"
            scripts = (
                local_app_data
                / "ManagerooClawPatchSupervisor"
                / "venv-f59afab"
                / "Scripts"
            )
            scripts.mkdir(parents=True)
            executable = scripts / "clawpatch-supervise.exe"
            python = scripts / "python.exe"
            executable.write_text("", encoding="utf-8")
            python.write_text("", encoding="utf-8")

            def which(name: str):
                return {
                    "clawpatch-supervise": str(executable),
                    "powershell": "C:/Windows/System32/WindowsPowerShell/powershell.exe",
                }.get(name)

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}), patch(
                "manageroo.stack_update.Path.home", return_value=root
            ), patch(
                "manageroo.stack_update.platform.system", return_value="Windows"
            ), patch(
                "manageroo.stack_update.shutil.which", side_effect=which
            ), patch(
                "manageroo.stack_update.supervisor_runtime_gate_ready",
                side_effect=[False, True],
            ), patch(
                "manageroo.stack_update.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "[]", ""),
            ), patch(
                "manageroo.stack_update._run",
                return_value={"ok": True, "exit_code": 0, "output": ""},
            ) as run:
                result = apply_stack_updates(["clawpatch-supervise"])

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 3)

    def test_direct_supervisor_cannot_start_between_snapshot_and_update(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "clawpatch-supervise"
            executable.write_text("", encoding="utf-8")
            planned = {
                "ok": True,
                "executes_changes": False,
                "selected_tools": ["clawpatch-supervise"],
                "tools": [
                    {
                        "name": "clawpatch-supervise",
                        "commands": [
                            ["python", "-m", "pip", "install", "gate"],
                            ["python", "-m", "pip", "install", "pinned"],
                            [str(executable), "--version"],
                        ],
                    }
                ],
            }
            entered = multiprocessing.Event()
            result_queue = multiprocessing.Queue()

            def blocker(_executable):
                process = multiprocessing.Process(
                    target=_attempt_standalone_gate,
                    args=(str(executable), entered, result_queue),
                )
                process.start()
                process.join(timeout=5)
                self.assertFalse(process.is_alive())
                self.assertEqual(result_queue.get(timeout=1), 75)
                self.assertFalse(entered.is_set())
                return None

            with patch(
                "manageroo.stack_update.stack_update_plan", return_value=planned
            ), patch(
                "manageroo.stack_update.shutil.which", return_value=str(executable)
            ), patch(
                "manageroo.stack_update.supervisor_runtime_gate_ready",
                side_effect=[False, True],
            ), patch(
                "manageroo.stack_update._supervisor_update_blocker",
                side_effect=blocker,
            ), patch(
                "manageroo.stack_update._run",
                return_value={"ok": True, "exit_code": 0, "output": ""},
            ) as run:
                result = apply_stack_updates(["clawpatch-supervise"])

        self.assertTrue(result["ok"])
        self.assertEqual(run.call_count, 3)

    @staticmethod
    def owned_run(argv, **_kwargs):
        if argv[1:] == ["prefix", "-g"]:
            return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr\n"}
        if argv[1:] == ["bin", "-g"]:
            return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr/bin\n"}
        return {"ok": False, "exit_code": 1, "argv": argv, "output": "not installed"}

    @staticmethod
    def _fake_autoreview_git_run(argv, **kwargs):
        if argv[1:3] == ["clone", "--no-checkout"]:
            checkout = Path(argv[-1])
            checkout.mkdir(parents=True)
            return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
        if "checkout" in argv:
            skill = Path(kwargs["cwd"]) / "skills" / "autoreview"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
            return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
        if "rev-parse" in argv:
            return {
                "ok": True,
                "exit_code": 0,
                "argv": argv,
                "output": AUTOREVIEW_COMMIT + "\n",
            }
        return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

    def test_plan_is_dry_run_and_uses_release_pinned_update_paths(self):
        def which(name: str):
            return {
                "gbrain": "/usr/bin/gbrain",
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "obsidian": "/usr/bin/obsidian",
                "trufflehog": "/usr/bin/trufflehog",
            }.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update.platform.system", return_value="Linux"
        ), patch("manageroo.stack_update._run", side_effect=self.owned_run), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan()

        self.assertTrue(plan["ok"])
        self.assertFalse(plan["executes_changes"])
        tools = {item["name"]: item for item in plan["tools"]}
        self.assertNotIn(["/usr/bin/gbrain", "upgrade"], tools["gbrain"]["commands"])
        self.assertEqual(tools["gbrain"]["commands"], [["/usr/bin/gbrain", "doctor", "--json"]])
        self.assertIn(["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE], tools["gitnexus"]["commands"])
        self.assertIn(["/usr/bin/pnpm", "add", "-g", CLAWPATCH_PACKAGE], tools["clawpatch"]["commands"])
        self.assertNotIn("@latest", repr(plan))
        self.assertEqual(tools["trufflehog"]["pinned_version"], TRUFFLEHOG_VERSION)
        self.assertEqual(
            tools["skills"]["bundled_skill_count"],
            len(tools["skills"]["bundled_skills"]),
        )

    def test_apply_skills_uses_transactional_owned_skill_reconciliation(self):
        resolved = {"tdd": "/tmp/skills/tdd/SKILL.md"}
        with patch(
            "manageroo.stack_update.install_core_helper_skills",
            return_value=resolved,
        ) as install:
            result = apply_stack_updates(["skills"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_tools"], ["skills"])
        self.assertEqual(result["results"][0]["resolved_skills"], resolved)
        install.assert_called_once_with()

    def test_run_separates_success_stderr_from_stdout(self):
        result = _run(
            [
                sys.executable,
                "-c",
                "import sys; print('/valid/prefix'); print('warning', file=sys.stderr)",
            ]
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"].strip(), "/valid/prefix")
        self.assertEqual(result["output"], result["stdout"])
        self.assertEqual(result["stderr"].strip(), "warning")

    def test_plan_parses_package_manager_stdout_when_stderr_warns(self):
        with tempfile.TemporaryDirectory() as temp:
            actual = Path(temp) / "actual"
            alias = Path(temp) / "alias"
            actual.mkdir()
            symlink_or_skip(self, actual, alias, target_is_directory=True)
            prefix = alias / "npm-prefix"
            npm_bin = prefix / "bin"
            package_root = prefix / "lib" / "node_modules"
            package = package_root / "gitnexus"
            npm_bin.mkdir(parents=True)
            (package / "dist").mkdir(parents=True)
            (package / "dist" / "cli.js").write_text("", encoding="utf-8")
            (package / "package.json").write_text(
                '{"name":"gitnexus","bin":{"gitnexus":"dist/cli.js"}}',
                encoding="utf-8",
            )
            gitnexus = npm_bin / "gitnexus.cmd"
            gitnexus.write_text(
                '@ECHO off\n"%~dp0\\..\\lib\\node_modules\\gitnexus\\dist\\cli.js" %*\n',
                encoding="utf-8",
            )

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "gitnexus": str(gitnexus),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[1:] == ["prefix", "-g"]:
                    stdout = str(prefix) + "\n"
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "argv": argv,
                        "output": stdout + "warning: migrated config\n",
                        "stdout": stdout,
                        "stderr": "warning: migrated config\n",
                    }
                if argv[1:] == ["root", "-g"]:
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "argv": argv,
                        "output": str(package_root) + "\n",
                    }
                if argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                return {"ok": False, "exit_code": 1, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]],
        )

    def test_plan_rejects_unrelated_regular_executable_in_npm_bin(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "npm-prefix"
            npm_bin = prefix / "bin"
            package_root = prefix / "lib" / "node_modules"
            package = package_root / "gitnexus"
            npm_bin.mkdir(parents=True)
            (package / "dist").mkdir(parents=True)
            (package / "dist" / "cli.js").write_text("", encoding="utf-8")
            (package / "package.json").write_text(
                '{"name":"gitnexus","bin":{"gitnexus":"dist/cli.js"}}',
                encoding="utf-8",
            )
            gitnexus = npm_bin / "gitnexus"
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "gitnexus": str(gitnexus),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[1:] == ["prefix", "-g"]:
                    return {"ok": True, "argv": argv, "output": str(prefix) + "\n"}
                if argv[1:] == ["root", "-g"]:
                    return {"ok": True, "argv": argv, "output": str(package_root) + "\n"}
                if argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "argv": argv, "output": "gitnexus@1.6.9\n"}
                return {"ok": False, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus"])

        self.assertEqual(plan["tools"][0]["commands"], [])
        self.assertIn("ownership", plan["tools"][0]["note"])

    def test_homebrew_owned_obsidian_update_survives_policy_hardening(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {"brew": "/usr/local/bin/brew", "obsidian": str(obsidian)}.get(name)

            def run(argv, **_kwargs):
                owned = argv == ["/usr/local/bin/brew", "list", "--cask", "obsidian"]
                return {"ok": owned, "exit_code": 0 if owned else 1, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Darwin"
            ), patch("manageroo.stack_update._run", side_effect=run):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/local/bin/brew", "upgrade", "--cask", "obsidian"]],
        )

    def test_flatpak_owned_obsidian_update_survives_policy_hardening(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {"flatpak": "/usr/bin/flatpak", "obsidian": str(obsidian)}.get(name)

            def run(argv, **_kwargs):
                owned = argv == [
                    "/usr/bin/flatpak",
                    "info",
                    "--user",
                    "md.obsidian.Obsidian",
                ]
                return {"ok": owned, "exit_code": 0 if owned else 1, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Linux"
            ), patch("manageroo.stack_update._run", side_effect=run):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/bin/flatpak", "update", "--user", "-y", "md.obsidian.Obsidian"]],
        )

    def test_winget_owned_obsidian_update_survives_policy_hardening(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian.exe"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {
                    "winget": "C:/Windows/winget.exe",
                    "obsidian": str(obsidian),
                }.get(name)

            probe = [
                "C:/Windows/winget.exe",
                "list",
                "--id",
                "Obsidian.Obsidian",
                "-e",
                "--source",
                "winget",
            ]

            def run(argv, **_kwargs):
                owned = argv == probe
                return {
                    "ok": owned,
                    "exit_code": 0 if owned else 1,
                    "argv": argv,
                    "output": "",
                }

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Windows"
            ), patch("manageroo.stack_update._run", side_effect=run):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [[
                "C:/Windows/winget.exe",
                "upgrade",
                "--id",
                "Obsidian.Obsidian",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]],
        )

    def test_unowned_winget_obsidian_update_is_not_planned(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian.exe"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {
                    "winget": "C:/Windows/winget.exe",
                    "obsidian": str(obsidian),
                }.get(name)

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Windows"
            ), patch(
                "manageroo.stack_update._run",
                return_value={"ok": False, "exit_code": 1, "output": "not installed"},
            ):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(plan["tools"][0]["commands"], [])
        self.assertIn("Winget", plan["tools"][0]["note"])

    def test_snap_owned_obsidian_outside_snap_bin_survives_policy_hardening(self):
        obsidian = "/snap/obsidian/current/usr/bin/obsidian"

        def which(name: str):
            return {"snap": "/usr/bin/snap", "obsidian": obsidian}.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update.platform.system", return_value="Linux"
        ):
            plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/bin/snap", "refresh", "obsidian"]],
        )

    def test_absent_gitnexus_is_not_treated_as_an_installed_tool(self):
        with patch("manageroo.stack_update.shutil.which", return_value=None):
            plan = stack_update_plan()
        gitnexus = next(item for item in plan["tools"] if item["name"] == "gitnexus")
        self.assertFalse(gitnexus["installed"])
        self.assertEqual(gitnexus["commands"], [])
        self.assertIn("will not install one implicitly", gitnexus["note"])

    def test_plan_can_target_one_tool(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "gitnexus": "/usr/bin/gitnexus"}.get(name)
        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=self.owned_run
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan(["gitnexus"])
        self.assertEqual(plan["selected_tools"], ["gitnexus"])
        self.assertEqual([item["name"] for item in plan["tools"]], ["gitnexus"])

    def test_trufflehog_update_requires_manageroo_ownership_proof(self):
        with patch("manageroo.stack_update.shutil.which", side_effect=lambda name: "/usr/bin/trufflehog" if name == "trufflehog" else None), patch(
            "manageroo.stack_update._manageroo_owned_trufflehog_path", return_value=None
        ):
            plan = stack_update_plan(["trufflehog"])
        tool = plan["tools"][0]
        self.assertTrue(tool["installed"])
        self.assertEqual(tool["install_paths"], [])
        self.assertIn("ownership", tool["note"].lower())

    def test_apply_one_tool_executes_no_unselected_tool_commands(self):
        calls: list[list[str]] = []

        def which(name: str):
            return {
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "gbrain": "/usr/bin/gbrain",
            }.get(name)

        def run(argv, **_kwargs):
            if argv[1:] == ["prefix", "-g"]:
                return {"ok": True, "exit_code": 0, "argv": list(argv), "output": "/usr\n"}
            calls.append(list(argv))
            return {"ok": True, "exit_code": 0, "argv": list(argv), "output": ""}

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=run
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            result = apply_stack_updates(["gitnexus"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_tools"], ["gitnexus"])
        self.assertEqual(calls, [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])

    def test_plan_drops_update_when_package_manager_ownership_is_not_proven(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "gitnexus": "/usr/bin/gitnexus"}.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=self.owned_run
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=False
        ):
            plan = stack_update_plan(["gitnexus"])

        tool = plan["tools"][0]
        self.assertEqual(tool["commands"], [])
        self.assertIn("ownership", tool["note"])

    def test_plan_updates_npm_owned_clawpatch_when_pnpm_is_absent(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "clawpatch": "/usr/bin/clawpatch"}.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan(["clawpatch"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [
                ["/usr/bin/npm", "install", "-g", CLAWPATCH_PACKAGE],
                ["/usr/bin/clawpatch", "doctor"],
            ],
        )

    def test_plan_proves_npm_owned_symlink_and_falls_back_from_wrong_manager(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "npm-prefix"
            npm_bin = prefix / "bin"
            package_root = prefix / "lib" / "node_modules"
            npm_bin.mkdir(parents=True)
            (package_root / "gitnexus" / "dist").mkdir(parents=True)
            (package_root / "clawpatch" / "dist").mkdir(parents=True)
            (package_root / "gitnexus" / "dist" / "cli.js").write_text("", encoding="utf-8")
            (package_root / "clawpatch" / "dist" / "cli.js").write_text("", encoding="utf-8")
            gitnexus = npm_bin / "gitnexus"
            clawpatch = npm_bin / "clawpatch"
            symlink_or_skip(
                self,
                package_root / "gitnexus" / "dist" / "cli.js",
                gitnexus,
            )
            symlink_or_skip(
                self,
                package_root / "clawpatch" / "dist" / "cli.js",
                clawpatch,
            )

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "pnpm": "/usr/bin/pnpm",
                    "gitnexus": str(gitnexus),
                    "clawpatch": str(clawpatch),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["prefix", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(prefix) + "\n"}
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["root", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(package_root) + "\n"}
                if argv[0] == "/usr/bin/npm" and argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": "installed\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:] == ["bin", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(Path(temp) / "pnpm-bin") + "\n"}
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "not owned"}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus", "clawpatch"])

            tools = {item["name"]: item for item in plan["tools"]}
            self.assertEqual(tools["gitnexus"]["commands"], [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])
            self.assertEqual(
                tools["clawpatch"]["commands"][:1],
                [["/usr/bin/npm", "install", "-g", CLAWPATCH_PACKAGE]],
            )

    def test_plan_falls_back_to_pnpm_for_pnpm_owned_gitnexus(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            npm_prefix = root / "npm-prefix"
            pnpm_bin = root / "pnpm-bin"
            package_root = root / "pnpm-root" / "node_modules"
            pnpm_bin.mkdir()
            (package_root / "gitnexus" / "dist").mkdir(parents=True)
            target = package_root / "gitnexus" / "dist" / "cli.js"
            target.write_text("", encoding="utf-8")
            gitnexus = pnpm_bin / "gitnexus"
            symlink_or_skip(self, target, gitnexus)

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "pnpm": "/usr/bin/pnpm",
                    "gitnexus": str(gitnexus),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["prefix", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(npm_prefix) + "\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:] == ["bin", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(pnpm_bin) + "\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:] == ["root", "-g"]:
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "argv": argv,
                        "output": str(package_root) + "\n",
                    }
                if argv[0] == "/usr/bin/pnpm" and argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": "installed\n"}
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "not owned"}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus"])

            self.assertEqual(
                plan["tools"][0]["commands"],
                [["/usr/bin/pnpm", "add", "-g", GITNEXUS_PACKAGE]],
            )

    def test_codex_only_autoreview_is_updated_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            codex_target = home / ".codex" / "skills" / "autoreview"
            codex_target.mkdir(parents=True)
            (codex_target / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    checkout = Path(kwargs["cwd"])
                    skill = checkout / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": AUTOREVIEW_COMMIT + "\n"}
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            def which(name: str):
                return "/usr/bin/git" if name == "git" else None

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", side_effect=which
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertTrue(result["ok"])
            self.assertEqual((codex_target / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertFalse((home / ".agents" / "skills" / "autoreview").exists())
            self.assertEqual(
                list(codex_target.parent.glob("autoreview.manageroo-backup-*")),
                [],
            )
            self.assertEqual(
                list((home / ".codex").glob(".autoreview.manageroo-rollback-*")),
                [],
            )
            installation = result["results"][0]["installations"][0]
            self.assertIsNone(installation["backup"])

    def test_autoreview_update_omits_only_the_known_claude_compatibility_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            destination = home / ".codex" / "skills" / "autoreview"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    skill = Path(kwargs["cwd"]) / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
                    (skill / "AGENTS.md").write_text("rules\n", encoding="utf-8")
                    symlink_or_skip(self, "AGENTS.md", skill / "CLAUDE.md")
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": AUTOREVIEW_COMMIT + "\n"}
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", side_effect=lambda name: "/usr/bin/git" if name == "git" else None
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertTrue(result["ok"], result)
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertTrue((destination / "AGENTS.md").is_file())
            self.assertFalse((destination / "CLAUDE.md").exists())

    def test_symlinked_autoreview_alias_is_preserved_and_resolved_target_updated_once(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "autoreview"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )
            alias = home / ".agents" / "skills" / "autoreview"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(target, target_is_directory=True)
            replacements = []

            def fake_update(installations):
                replacements.extend(
                    Path(item["resolved_path"]) for item in installations
                )
                return {"ok": True, "name": "autoreview", "installations": []}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update._update_autoreview", side_effect=fake_update
            ):
                result = apply_stack_updates(["autoreview"])
            self.assertTrue(result["ok"])
            self.assertTrue(alias.is_symlink())
            self.assertEqual(replacements, [target.resolve()])

    def test_autoreview_retargeted_alias_is_rejected_without_touching_victim(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "autoreview"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )
            alias = home / ".agents" / "skills" / "autoreview"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(target, target_is_directory=True)
            victim = home / "victim"
            victim.mkdir()
            (victim / "KEEP.txt").write_text("untouched\n", encoding="utf-8")

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", return_value=None
            ):
                plan = stack_update_plan(["autoreview"])
            installation_records = plan["tools"][0]["installation_records"]
            alias.unlink()
            alias.symlink_to(victim, target_is_directory=True)

            with patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else None,
            ), patch("manageroo.stack_update._run", side_effect=self._fake_autoreview_git_run):
                result = _update_autoreview(installation_records)

            self.assertFalse(result["ok"], result)
            self.assertEqual((victim / "KEEP.txt").read_text(encoding="utf-8"), "untouched\n")
            self.assertEqual(
                (target / "SKILL.md").read_text(encoding="utf-8"),
                "---\nname: autoreview\n---\nold\n",
            )

    def test_autoreview_replaced_directory_is_rejected_without_touching_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            destination = home / ".codex" / "skills" / "autoreview"
            destination.mkdir(parents=True)
            original_skill = "---\nname: autoreview\n---\nold\n"
            (destination / "SKILL.md").write_text(original_skill, encoding="utf-8")

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", return_value=None
            ):
                plan = stack_update_plan(["autoreview"])
            installation_records = plan["tools"][0]["installation_records"]
            moved = destination.with_name("autoreview-original")
            destination.rename(moved)
            destination.mkdir()
            (destination / "SKILL.md").write_text(original_skill, encoding="utf-8")
            (destination / "KEEP.txt").write_text("untouched\n", encoding="utf-8")

            with patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else None,
            ), patch("manageroo.stack_update._run", side_effect=self._fake_autoreview_git_run):
                result = _update_autoreview(installation_records)

            self.assertFalse(result["ok"], result)
            self.assertEqual((destination / "KEEP.txt").read_text(encoding="utf-8"), "untouched\n")
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), original_skill)
            self.assertEqual((moved / "SKILL.md").read_text(encoding="utf-8"), original_skill)

    def test_autoreview_substitution_after_final_check_is_restored_and_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            actual_home = Path(temp) / "actual-home"
            home = Path(temp) / "home-alias"
            actual_home.mkdir()
            symlink_or_skip(self, actual_home, home, target_is_directory=True)
            destination = home / ".codex" / "skills" / "autoreview"
            destination.mkdir(parents=True)
            original_skill = "---\nname: autoreview\n---\nold\n"
            (destination / "SKILL.md").write_text(original_skill, encoding="utf-8")
            source = home / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n", encoding="utf-8")

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", return_value=None
            ):
                installation = stack_update_plan(["autoreview"])["tools"][0][
                    "installation_records"
                ][0]

            displaced = destination.with_name("autoreview-original")
            import manageroo.stack_update as stack_update_module

            original_check = stack_update_module._autoreview_installation_error
            check_count = 0

            def substitute_after_final_check(record, checked_destination):
                nonlocal check_count
                result = original_check(record, checked_destination)
                check_count += 1
                if check_count == 3 and result is None:
                    destination.rename(displaced)
                    destination.mkdir()
                    (destination / "KEEP.txt").write_text(
                        "concurrent replacement\n", encoding="utf-8"
                    )
                return result

            with patch(
                "manageroo.stack_update._autoreview_installation_error",
                side_effect=substitute_after_final_check,
            ):
                result = _replace_autoreview(source, destination, installation)

            self.assertFalse(result["ok"], result)
            self.assertIn("identity does not match", result["error"])
            self.assertEqual(
                (destination / "KEEP.txt").read_text(encoding="utf-8"),
                "concurrent replacement\n",
            )
            self.assertEqual(
                (displaced / "SKILL.md").read_text(encoding="utf-8"), original_skill
            )
            self.assertEqual(
                list((home / ".codex").glob(".autoreview.manageroo-rollback-*")), []
            )

    def test_autoreview_alias_targeting_another_skill_is_rejected_without_changes(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "other-skill"
            target.mkdir(parents=True)
            original_skill = "---\nname: other-skill\n---\noriginal\n"
            (target / "SKILL.md").write_text(original_skill, encoding="utf-8")
            (target / "KEEP.txt").write_text("keep me\n", encoding="utf-8")
            alias = home / ".agents" / "skills" / "autoreview"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(target, target_is_directory=True)

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    skill = Path(kwargs["cwd"]) / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text(
                        "---\nname: autoreview\n---\nupdated\n",
                        encoding="utf-8",
                    )
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "argv": argv,
                        "output": AUTOREVIEW_COMMIT + "\n",
                    }
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else None,
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertFalse(result["ok"], result)
            self.assertIn("unsafe", result["results"][0]["error"].lower())
            self.assertTrue(alias.is_symlink())
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), original_skill)
            self.assertEqual((target / "KEEP.txt").read_text(encoding="utf-8"), "keep me\n")

    def test_autoreview_failed_swap_restores_original_and_preserves_old_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n", encoding="utf-8")
            destination = root / "autoreview"
            destination.mkdir()
            (destination / "SKILL.md").write_text("old\n", encoding="utf-8")
            prior_backup = root / "autoreview.manageroo-backup-prior"
            prior_backup.mkdir()
            (prior_backup / "SKILL.md").write_text("older\n", encoding="utf-8")

            original_rename = Path.rename

            def fail_stage_rename(path, target):
                if ".manageroo-stage" in path.name:
                    raise OSError("simulated swap failure")
                return original_rename(path, target)

            with patch.object(Path, "rename", autospec=True, side_effect=fail_stage_rename):
                result = _replace_autoreview(source, destination)

            self.assertFalse(result["ok"])
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "old\n")
            self.assertEqual((prior_backup / "SKILL.md").read_text(encoding="utf-8"), "older\n")
            self.assertEqual(list(root.glob(".autoreview.manageroo-rollback-*")), [])

    def test_autoreview_cleanup_failure_reports_installed_update_with_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n", encoding="utf-8")
            destination = root / "skills" / "autoreview"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("old\n", encoding="utf-8")
            real_rmtree = shutil.rmtree

            def fail_rollback_cleanup(path, *args, **kwargs):
                if ".manageroo-rollback-" in Path(path).name:
                    raise OSError("simulated cleanup failure")
                return real_rmtree(path, *args, **kwargs)

            with patch("manageroo.stack_update_policy.shutil.rmtree", side_effect=fail_rollback_cleanup):
                result = _replace_autoreview(source, destination)

            self.assertTrue(result["ok"], result)
            self.assertIn("update was installed", result["cleanup_warning"].lower())
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertTrue(Path(result["backup"]).is_dir())

    def test_autoreview_lock_blocks_contender_before_owner_metadata_is_published(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            context = multiprocessing.get_context("spawn")
            publication_paused = context.Event()
            publish_owner = context.Event()
            owner_entered = context.Event()
            release_owner = context.Event()
            contender_opened = context.Event()
            contender_entered = context.Event()
            owner = context.Process(
                target=_hold_autoreview_lock_before_owner_publication,
                args=(
                    destination,
                    publication_paused,
                    publish_owner,
                    owner_entered,
                    release_owner,
                ),
            )
            contender = context.Process(
                target=_enter_autoreview_lock,
                args=(destination, contender_opened, contender_entered),
            )

            try:
                owner.start()
                self.assertTrue(publication_paused.wait(timeout=5))
                contender.start()
                self.assertTrue(contender_opened.wait(timeout=5))
                self.assertFalse(contender_entered.wait(timeout=0.3))
                publish_owner.set()
                self.assertTrue(owner_entered.wait(timeout=5))
                self.assertFalse(contender_entered.wait(timeout=0.3))
                release_owner.set()
                owner.join(timeout=5)
                contender.join(timeout=5)
                self.assertEqual(owner.exitcode, 0)
                self.assertEqual(contender.exitcode, 0)
                self.assertTrue(contender_entered.is_set())
            finally:
                publish_owner.set()
                release_owner.set()
                for process in (owner, contender):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

    def test_autoreview_lock_never_unlinks_stale_owner_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
            lock.write_text("pid=999999999\n", encoding="utf-8")

            with patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=AssertionError("lock path must not be unlinked"),
            ):
                from manageroo.stack_update_policy import _destination_lock

                with _destination_lock(destination):
                    pass

            self.assertTrue(lock.is_file())
            self.assertEqual(lock.read_text(encoding="utf-8"), f"pid={os.getpid()}\n")

    def test_autoreview_lock_rejects_hard_link_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
            victim = Path(temp) / "victim.txt"
            sentinel = b"do not overwrite\n"
            victim.write_bytes(sentinel)
            try:
                os.link(victim, lock)
            except OSError as exc:
                self.skipTest(f"hard links are unavailable: {exc}")

            from manageroo.stack_update_policy import _destination_lock

            with self.assertRaises(OSError):
                with _destination_lock(destination):
                    pass

            self.assertEqual(victim.read_bytes(), sentinel)

    def test_autoreview_lock_rejects_symlink_without_o_nofollow(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
            victim = Path(temp) / "victim.txt"
            sentinel = b"do not overwrite\n"
            victim.write_bytes(sentinel)
            symlink_or_skip(self, victim, lock)

            import manageroo.stack_update_policy as policy

            with patch.object(policy.os, "O_NOFOLLOW", 0, create=True):
                with self.assertRaises(OSError):
                    with policy._destination_lock(destination):
                        pass

            self.assertEqual(victim.read_bytes(), sentinel)

    def test_plain_output_makes_apply_boundary_explicit(self):
        text = format_stack_update(stack_update_plan())
        self.assertIn("No changes were made", text)
        self.assertIn("--apply", text)


if __name__ == "__main__":
    unittest.main()
