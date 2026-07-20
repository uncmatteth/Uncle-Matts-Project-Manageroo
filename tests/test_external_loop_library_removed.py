import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from manageroo.cli import parser


ROOT = Path(__file__).resolve().parents[1]


class ExternalLoopLibraryRemovalTests(unittest.TestCase):
    def test_catalog_runtime_and_tests_are_absent(self):
        self.assertFalse((ROOT / "src" / "manageroo" / "loop_library.py").exists())
        self.assertFalse((ROOT / "tests" / "test_loop_library.py").exists())

    def test_removed_cli_command_and_solo_flag_are_rejected(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser().parse_args(["loop-library", "search", "docs"])
            with self.assertRaises(SystemExit):
                parser().parse_args(["solo", "--use-loop-library"])

    def test_runtime_and_installer_surfaces_do_not_expose_external_integration(self):
        surfaces = [
            ROOT / "src" / "manageroo" / "cli.py",
            ROOT / "src" / "manageroo" / "stack_doctor.py",
            ROOT / "src" / "manageroo" / "wizards.py",
            ROOT / "src" / "manageroo" / "install_status.py",
            ROOT / "scripts" / "install.py",
            ROOT / "install.ps1",
        ]
        forbidden = [
            "manageroo loop-library",
            "--use-loop-library",
            "--loop-library-agent",
            "Forward-Future/loop-library",
            "signals.forwardfuture.ai",
            "DEFAULT_CATALOG_URL",
            "install_loop_library",
            "loop_library",
        ]
        for surface in surfaces:
            text = surface.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(surface=surface.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_public_operating_docs_do_not_advertise_removed_commands_or_installation(self):
        surfaces = [
            ROOT / "README.md",
            ROOT / "GITHUB_DESCRIPTION.md",
            ROOT / "LOCAL_SETUP.md",
            ROOT / "docs" / "00_START_HERE.md",
            ROOT / "docs" / "INSTALLATION.md",
            ROOT / "docs" / "SOLO_OPERATOR_MODE.md",
            ROOT / "docs" / "EXTERNAL_INTEGRATIONS.md",
            ROOT / "docs" / "DEPENDENCY_POLICY.md",
        ]
        forbidden = [
            "manageroo loop-library",
            "--use-loop-library",
            "--loop-library-agent",
            "Forward-Future/loop-library",
            "signals.forwardfuture.ai",
            "installed with `npx --yes skills add Forward-Future",
        ]
        for surface in surfaces:
            text = surface.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(surface=surface.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_readme_keeps_credit_without_dependency_claim(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Matthew Berman / Forward Future", readme)
        self.assertIn("helped clarify the pattern", readme)
        self.assertIn("does not connect to or depend on Loop Library", readme)


if __name__ == "__main__":
    unittest.main()
