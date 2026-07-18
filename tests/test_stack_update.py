import unittest
from unittest.mock import patch

from manageroo.stack_update import format_stack_update, stack_update_plan


class StackUpdateTests(unittest.TestCase):
    def test_plan_is_dry_run_and_uses_current_upstream_update_paths(self):
        def which(name: str):
            return {
                "gbrain": "/usr/bin/gbrain",
                "npm": "/usr/bin/npm",
                "npx": "/usr/bin/npx",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "obsidian": "/usr/bin/obsidian",
            }.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which):
            with patch("manageroo.stack_update.platform.system", return_value="Linux"):
                plan = stack_update_plan()

        self.assertTrue(plan["ok"])
        self.assertFalse(plan["executes_changes"])
        tools = {item["name"]: item for item in plan["tools"]}
        self.assertIn(["/usr/bin/gbrain", "upgrade"], tools["gbrain"]["commands"])
        self.assertIn(
            ["/usr/bin/npm", "install", "-g", "gitnexus@latest"],
            tools["gitnexus"]["commands"],
        )
        self.assertIn(
            ["/usr/bin/pnpm", "add", "-g", "clawpatch@latest"],
            tools["clawpatch"]["commands"],
        )

    def test_plan_explains_npx_gitnexus_when_no_global_binary_exists(self):
        def which(name: str):
            return "/usr/bin/npx" if name == "npx" else None

        with patch("manageroo.stack_update.shutil.which", side_effect=which):
            plan = stack_update_plan()

        gitnexus = next(item for item in plan["tools"] if item["name"] == "gitnexus")
        self.assertTrue(gitnexus["installed"])
        self.assertEqual(gitnexus["commands"], [])
        self.assertIn("npx gitnexus analyze/setup", gitnexus["note"])

    def test_plain_output_makes_apply_boundary_explicit(self):
        text = format_stack_update(stack_update_plan())
        self.assertIn("No changes were made", text)
        self.assertIn("--apply", text)


if __name__ == "__main__":
    unittest.main()
