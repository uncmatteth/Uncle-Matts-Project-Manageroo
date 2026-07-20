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

    def test_skill_pack_prompt_can_skip_and_records_later_reconcile_command(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_skill_pack_mode("ask", False), "skip")
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Portable core skill pack skipped", source)
        self.assertIn("manageroo skills reconcile --apply", source)

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
        self.assertIn("How Manageroo fits together", text)
        self.assertIn("Manageroo owns run truth", text)
        self.assertIn("GitNexus", text)
        self.assertIn("GBrain", text)
        self.assertIn("AUTOREVIEW and Clawpatch", text)
        self.assertIn("Host skills", text)

    def test_next_commands_offer_guided_project_setup(self):
        install = load_install_script()
        output = io.StringIO()
        with redirect_stdout(output):
            install.print_next_commands()
        text = output.getvalue()
        self.assertIn("manageroo projects --add", text)
        self.assertIn("manageroo stack-doctor", text)
        self.assertIn("manageroo repair-install --no-apply", text)
        self.assertIn("manageroo next", text)
        self.assertNotIn("cd /path/to/project && manageroo solo", text)

    def test_project_discovery_prompt_defaults_to_add_selected_projects(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_project_discovery_mode("ask"), "add")

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
            ("Prefix", "--prefix"),
            ("BinDir", "--bin-dir"),
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

    def test_installer_has_no_external_loop_library_surface(self):
        py = INSTALL_SCRIPT.read_text(encoding="utf-8")
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        for text in (py, ps1):
            self.assertNotIn("--loop-library-agent", text)
            self.assertNotIn("Forward-Future/loop-library", text)
            self.assertNotIn("signals.forwardfuture", text)
        self.assertNotIn("install_loop_library", py)

    def test_public_installer_and_docs_do_not_hardcode_private_skill_import_paths(self):
        public_files = [
            ROOT / "scripts" / "install.py",
            ROOT / "README.md",
            ROOT / "LOCAL_SETUP.md",
            ROOT / "docs" / "00_START_HERE.md",
            ROOT / "docs" / "INSTALLATION.md",
        ]
        private_fragments = (
            "/home/Tommy/",
            "/Users/tommythehamburger/",
            "C:\\Users\\David\\",
            "Tommy's tOS",
        )
        for path in public_files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for fragment in private_fragments:
                    self.assertNotIn(fragment, text)

    def test_official_gbrain_lane_uses_upstream_agent_protocol(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install, "command_version", return_value="not installed"):
            with redirect_stdout(output):
                result = install.install_gbrain([], lane="official")
        text = output.getvalue() + "\n".join(result["next_commands"])
        self.assertIn("INSTALL_FOR_AGENTS.md", text)
        self.assertIn("agent-supervised", str(result.get("guidance", "")))
        self.assertNotIn("Paste this into your AI agent", text)


if __name__ == "__main__":
    unittest.main()
