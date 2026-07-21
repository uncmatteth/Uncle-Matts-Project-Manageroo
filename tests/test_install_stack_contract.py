import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.stack_update import CLAWPATCH_PACKAGE, GITNEXUS_PACKAGE, stack_update_plan


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
        self.assertIn("docs/HOST_SKILL_ECOSYSTEM.md", readme)
        self.assertIn("18. `uncle-matts-caveman-curse`", readme)
        self.assertIn("18. `uncle-matts-caveman-curse`", installation)
        self.assertIn("`skill-vetter`", readme)
        self.assertIn("`skill-vetter`", installation)

    def test_gitnexus_is_documented_as_first_class_but_non_authoritative(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        self.assertIn("first-class recommended repository-intelligence integration", readme)
        self.assertIn("GitNexus is a first-class recommended integration", installation)
        self.assertIn("They do not become the authority over Manageroo completion", readme)

    def test_stack_update_targeting_is_behavioral_and_uses_pinned_packages(self):
        def which(name: str):
            return {
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "gbrain": "/usr/bin/gbrain",
            }.get(name)

        def owned_run(argv, **_kwargs):
            if argv[1:] == ["prefix", "-g"]:
                return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr\n"}
            if argv[1:] == ["bin", "-g"]:
                return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr/bin\n"}
            return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=owned_run
        ):
            gitnexus_only = stack_update_plan(["gitnexus"])
            clawpatch_only = stack_update_plan(["clawpatch"])

        self.assertEqual(gitnexus_only["selected_tools"], ["gitnexus"])
        self.assertEqual([item["name"] for item in gitnexus_only["tools"]], ["gitnexus"])
        self.assertEqual(gitnexus_only["tools"][0]["commands"], [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])
        self.assertEqual(clawpatch_only["selected_tools"], ["clawpatch"])
        self.assertEqual(clawpatch_only["tools"][0]["commands"], [["/usr/bin/pnpm", "add", "-g", CLAWPATCH_PACKAGE], ["/usr/bin/clawpatch", "doctor"]])
        self.assertNotIn("@latest", repr(gitnexus_only) + repr(clawpatch_only))


if __name__ == "__main__":
    unittest.main()
