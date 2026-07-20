import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.install_repair import repair_install


class InstallRepairTests(unittest.TestCase):
    def test_missing_lock_reports_reinstall_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            result = repair_install(prefix=Path(temp) / "missing", apply=False)
            self.assertFalse(result["ok"])
            self.assertIn("./install.sh", result["next_commands"][0])

    def test_malformed_lock_reports_actionable_reinstall_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            prefix.mkdir()
            (prefix / "install-lock.json").write_text("{", encoding="utf-8")
            result = repair_install(prefix=prefix, apply=False)
            self.assertFalse(result["ok"])
            self.assertTrue(result["next_commands"])
            self.assertIn("install", " ".join(result["next_commands"]).lower())

    def test_apply_recreates_missing_launcher_from_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            bin_dir = Path(temp) / "bin"
            launcher = bin_dir / "manageroo"
            prefix.mkdir()
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(launcher)}) + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"MANAGEROO_SKILLS_DIR": str(Path(temp) / "skills")}):
                result = repair_install(prefix=prefix, bin_dir=bin_dir, apply=True)
            self.assertTrue(result["ok"])
            self.assertTrue(launcher.exists())
            self.assertIn("PYTHONPATH", launcher.read_text(encoding="utf-8"))
            if os.name != "nt":
                self.assertTrue(os.access(launcher, os.X_OK))
                self.assertNotEqual(launcher.stat().st_mode & 0o111, 0)
            self.assertTrue(any(action["name"] == "launcher" for action in result["actions"]))

    def test_no_apply_does_not_install_helper_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            bin_dir = Path(temp) / "bin"
            launcher = bin_dir / "manageroo"
            prefix.mkdir()
            bin_dir.mkdir()
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            if os.name != "nt":
                launcher.chmod(0o755)
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(launcher)}) + "\n",
                encoding="utf-8",
            )
            skills = Path(temp) / "skills"
            with patch.dict(os.environ, {"MANAGEROO_SKILLS_DIR": str(skills)}):
                result = repair_install(prefix=prefix, bin_dir=bin_dir, apply=False)
            self.assertFalse((skills / "pimp-my-prompt").exists())
            self.assertTrue(result["ok"])

    def test_reports_bin_dir_from_lock_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            custom_bin = Path(temp) / "custom-bin"
            launcher = custom_bin / "manageroo"
            prefix.mkdir()
            custom_bin.mkdir()
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(launcher)}) + "\n",
                encoding="utf-8",
            )
            result = repair_install(prefix=prefix, apply=False)
            self.assertEqual(result["bin_dir"], str(custom_bin.resolve()))


if __name__ == "__main__":
    unittest.main()
