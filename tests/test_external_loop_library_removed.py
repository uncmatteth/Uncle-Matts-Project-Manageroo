import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ExternalLoopLibraryRemovalTests(unittest.TestCase):
    def test_catalog_runtime_and_tests_are_absent(self):
        self.assertFalse((ROOT / "src" / "manageroo" / "loop_library.py").exists())
        self.assertFalse((ROOT / "tests" / "test_loop_library.py").exists())

    def test_runtime_and_installer_surfaces_do_not_expose_external_integration(self):
        surfaces = [
            ROOT / "src" / "manageroo" / "cli.py",
            ROOT / "src" / "manageroo" / "stack_doctor.py",
            ROOT / "src" / "manageroo" / "wizards.py",
            ROOT / "scripts" / "install.py",
            ROOT / "install.ps1",
        ]
        forbidden = [
            "manageroo loop-library",
            "--use-loop-library",
            "--loop-library-agent",
            "Forward-Future/loop-library",
            "signals.forwardfuture",
            "DEFAULT_CATALOG_URL",
            "install_loop_library",
        ]
        for surface in surfaces:
            text = surface.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(surface=surface.name, phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_readme_keeps_conceptual_credit_without_dependency_claim(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Matthew Berman / Forward Future", readme)
        self.assertIn("conceptual", readme.lower())
        self.assertIn("does not connect to or depend on Loop Library", readme)


if __name__ == "__main__":
    unittest.main()
