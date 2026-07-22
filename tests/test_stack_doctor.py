import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.cli import main
from manageroo.stack_doctor import _safe_probe_record, format_stack_doctor, stack_doctor
from manageroo.stack_update import (
    AUTOREVIEW_COMMIT,
    CLAWPATCH_PACKAGE,
    GBRAIN_COMMIT,
    GITNEXUS_PACKAGE,
    GITNEXUS_REFERENCE,
)


class StackDoctorTests(unittest.TestCase):
    def test_gbrain_installed_without_sources_gets_mapping_next_steps(self):
        probes = {
            ("gbrain", "config", "show"): {
                "ok": True,
                "exit_code": 0,
                "output": "engine: postgres\nembedding_model: ollama:nomic-embed-text\nschema_pack: gbrain-base-v2\n",
            },
            ("gbrain", "status", "--json", "--section", "sync"): {
                "ok": True,
                "exit_code": 0,
                "output": json.dumps({"sync": {"sources": []}}),
            },
            ("gbrain", "doctor", "--json"): {"ok": True, "exit_code": 0, "output": "{}"},
        }

        def which(name: str) -> str | None:
            return "/usr/bin/gbrain" if name == "gbrain" else None

        def runner(argv: list[str], timeout_seconds: int = 30) -> dict:
            key = tuple(Path(argv[0]).name if index == 0 else value for index, value in enumerate(argv))
            return probes.get(key, {"ok": False, "exit_code": 1, "output": "unexpected"})

        with tempfile.TemporaryDirectory() as temp:
            report = stack_doctor(which=which, runner=runner, home=Path(temp))

        gbrain = next(item for item in report["items"] if item["name"] == "gbrain")
        self.assertTrue(gbrain["installed"])
        self.assertFalse(gbrain["configured"])
        self.assertEqual(gbrain["status"], "needs_action")
        self.assertIn("ollama:nomic-embed-text", gbrain["detail"])
        self.assertIn("gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder", gbrain["next_commands"])
        self.assertEqual(gbrain["pinned_commit"], GBRAIN_COMMIT)
        self.assertFalse(report["ready"])

    def test_missing_tool_guidance_uses_release_pins_and_current_gitnexus_source(self):
        with tempfile.TemporaryDirectory() as temp:
            report = stack_doctor(which=lambda _name: None, runner=lambda _argv, _timeout: {}, home=Path(temp))
        by_name = {item["name"]: item for item in report["items"]}
        self.assertTrue(any(GBRAIN_COMMIT in command for command in by_name["gbrain"]["next_commands"]))
        self.assertIn(f"npm install -g {GITNEXUS_PACKAGE}", by_name["gitnexus"]["next_commands"])
        self.assertEqual(by_name["gitnexus"]["reference"], GITNEXUS_REFERENCE)
        self.assertTrue(any(CLAWPATCH_PACKAGE in command for command in by_name["clawpatch"]["next_commands"]))
        self.assertTrue(any(AUTOREVIEW_COMMIT in command for command in by_name["autoreview"]["next_commands"]))
        self.assertNotIn("@latest", repr(report))
        self.assertNotIn("nxpatterns/gitnexus", repr(report))

    def test_failed_probe_output_and_argv_are_redacted(self):
        record = _safe_probe_record(
            {
                "ok": False,
                "exit_code": 1,
                "argv": ["tool", "--token=abc123", "api_key=supersecret"],
                "output": "password=hunter2 Bearer deadbeef api_key=abc123",
            }
        )
        rendered = json.dumps(record)
        for secret in ("hunter2", "deadbeef", "abc123", "supersecret"):
            self.assertNotIn(secret, rendered)
        self.assertIn("<REDACTED>", rendered)

    def test_cli_stack_doctor_json_reports_all_missing_tools_without_mutation(self):
        calls: list[tuple[list[str], int]] = []

        def runner(argv: list[str], timeout_seconds: int = 30) -> dict:
            calls.append((argv, timeout_seconds))
            return {"ok": False, "exit_code": 1, "output": "should not run"}

        with tempfile.TemporaryDirectory() as temp:
            deterministic = stack_doctor(which=lambda _name: None, runner=runner, home=Path(temp))
            stdout = io.StringIO()
            with patch("manageroo.cli.stack_doctor", return_value=deterministic):
                with redirect_stdout(stdout):
                    code = main(["stack-doctor", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["executes_changes"])
        self.assertEqual(calls, [])
        by_name = {item["name"]: item for item in payload["items"]}
        for name in ("gbrain", "gitnexus", "autoreview", "clawpatch", "obsidian", "codex"):
            with self.subTest(name=name):
                self.assertFalse(by_name[name]["installed"])
                self.assertEqual(by_name[name]["status"], "missing")

    def test_autoreview_requires_a_runnable_regular_script(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            script = home / ".agents" / "skills" / "autoreview" / "scripts" / "autoreview"
            script.mkdir(parents=True)
            report = stack_doctor(which=lambda _name: None, runner=lambda _argv, _timeout: {}, home=home)
            autoreview = next(item for item in report["items"] if item["name"] == "autoreview")
            self.assertFalse(autoreview["configured"])
            self.assertEqual(autoreview["status"], "missing")

            script.rmdir()
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            if os.name != "nt":
                script.chmod(0o644)
                report = stack_doctor(which=lambda _name: None, runner=lambda _argv, _timeout: {}, home=home)
                autoreview = next(item for item in report["items"] if item["name"] == "autoreview")
                self.assertFalse(autoreview["configured"])
                script.chmod(0o755)

            report = stack_doctor(which=lambda _name: None, runner=lambda _argv, _timeout: {}, home=home)
            autoreview = next(item for item in report["items"] if item["name"] == "autoreview")
            self.assertTrue(autoreview["configured"])
            self.assertEqual(autoreview["status"], "ok")

    def test_codex_login_probe_is_shared_with_clawpatch_dependency_status(self):
        calls: dict[tuple[str, ...], int] = {}

        def which(name: str) -> str | None:
            if name in {"codex", "clawpatch"}:
                return f"/usr/bin/{name}"
            return None

        def runner(argv: list[str], timeout_seconds: int = 30) -> dict:
            key = tuple(Path(argv[0]).name if index == 0 else value for index, value in enumerate(argv))
            calls[key] = calls.get(key, 0) + 1
            if key == ("codex", "login", "status"):
                return {"ok": True, "exit_code": 0, "output": "logged in"}
            if key == ("clawpatch", "doctor"):
                return {"ok": True, "exit_code": 0, "output": "healthy"}
            return {"ok": False, "exit_code": 1, "output": "unexpected"}

        with tempfile.TemporaryDirectory() as temp:
            report = stack_doctor(which=which, runner=runner, home=Path(temp))

        self.assertEqual(calls.get(("codex", "login", "status")), 1)
        codex = next(item for item in report["items"] if item["name"] == "codex")
        clawpatch = next(item for item in report["items"] if item["name"] == "clawpatch")
        self.assertTrue(codex["configured"])
        self.assertTrue(clawpatch["configured"])
        self.assertTrue(clawpatch["probes"]["codex_provider"]["configured"])

    def test_format_stack_doctor_is_plain_and_actionable(self):
        text = format_stack_doctor(
            {
                "ok": True,
                "ready": False,
                "executes_changes": False,
                "items": [
                    {
                        "name": "gitnexus",
                        "status": "needs_action",
                        "installed": True,
                        "configured": False,
                        "detail": "installed; setup verification still needed",
                        "next_commands": ["gitnexus setup"],
                    }
                ],
            }
        )
        self.assertIn("SMART STACK DOCTOR", text)
        self.assertIn("read-only", text)
        self.assertIn("ACTION gitnexus", text)
        self.assertIn("gitnexus setup", text)

    def test_gitnexus_installed_is_warning_not_permanent_required_failure(self):
        def which(name: str) -> str | None:
            return "/usr/bin/gitnexus" if name == "gitnexus" else None

        def runner(argv: list[str], timeout_seconds: int = 30) -> dict:
            if Path(argv[0]).name == "gitnexus" and argv[1:] == ["--version"]:
                return {"ok": True, "exit_code": 0, "output": "gitnexus 1.6.9"}
            return {"ok": False, "exit_code": 1, "output": "unexpected"}

        with tempfile.TemporaryDirectory() as temp:
            report = stack_doctor(which=which, runner=runner, home=Path(temp))

        gitnexus = next(item for item in report["items"] if item["name"] == "gitnexus")
        self.assertTrue(gitnexus["installed"])
        self.assertIn(gitnexus["status"], {"ok", "warning"})
        self.assertTrue(gitnexus["configured"])
        self.assertNotEqual(gitnexus["status"], "needs_action")


if __name__ == "__main__":
    unittest.main()
