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
    def test_skill_pack_is_recommended_default_but_can_be_skipped(self):
        install = load_install_script()
        self.assertEqual(install.choose_skill_pack_mode("install", False), "install")
        self.assertEqual(install.choose_skill_pack_mode("skip", False), "skip")
        self.assertEqual(install.choose_skill_pack_mode("ask", True), "skip")

    def test_skill_pack_prompt_defaults_to_install(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")

    def test_skill_pack_prompt_explains_default_skip_and_later_install(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with redirect_stdout(output):
                    self.assertEqual(install.choose_skill_pack_mode("ask", False), "skip")
        prompt = output.getvalue()
        self.assertIn("optional, but strongly suggested", prompt)
        self.assertIn("Default is yes", prompt)
        self.assertIn("You can skip it", prompt)
        self.assertIn("manageroo skills reconcile --apply", prompt)

    def test_skill_pack_non_interactive_uses_recommended_install(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=False):
            self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")

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

    def test_stack_doctor_prompt_defaults_to_run_when_interactive(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_stack_doctor_mode("ask"), "run")

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


if __name__ == "__main__":
    unittest.main()
