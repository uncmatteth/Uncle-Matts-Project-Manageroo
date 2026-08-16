from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.errors import SafetyError
from manageroo.integrations import ObsidianIntegration


class PortableObsidianExportTests(unittest.TestCase):
    def test_macos_uses_descriptor_safe_fallback_without_openat2(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            (vault / "exports" / "notes").mkdir(parents=True)
            integration = ObsidianIntegration(str(vault), "exports")

            with patch("manageroo.integrations.platform.system", return_value="Darwin"), patch(
                "manageroo.integrations._openat2_syscall_number", return_value=None
            ), patch(
                "manageroo.integrations._descriptor_export_supported", return_value=True
            ):
                destination = integration.export("notes/report.md", "# macOS\n")

            self.assertEqual(
                destination, (vault / "exports" / "notes" / "report.md").resolve()
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), "# macOS\n")

    def test_linux_still_uses_original_openat2_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            (vault / "exports" / "notes").mkdir(parents=True)
            integration = ObsidianIntegration(str(vault), "exports")

            with patch("manageroo.integrations.platform.system", return_value="Linux"), patch(
                "manageroo.integrations._openat2_syscall_number", return_value=None
            ):
                with self.assertRaisesRegex(SafetyError, "openat2"):
                    integration.export("notes/report.md", "# Linux\n")

            self.assertFalse((vault / "exports" / "notes" / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
