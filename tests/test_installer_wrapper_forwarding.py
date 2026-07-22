from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerWrapperForwardingTests(unittest.TestCase):
    def test_powershell_value_parameters_forward_to_their_exact_python_flags(self):
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        mappings = {
            "Prefix": "--prefix",
            "BinDir": "--bin-dir",
            "TokenMode": "--token-mode",
            "SkillPack": "--skill-pack",
            "Stack": "--stack",
            "GBrainLane": "--gbrain-lane",
            "ProjectDiscovery": "--project-discovery",
            "StackDoctor": "--stack-doctor",
            "ClawpatchCodexLogin": "--clawpatch-codex-login",
            "ObsidianMethod": "--obsidian-method",
        }
        for parameter, flag in mappings.items():
            pattern = (
                rf"if\s*\(\${re.escape(parameter)}\)\s*\{{\s*"
                rf"\$InstallArgs\s*\+=\s*@\(\s*\"{re.escape(flag)}\"\s*,\s*"
                rf"\${re.escape(parameter)}\s*\)\s*\}}"
            )
            with self.subTest(parameter=parameter, flag=flag):
                self.assertRegex(text, re.compile(pattern, re.IGNORECASE | re.DOTALL))

    def test_powershell_switches_forward_to_their_exact_python_flags(self):
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        mappings = {
            "SkipCodex": "--skip-codex",
            "InstallCodex": "--install-codex",
            "InstallStack": "--install-stack",
            "SkipStack": "--skip-stack",
            "SkipTests": "--skip-tests",
            "SkipSkillPack": "--skip-skill-pack",
            "NoMusic": "--no-music",
            "NoAnimation": "--no-animation",
        }
        for parameter, flag in mappings.items():
            pattern = (
                rf"if\s*\(\${re.escape(parameter)}\)\s*\{{\s*"
                rf"\$InstallArgs\s*\+=\s*\"{re.escape(flag)}\"\s*\}}"
            )
            with self.subTest(parameter=parameter, flag=flag):
                self.assertRegex(text, re.compile(pattern, re.IGNORECASE | re.DOTALL))

    def test_python_installer_receives_the_built_argument_array(self):
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            re.compile(
                r"&\s*\$PythonExe\s+@PythonPrefixArgs\s+@InstallArgs",
                re.IGNORECASE,
            ),
        )


if __name__ == "__main__":
    unittest.main()
