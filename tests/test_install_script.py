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
    spec = importlib.util.spec_from_file_location("umsmfburasbofe_install_script", INSTALL_SCRIPT)
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
        self.assertIn("umsmfburasbofe skills install", prompt)

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
        self.assertIn("document_analysis_command", text)
        self.assertIn("ready prints WARN but does not block", text)
        self.assertIn("AUTOREVIEW/Clawpatch lane", text)


if __name__ == "__main__":
    unittest.main()
