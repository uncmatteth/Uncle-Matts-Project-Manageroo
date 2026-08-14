import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.stack_update import CLAWPATCH_PACKAGE, GITNEXUS_PACKAGE, stack_update_plan
from manageroo.token_modes import CORE_SKILL_NAMES


ROOT = Path(__file__).resolve().parents[1]
FINALIZE_GITNEXUS = ROOT / "scripts" / "finalize_gitnexus.py"


def load_finalize_gitnexus():
    spec = importlib.util.spec_from_file_location(
        "manageroo_finalize_gitnexus",
        FINALIZE_GITNEXUS,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GitNexus finalizer: {FINALIZE_GITNEXUS}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallStackContractTests(unittest.TestCase):
    def test_gitnexus_setup_success_is_persisted_in_the_install_lock(self):
        finalizer = load_finalize_gitnexus()
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            prefix.mkdir()
            lock_path = prefix / "install-lock.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "external_tools": [
                            {
                                "name": "gitnexus",
                                "installed": True,
                                "configured": False,
                                "path": "/tools/gitnexus",
                            }
                        ],
                        "stack_summary": {"stale": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                ["/tools/gitnexus", "setup"],
                0,
                stdout="setup complete\n",
            )
            with (
                patch.object(finalizer.shutil, "which", return_value="/tools/gitnexus"),
                patch.object(finalizer.subprocess, "run", return_value=completed) as run_setup,
            ):
                result = finalizer.finalize(prefix)

            run_setup.assert_called_once_with(
                ["/tools/gitnexus", "setup"],
                cwd=str(Path.home()),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                timeout=600,
            )
            persisted = json.loads(lock_path.read_text(encoding="utf-8"))

        self.assertEqual(result["configured"], True)
        record = persisted["external_tools"][0]
        self.assertTrue(record["configured"])
        self.assertEqual(record["next_commands"], [])
        self.assertEqual(record["setup_result"]["argv"], ["/tools/gitnexus", "setup"])
        summary = persisted["stack_summary"]
        self.assertEqual(summary["counts"]["configured"], 1)
        self.assertFalse(summary["items"][0]["needs_action"])

    def test_windows_installer_executes_gitnexus_finalizer_after_main_install(self):
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            self.skipTest("PowerShell is unavailable on this host")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            command_log = root / "python.log"
            prefix = root / "prefix"
            harness = root / "run-installer.ps1"
            harness.write_text(
                "function global:Record-PythonCall {\n"
                "  Add-Content -LiteralPath $env:PYTHON_LOG -Value "
                "(ConvertTo-Json -Compress -InputObject @($args))\n"
                "  $global:LASTEXITCODE = 0\n"
                "}\n"
                "function global:py { Record-PythonCall @args }\n"
                "function global:python { Record-PythonCall @args }\n"
                "function global:git { $global:LASTEXITCODE = 0 }\n"
                "& $env:INSTALL_PS1 -Prefix $env:INSTALL_PREFIX -SkipTests -SkipStack "
                "-SkipSkillPack -TokenMode off -Agent auto -GBrainLane skip "
                "-StackDoctor skip -ClawpatchCodexLogin skip "
                "-NoMusic -NoAnimation\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(harness),
                ],
                env={
                    **os.environ,
                    "INSTALL_PS1": str(ROOT / "install.ps1"),
                    "INSTALL_PREFIX": str(prefix),
                    "PYTHON_LOG": str(command_log),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [
                json.loads(line)
                for line in command_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(calls), 3)
            self.assertIn("-c", calls[0])
            self.assertIn(str(ROOT / "scripts" / "install.py"), calls[1])
            finalizer_index = calls[2].index(str(FINALIZE_GITNEXUS))
            self.assertEqual(calls[2][finalizer_index + 1 :], ["--prefix", str(prefix)])

    def test_gitnexus_setup_failure_is_returned_and_persisted(self):
        finalizer = load_finalize_gitnexus()
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            prefix.mkdir()
            lock_path = prefix / "install-lock.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "external_tools": [
                            {
                                "name": "gitnexus",
                                "installed": True,
                                "configured": False,
                                "path": "/tools/gitnexus",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess(
                ["/tools/gitnexus", "setup"],
                7,
                stdout="setup failed\n",
            )
            with (
                patch.object(finalizer.shutil, "which", return_value="/tools/gitnexus"),
                patch.object(finalizer.subprocess, "run", return_value=completed),
            ):
                result = finalizer.finalize(prefix)
            persisted = json.loads(lock_path.read_text(encoding="utf-8"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        record = persisted["external_tools"][0]
        self.assertFalse(record["configured"])
        self.assertEqual(record["next_commands"], ["gitnexus setup"])
        self.assertEqual(record["setup_result"]["exit_code"], 7)
        self.assertTrue(persisted["stack_summary"]["items"][0]["needs_action"])

    def test_public_docs_match_portable_boundary_and_exact_22_skill_core(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        public = readme + "\n" + installation
        self.assertNotIn("Tommy's", public)
        self.assertNotIn("HOST_AND_TOS_INTEGRATION", public)
        self.assertNotIn("host/tOS", public)
        self.assertIn("docs/HOST_SKILL_ECOSYSTEM.md", readme)

        expected = list(CORE_SKILL_NAMES)
        self.assertEqual(len(expected), 22)
        self.assertEqual(len(expected), len(set(expected)))
        for index, skill in enumerate(expected, 1):
            with self.subTest(skill=skill):
                marker = f"{index}. `{skill}`"
                self.assertIn(marker, readme)
                self.assertIn(marker, installation)

        for text in (readme, installation):
            numbered = re.findall(r"(?m)^\s*(\d+)\. `([^`]+)`\s*$", text)
            core_block = [name for number, name in numbered if 1 <= int(number) <= 22]
            self.assertGreaterEqual(len(core_block), 22)
            self.assertEqual(core_block[:22], expected)

    def test_gitnexus_is_documented_as_required_but_non_authoritative(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        installation = (ROOT / "docs" / "INSTALLATION.md").read_text(encoding="utf-8")
        self.assertIn("GitNexus is required repository intelligence", readme)
        self.assertIn("GitNexus is required", installation)
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
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
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
