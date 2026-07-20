import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallStackContractTests(unittest.TestCase):
    def test_gitnexus_setup_is_part_of_platform_installers(self):
        unix = (ROOT / "install.sh").read_text(encoding="utf-8")
        windows = (ROOT / "install.ps1").read_text(encoding="utf-8")
        finalizer = (ROOT / "scripts" / "finalize_gitnexus.py").read_text(encoding="utf-8")

        self.assertIn("scripts/finalize_gitnexus.py", unix)
        self.assertIn("scripts\\finalize_gitnexus.py", windows)
        self.assertIn('[str(executable), "setup"]', finalizer)
        self.assertIn('record["configured"] = configured', finalizer)
        self.assertIn('lock["stack_summary"] = summarize_external_tools', finalizer)

    def test_public_docs_match_portable_boundary_and_18_skill_core(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        public = readme + "\n" + installation

        self.assertNotIn("Tommy's", public)
        self.assertNotIn("HOST_AND_TOS_INTEGRATION", public)
        self.assertNotIn("host/tOS", public)
        self.assertIn("docs/HOST_INTEGRATION.md", readme)
        self.assertIn("18. `uncle-matts-caveman-curse`", readme)
        self.assertIn("18. `uncle-matts-caveman-curse`", installation)
        self.assertIn("`skill-vetter`", readme)
        self.assertIn("`skill-vetter`", installation)

    def test_gitnexus_is_documented_as_first_class_but_non_authoritative(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")

        self.assertIn("first-class recommended repository-intelligence integration", readme)
        self.assertIn("GitNexus is a first-class recommended integration", installation)
        self.assertIn("without becoming authorities over Manageroo completion", readme)

    def test_stack_update_supports_targeted_tools(self):
        entrypoint = (ROOT / "src" / "manageroo" / "entrypoint.py").read_text(encoding="utf-8")
        updater = (ROOT / "src" / "manageroo" / "stack_update.py").read_text(encoding="utf-8")

        self.assertIn("STACK_TOOL_NAMES", entrypoint)
        self.assertIn('nargs="*"', entrypoint)
        self.assertIn("def stack_update_plan(only:", updater)
        self.assertIn("def apply_stack_updates(only:", updater)
        self.assertIn('"gitnexus@latest"', updater)
        self.assertIn('[gbrain, "doctor", "--json"]', updater)


if __name__ == "__main__":
    unittest.main()
