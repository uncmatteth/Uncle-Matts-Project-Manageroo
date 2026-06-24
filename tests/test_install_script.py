import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scripts" / "install.py"


def load_install_script():
    spec = importlib.util.spec_from_file_location("manageroo_install_script", INSTALL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load installer script: {INSTALL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallScriptTests(unittest.TestCase):
    def test_skill_pack_is_required_and_cannot_be_skipped(self):
        install = load_install_script()
        self.assertEqual(install.choose_skill_pack_mode("install", False), "install")
        self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")
        with self.assertRaises(SystemExit):
            install.choose_skill_pack_mode("skip", False)
        with self.assertRaises(SystemExit):
            install.choose_skill_pack_mode("ask", True)

    def test_skill_pack_prompt_defaults_to_install_without_choice(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with redirect_stdout(output):
                self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")
        prompt = output.getvalue()
        self.assertIn("Required local skill pack", prompt)
        self.assertIn("full Manageroo install", prompt)
        self.assertNotIn("optional", prompt.lower())
        self.assertNotIn("skip", prompt.lower())

    def test_skill_pack_non_interactive_uses_required_install(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=False):
            self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")

    def test_stack_mode_is_required_and_cannot_be_skipped(self):
        install = load_install_script()
        self.assertEqual(install.choose_stack_mode("ask", False, False), "install")
        self.assertEqual(install.choose_stack_mode("install", False, False), "install")
        with self.assertRaises(SystemExit):
            install.choose_stack_mode("ask", False, True)
        with self.assertRaises(SystemExit):
            install.choose_stack_mode("skip", False, False)

    def test_token_mode_has_only_caveman_or_curse(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=False):
            self.assertEqual(install.choose_token_mode("ask"), "caveman")
        self.assertEqual(install.choose_token_mode("caveman"), "caveman")
        self.assertEqual(install.choose_token_mode("curse"), "curse")
        with self.assertRaises(SystemExit):
            install.choose_token_mode("off")
        with self.assertRaises(SystemExit):
            install.choose_token_mode("none")
        with self.assertRaises(SystemExit):
            install.choose_token_mode("normal")

    def test_lane_explainer_is_plain_english(self):
        install = load_install_script()
        output = io.StringIO()
        with redirect_stdout(output):
            install.print_lane_explainer()
        text = output.getvalue()
        self.assertIn("Memory lane", text)
        self.assertIn("Document/prose lane", text)
        self.assertIn("Intent lock lane", text)
        self.assertIn("compaction audit", text)
        self.assertIn("document_analysis_command", text)
        self.assertIn("ready prints WARN but does not block", text)
        self.assertIn("AUTOREVIEW/Clawpatch lane", text)

    def test_next_commands_offer_project_picker_instead_of_manual_path_juggling(self):
        install = load_install_script()
        output = io.StringIO()
        with redirect_stdout(output):
            install.print_next_commands()
        text = output.getvalue()
        self.assertIn("manageroo projects --pick", text)
        self.assertIn("manageroo projects --add", text)
        self.assertIn("manageroo stack-doctor", text)
        self.assertIn("manageroo skills reconcile --apply", text)
        self.assertIn("manageroo skills reconcile --source ~/Downloads/SKILLS --include-external --apply", text)
        self.assertIn("manageroo intent show", text)
        self.assertIn("manageroo compact audit --summary SUMMARY.md", text)
        self.assertIn("checkbox-style list", text)
        self.assertNotIn("cd /path/to/project && manageroo solo", text)

    def test_project_discovery_prompt_defaults_to_add_selected_projects(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(output):
                    self.assertEqual(install.choose_project_discovery_mode("ask"), "add")
        text = output.getvalue()
        self.assertIn("checkbox-style", text)
        self.assertIn("choose which ones to add", text)
        self.assertIn("paste extra paths", text)
        with self.assertRaises(SystemExit):
            install.choose_project_discovery_mode("skip")
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="skip"):
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        install.choose_project_discovery_mode("ask")

    def test_stack_doctor_prompt_defaults_to_run_when_interactive(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_stack_doctor_mode("ask"), "run")
        with self.assertRaises(SystemExit):
            install.choose_stack_doctor_mode("skip")

    def test_loop_library_defaults_to_codex_instead_of_skip(self):
        install = load_install_script()
        output = io.StringIO()
        with (
            patch.object(install.shutil, "which", return_value="/usr/bin/npx"),
            patch.object(install.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value=""),
            patch.object(install, "optional_run", return_value={"ok": True, "argv": ["npx"]}) as run_mock,
            redirect_stdout(output),
        ):
            result = install.install_loop_library([], [])

        self.assertTrue(result["installed"])
        self.assertEqual(result["agents"], ["codex"])
        self.assertNotIn("skip", output.getvalue().lower())
        argv = run_mock.call_args.args[0]
        self.assertIn("--agent", argv)
        self.assertIn("codex", argv)

    def test_loop_library_rejects_removed_skip_answer(self):
        install = load_install_script()
        with (
            patch.object(install.shutil, "which", return_value="/usr/bin/npx"),
            patch.object(install.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="skip"),
            patch.object(install, "optional_run") as run_mock,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                install.install_loop_library([], [])
        run_mock.assert_not_called()

    def test_clawpatch_codex_login_prompt_treats_legacy_skip_as_no(self):
        install = load_install_script()
        with (
            patch.object(install.shutil, "which", return_value="/usr/bin/codex"),
            patch.object(install, "probe_command", return_value={"ok": False, "returncode": 1}),
            patch.object(install.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="skip"),
            patch.object(install, "run_interactive_action") as login_mock,
        ):
            result = install.check_clawpatch_codex_provider("ask")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["login_result"])
        login_mock.assert_not_called()

    def test_gbrain_prompt_rejects_removed_skip_lane(self):
        install = load_install_script()
        with (
            patch.object(install.sys.stdin, "isatty", return_value=True),
            patch("builtins.input", return_value="3"),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                install.choose_gbrain_lane("ask")

    def test_powershell_installer_exposes_important_python_flags(self):
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        py = INSTALL_SCRIPT.read_text(encoding="utf-8")
        important = [
            ("GBrainLane", "--gbrain-lane"),
            ("ProjectDiscovery", "--project-discovery"),
            ("StackDoctor", "--stack-doctor"),
            ("ClawpatchCodexLogin", "--clawpatch-codex-login"),
        ]
        for parameter, flag in important:
            with self.subTest(flag=flag):
                self.assertIn(flag, py)
                self.assertIn(f"${parameter}", ps1)
                self.assertIn(flag, ps1)
        self.assertIn("--skip-tests", py)
        self.assertNotIn("$SkipTests", ps1)
        self.assertNotIn("--skip-tests", ps1)

    def test_public_installer_and_docs_do_not_hardcode_tommy_skill_import_path(self):
        public_files = [
            ROOT / "scripts" / "install.py",
            ROOT / "README.md",
            ROOT / "LOCAL_SETUP.md",
            ROOT / "docs" / "00_START_HERE.md",
            ROOT / "docs" / "INSTALLATION.md",
        ]
        for path in public_files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/home/Tommy/Downloads/SKILLS", text)
                self.assertIn("~/Downloads/SKILLS", text)

    def test_official_gbrain_lane_does_not_tell_users_to_copy_paste(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install, "command_version", return_value="not installed"):
            with redirect_stdout(output):
                result = install.install_gbrain([], lane="official")
        text = output.getvalue() + "\n".join(result["next_commands"])
        self.assertIn("official GBrain agent install guide", text)
        self.assertNotIn("Paste this into your AI agent", text)


if __name__ == "__main__":
    unittest.main()
