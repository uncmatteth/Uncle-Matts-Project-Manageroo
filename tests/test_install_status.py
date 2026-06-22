import tempfile
import unittest
from pathlib import Path

from manageroo.install_status import (
    format_stack_status,
    summarize_external_tools,
    uninstall_plan,
)


class InstallStatusTests(unittest.TestCase):
    def test_stack_summary_keeps_next_commands_for_skipped_tools(self):
        summary = summarize_external_tools(
            [
                {"name": "gbrain", "installed": True, "configured": True},
                {
                    "name": "gitnexus",
                    "skipped": True,
                    "reason": "npm missing",
                    "next_commands": ["Install Node.js", "npm install -g gitnexus"],
                },
            ]
        )
        self.assertEqual(summary["counts"]["installed"], 1)
        self.assertEqual(summary["counts"]["skipped"], 1)
        self.assertTrue(summary["items"][1]["needs_action"])
        self.assertIn("npm install -g gitnexus", summary["items"][1]["next_commands"])

    def test_stack_summary_surfaces_guidance_commands(self):
        summary = summarize_external_tools(
            [
                {
                    "name": "gbrain",
                    "installed": True,
                    "configured": True,
                    "guidance_commands": ["Connect `gbrain serve` to the selected agent."],
                },
            ]
        )
        self.assertEqual(summary["counts"]["needs_action"], 1)
        self.assertTrue(summary["items"][0]["needs_action"])
        self.assertIn("gbrain serve", summary["items"][0]["next_commands"][0])

    def test_format_stack_status_is_plain_and_actionable(self):
        text = format_stack_status(
            {
                "ok": True,
                "lock_path": "/tmp/install-lock.json",
                "launcher": "/tmp/bin/manageroo",
                "stack_summary": {
                    "items": [
                        {
                            "name": "loop-library",
                            "installed": False,
                            "needs_action": True,
                            "reason": "No agent selected",
                            "next_commands": ["npx --yes skills add Forward-Future/loop-library"],
                        }
                    ]
                },
            }
        )
        self.assertIn("ACTION loop-library", text)
        self.assertIn("No agent selected", text)
        self.assertIn("npx --yes", text)

    def test_uninstall_plan_does_not_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            plan = uninstall_plan(prefix=prefix, bin_dir=Path(temp) / "bin")
            self.assertFalse(plan["executes_deletions"])
            self.assertIn(str(prefix), plan["core_paths"])


if __name__ == "__main__":
    unittest.main()
