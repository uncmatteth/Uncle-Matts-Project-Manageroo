import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CapacityPublicSurfaceTests(unittest.TestCase):
    def test_installers_surface_capacity_command_without_claiming_machine_minimums(self):
        for relative in ("install.sh", "install.ps1"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("manageroo capacity", text)
                self.assertIn("product minimum requirement", text)

    def test_github_copy_explains_discovery_and_capacity(self):
        text = (ROOT / "GITHUB_DESCRIPTION.md").read_text(encoding="utf-8")
        self.assertIn("unknown-unknowns preflight", text)
        self.assertIn("manageroo decisions answer RUN_ID", text)
        self.assertIn("manageroo capacity", text)
        self.assertIn("not the product's minimum hardware requirement", text)

    def test_dedicated_discovery_capacity_document_is_packaged_source(self):
        path = ROOT / "docs" / "DISCOVERY_AND_CAPACITY.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("manageroo decisions answer", text)
        self.assertIn("manageroo capacity", text)


if __name__ == "__main__":
    unittest.main()
