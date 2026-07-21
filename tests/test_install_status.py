import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.install_status import (
    format_stack_status,
    read_install_lock,
    stack_status,
    summarize_external_tools,
    uninstall_plan,
)


class InstallStatusTests(unittest.TestCase):
    def test_stack_summary_keeps_next_commands_for_skipped_tools(self):
        summary = summarize_external_tools([
            {"name": "gbrain", "installed": True, "configured": True},
            {"name": "gitnexus", "skipped": True, "reason": "npm missing", "next_commands": ["Install Node.js", "npm install -g gitnexus"]},
        ])
        self.assertEqual(summary["counts"]["installed"], 1)
        self.assertEqual(summary["counts"]["skipped"], 1)
        self.assertTrue(summary["items"][1]["needs_action"])
        self.assertIn("npm install -g gitnexus", summary["items"][1]["next_commands"])

    def test_stack_summary_surfaces_guidance_commands(self):
        summary = summarize_external_tools([{"name": "gbrain", "installed": True, "configured": True, "guidance_commands": ["Connect `gbrain serve` to the selected agent."]}])
        self.assertEqual(summary["counts"]["needs_action"], 1)
        self.assertTrue(summary["items"][0]["needs_action"])
        self.assertIn("gbrain serve", summary["items"][0]["next_commands"][0])

    def test_format_stack_status_is_plain_and_actionable(self):
        text = format_stack_status({
            "ok": True,
            "lock_path": "/tmp/install-lock.json",
            "launcher": "/tmp/bin/manageroo",
            "stack_summary": {"items": [{"name": "obsidian", "installed": False, "needs_action": True, "reason": "No package manager available", "next_commands": ["Install Obsidian from https://obsidian.md/download"]}]},
        })
        self.assertIn("ACTION obsidian", text)
        self.assertIn("No package manager available", text)
        self.assertIn("obsidian.md", text)

    def test_malformed_lock_shapes_return_actionable_status_instead_of_crashing(self):
        payloads = [
            {"external_tools": None}, {"external_tools": {}}, {"external_tools": [None]},
            {"external_tools": [{"name": "x", "next_commands": None}]},
            {"external_tools": [{"name": "x", "guidance_commands": None}]},
            {"external_tools": [], "stack_summary": {"items": None}},
        ]
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    lock.write_text(json.dumps(payload), encoding="utf-8")
                    loaded = read_install_lock(lock)
                    self.assertFalse(loaded["ok"])
                    report = stack_status(lock)
                    self.assertFalse(report["ok"])
                    rendered = format_stack_status(report)
                    self.assertIn("NOT READY", rendered)
                    self.assertIn("install-lock.json", rendered)
                    self.assertIn("next:", rendered)

    def test_live_probe_overrides_stale_cached_installed_status(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            lock.write_text(json.dumps({
                "launcher": "/tmp/bin/manageroo",
                "external_tools": [{"name": "codex", "installed": True, "configured": True}],
                "stack_summary": {"items": [{"name": "codex", "installed": True, "configured": True, "skipped": False, "needs_action": False, "next_commands": []}]},
            }), encoding="utf-8")
            with patch("manageroo.install_status.shutil.which", return_value=None), patch("manageroo.install_status._find_skill", return_value=None):
                report = stack_status(lock)
            self.assertTrue(report["ok"])
            item = report["stack_summary"]["items"][0]
            self.assertFalse(item["installed"])
            self.assertTrue(item["needs_action"])
            self.assertIn("ACTION codex", format_stack_status(report))

    def test_uninstall_plan_uses_recorded_custom_launcher_not_default_bin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            custom_launcher = root / "custom" / "manageroo"
            unrelated_default = Path.home() / ".local" / "bin" / "manageroo"
            prefix.mkdir()
            custom_launcher.parent.mkdir()
            custom_launcher.write_text('#!/bin/sh\nexport MANAGEROO_PREFIX="/tmp/manageroo"\nexec python3 -m manageroo "$@"\n', encoding="utf-8")
            (prefix / "install-lock.json").write_text(json.dumps({"launcher": str(custom_launcher), "external_tools": []}), encoding="utf-8")
            plan = uninstall_plan(prefix=prefix)
            self.assertFalse(plan["executes_deletions"])
            self.assertIn(str(custom_launcher), plan["core_paths"])
            self.assertNotIn(str(unrelated_default), plan["core_paths"])
            self.assertTrue(plan["launcher_ownership_known"])

    def test_uninstall_plan_does_not_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            plan = uninstall_plan(prefix=prefix, bin_dir=Path(temp) / "bin")
            self.assertFalse(plan["executes_deletions"])
            self.assertIn(str(prefix), plan["core_paths"])


if __name__ == "__main__":
    unittest.main()
