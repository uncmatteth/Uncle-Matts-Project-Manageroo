from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.install_update import update_install
from manageroo.cli import main


class InstallUpdateTests(unittest.TestCase):
    def test_update_cli_is_dry_run_by_default_and_apply_is_explicit(self):
        report = {"ok": True, "applied": False, "next_commands": ["manageroo update --apply"]}
        output = io.StringIO()
        with (
            patch("manageroo.cli.update_install", return_value=report) as update,
            patch("sys.stdout", output),
        ):
            code = main(["update", "--json"])

        self.assertEqual(code, 0)
        self.assertFalse(update.call_args.kwargs["apply"])
        self.assertFalse(json.loads(output.getvalue())["applied"])

    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        prefix = root / "prefix"
        source = root / "source"
        launcher = root / "bin" / "manageroo"
        prefix.mkdir()
        source.mkdir()
        launcher.parent.mkdir()
        (source / "scripts").mkdir()
        (source / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (source / "install.sh").chmod(0o755)
        (source / "scripts" / "install.py").write_text("# installer\n", encoding="utf-8")
        (source / "pyproject.toml").write_text(
            '[project]\nname = "uncle-matts-project-manageroo"\nversion = "2026.8.13.2"\n',
            encoding="utf-8",
        )
        (prefix / "install-lock.json").write_text(
            json.dumps(
                {
                    "source_root": str(source),
                    "prefix": str(prefix),
                    "launcher": str(launcher),
                    "agent_preference": "codex",
                    "token_mode": {"mode": "off"},
                    "manageroo_version_output": "2026.8.13.1",
                }
            ),
            encoding="utf-8",
        )
        return prefix, source, launcher

    def test_update_dry_run_uses_recorded_source_and_preserves_install_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix, source, launcher = self._fixture(Path(temp))
            with patch(
                "manageroo.install_update.installation_is_manageroo_owned",
                return_value=True,
            ):
                report = update_install(prefix=prefix, apply=False)

            self.assertTrue(report["ok"], report)
            self.assertFalse(report["applied"])
            self.assertEqual(report["source"], str(source.resolve()))
            self.assertEqual(report["available_version"], "2026.8.13.2")
            self.assertIn(str(prefix.resolve()), report["argv"])
            self.assertIn(str(launcher.parent.resolve()), report["argv"])
            self.assertIn("--stack", report["argv"])
            self.assertIn("skip", report["argv"])

    def test_update_prefers_current_token_mode_over_stale_install_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix, _source, _launcher = self._fixture(root)
            state = root / "token-mode.json"
            state.write_text(json.dumps({"mode": "caveman"}), encoding="utf-8")
            lock_path = prefix / "install-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["token_mode"]["state_path"] = str(state)
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            with patch(
                "manageroo.install_update.installation_is_manageroo_owned",
                return_value=True,
            ):
                report = update_install(prefix=prefix, apply=False)

            token_index = report["argv"].index("--token-mode")
            self.assertEqual(report["argv"][token_index + 1], "caveman")

    def test_update_apply_runs_the_verified_source_installer_through_sh_without_shell_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix, source, _launcher = self._fixture(Path(temp))
            completed = type("Completed", (), {"returncode": 0})()
            with (
                patch(
                    "manageroo.install_update.installation_is_manageroo_owned",
                    return_value=True,
                ),
                patch("manageroo.install_update.subprocess.run", return_value=completed) as run,
            ):
                report = update_install(prefix=prefix, apply=True)

            self.assertTrue(report["ok"], report)
            self.assertTrue(report["applied"])
            self.assertEqual(Path(run.call_args.args[0][0]).name, "sh")
            self.assertEqual(run.call_args.args[0][1], str((source / "install.sh").resolve()))
            self.assertEqual(run.call_args.kwargs["cwd"], source.resolve())
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_update_accepts_a_zip_extracted_installer_without_executable_bit(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix, source, _launcher = self._fixture(Path(temp))
            (source / "install.sh").chmod(0o644)
            with patch(
                "manageroo.install_update.installation_is_manageroo_owned",
                return_value=True,
            ):
                report = update_install(prefix=prefix, apply=False)

            self.assertTrue(report["ok"], report)
            self.assertEqual(Path(report["argv"][0]).name, "sh")
            self.assertEqual(report["argv"][1], str((source / "install.sh").resolve()))

    def test_update_refuses_a_forged_install_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix, _source, _launcher = self._fixture(Path(temp))
            with patch(
                "manageroo.install_update.installation_is_manageroo_owned",
                return_value=False,
            ):
                report = update_install(prefix=prefix, apply=True)
            self.assertFalse(report["ok"])
            self.assertFalse(report["applied"])
            self.assertIn("ownership", report["error"])

    def test_update_refuses_an_owned_lock_without_a_valid_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix, _source, _launcher = self._fixture(Path(temp))
            lock_path = prefix / "install-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock.pop("launcher")
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            with patch(
                "manageroo.install_update.installation_is_manageroo_owned",
                return_value=True,
            ):
                report = update_install(prefix=prefix, apply=True)

            self.assertFalse(report["ok"])
            self.assertFalse(report["applied"])
            self.assertIn("valid Manageroo launcher", report["error"])


if __name__ == "__main__":
    unittest.main()
