import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.install_repair import repair_install


class InstallRepairTests(unittest.TestCase):
    def test_missing_lock_reports_reinstall_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            result = repair_install(prefix=Path(temp) / "missing", apply=False)
            self.assertFalse(result["ok"])
            self.assertIn("./install.sh", result["next_commands"][0])

    def test_apply_recreates_missing_launcher_from_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            bin_dir = Path(temp) / "bin"
            launcher = bin_dir / "umsmfburasbofe"
            prefix.mkdir()
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(launcher)}) + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"UMSMFBURASBOFE_SKILLS_DIR": str(Path(temp) / "skills")}):
                result = repair_install(prefix=prefix, bin_dir=bin_dir, apply=True)
            self.assertTrue(result["ok"])
            self.assertTrue(launcher.exists())
            self.assertIn("PYTHONPATH", launcher.read_text(encoding="utf-8"))
            self.assertTrue(any(action["name"] == "launcher" for action in result["actions"]))

    def test_no_apply_does_not_install_helper_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            bin_dir = Path(temp) / "bin"
            launcher = bin_dir / "umsmfburasbofe"
            prefix.mkdir()
            bin_dir.mkdir()
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(launcher)}) + "\n",
                encoding="utf-8",
            )
            skills = Path(temp) / "skills"
            with patch.dict(os.environ, {"UMSMFBURASBOFE_SKILLS_DIR": str(skills)}):
                result = repair_install(prefix=prefix, bin_dir=bin_dir, apply=False)
            self.assertFalse((skills / "pimp-my-prompt").exists())
            self.assertTrue(result["ok"])

    def test_reports_bin_dir_from_lock_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            custom_bin = Path(temp) / "custom-bin"
            launcher = custom_bin / "umsmfburasbofe"
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
