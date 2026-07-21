import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.integrations import ObsidianIntegration


class IntegrationTests(unittest.TestCase):
    def test_obsidian_export_stays_inside_configured_export_root(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            vault.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")

            destination = integration.export("notes/report.md", "# Report\n")
            self.assertEqual(destination, (vault / "exports" / "notes" / "report.md").resolve())
            self.assertEqual(destination.read_text(encoding="utf-8"), "# Report\n")

    def test_obsidian_export_rejects_absolute_and_parent_traversal_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            vault.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")
            outside = root / "outside.md"

            with self.assertRaises(SafetyError):
                integration.export("../outside.md", "x")
            with self.assertRaises(SafetyError):
                integration.export(str(outside.resolve()), "x")
            self.assertFalse(outside.exists())

    def test_obsidian_export_rejects_symlink_parent_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            outside = root / "outside"
            (vault / "exports").mkdir(parents=True)
            outside.mkdir()
            try:
                (vault / "exports" / "link").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable on this platform")

            integration = ObsidianIntegration(str(vault), "exports")
            with self.assertRaises(SafetyError):
                integration.export("link/report.md", "x")
            self.assertFalse((outside / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
