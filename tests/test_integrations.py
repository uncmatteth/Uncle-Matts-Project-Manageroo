import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.errors import SafetyError
from manageroo.integrations import ObsidianIntegration


class IntegrationTests(unittest.TestCase):
    def test_obsidian_export_without_openat2_never_creates_file_during_parent_rename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            (vault / "exports" / "notes").mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")
            from manageroo.integrations import os as integration_os

            original_open = integration_os.open
            export_directory_opens = 0

            def rename_after_fallback_opens_export(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal export_directory_opens
                descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
                if path == "exports" and flags & integration_os.O_DIRECTORY:
                    export_directory_opens += 1
                    if export_directory_opens == 2:
                        (vault / "exports").rename(outside / "exports-pinned")
                        (vault / "exports" / "notes").mkdir(parents=True)
                return descriptor

            with patch(
                "manageroo.integrations._openat2_syscall_number",
                return_value=None,
            ), patch(
                "manageroo.integrations._descriptor_export_supported",
                return_value=True,
            ), patch(
                "manageroo.integrations._descriptor_relative_open_supported",
                return_value=True,
            ), patch(
                "manageroo.integrations.os.open",
                side_effect=rename_after_fallback_opens_export,
            ):
                with self.assertRaisesRegex(SafetyError, "openat2"):
                    integration.export("notes/report.md", "# Portable\n")

            self.assertFalse((outside / "exports-pinned" / "notes" / "report.md").exists())
            self.assertFalse((vault / "exports" / "notes" / "report.md").exists())

    def test_obsidian_export_stays_inside_configured_export_root(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            (vault / "exports" / "notes").mkdir(parents=True)
            integration = ObsidianIntegration(str(vault), "exports")

            destination = integration.export("notes/report.md", "# Report\n")
            self.assertEqual(destination, (vault / "exports" / "notes" / "report.md").resolve())
            self.assertEqual(destination.read_text(encoding="utf-8"), "# Report\n")

    def test_obsidian_export_refuses_to_create_directory_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            vault.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")

            with self.assertRaises(SafetyError):
                integration.export("notes/report.md", "# Report\n")
            self.assertFalse((vault / "exports").exists())

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

    def test_obsidian_search_parent_swap_never_reads_outside_vault(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            notes = vault / "notes"
            notes.mkdir(parents=True)
            (notes / "inside.md").write_text("inside needle\n", encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            (outside / "inside.md").write_text("outside needle\n", encoding="utf-8")
            moved = root / "notes-pinned"
            integration = ObsidianIntegration(str(vault), "exports")
            from manageroo.integrations import _open_beneath

            swapped = False

            def swap_then_open(root_fd, relative, flags, mode=0):
                nonlocal swapped
                if not swapped:
                    notes.rename(moved)
                    try:
                        notes.symlink_to(outside, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        self.skipTest("directory symlinks are unavailable on this platform")
                    swapped = True
                return _open_beneath(root_fd, relative, flags, mode)

            with patch(
                "manageroo.integrations._open_beneath",
                side_effect=swap_then_open,
            ):
                self.assertEqual(integration.search("needle"), [])
            self.assertTrue(swapped)

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

    def test_obsidian_export_parent_swap_never_writes_outside_vault(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            parent = vault / "exports" / "notes"
            parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")

            from manageroo.integrations import _open_beneath

            def swap_then_open(root_fd, relative, flags, mode=0):
                moved = outside / "notes-pinned"
                parent.rename(moved)
                try:
                    parent.symlink_to(outside, target_is_directory=True)
                except (OSError, NotImplementedError):
                    self.skipTest("directory symlinks are unavailable on this platform")
                return _open_beneath(root_fd, relative, flags, mode)

            with patch(
                "manageroo.integrations._open_beneath",
                side_effect=swap_then_open,
            ):
                with self.assertRaises(SafetyError):
                    integration.export("notes/report.md", "safe\n")

            self.assertFalse((outside / "report.md").exists())
            self.assertEqual(
                list((outside / "notes-pinned").glob("*")),
                [],
            )

    def test_obsidian_export_rejects_hardlinked_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            parent = vault / "exports" / "notes"
            parent.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            outside_file = outside / "report.md"
            outside_file.write_text("outside\n", encoding="utf-8")
            try:
                (parent / "report.md").hardlink_to(outside_file)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this platform")
            integration = ObsidianIntegration(str(vault), "exports")

            with self.assertRaises(SafetyError):
                integration.export("notes/report.md", "safe\n")
            self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside\n")

    def test_obsidian_export_rejects_others_writable_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            parent = vault / "exports" / "notes"
            parent.mkdir(parents=True)
            parent.chmod(0o777)
            integration = ObsidianIntegration(str(vault), "exports")

            with self.assertRaises(SafetyError):
                integration.export("notes/report.md", "safe\n")
            self.assertFalse((parent / "report.md").exists())

    def test_obsidian_export_rejected_directory_does_not_leak_descriptors(self):
        descriptor_root = Path("/proc/self/fd")
        if not descriptor_root.is_dir():
            self.skipTest("process descriptor counts are unavailable on this platform")

        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            parent = vault / "exports" / "notes"
            parent.mkdir(parents=True)
            parent.chmod(0o777)
            integration = ObsidianIntegration(str(vault), "exports")
            descriptors_before = len(list(descriptor_root.iterdir()))

            for _ in range(20):
                with self.assertRaises(SafetyError):
                    integration.export("notes/report.md", "safe\n")

            self.assertEqual(len(list(descriptor_root.iterdir())), descriptors_before)


if __name__ == "__main__":
    unittest.main()
