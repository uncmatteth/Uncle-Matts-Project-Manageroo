import unittest
from unittest.mock import patch

from manageroo.stack_update import format_stack_update, stack_update_plan


class StackUpdateTests(unittest.TestCase):
    def test_plan_is_dry_run_and_uses_current_supported_update_paths(self):
        def which(name: str):
            return {
                "gbrain": "/usr/bin/gbrain",
                "npm": "/usr/bin/npm",
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
        self.assertIn(["/usr/bin/gbrain", "doctor", "--json"], tools["gbrain"]["commands"])
        self.assertIn(
            ["/usr/bin/npm", "install", "-g", "gitnexus@latest"],
            tools["gitnexus"]["commands"],
        )
        self.assertIn(
            ["/usr/bin/pnpm", "add", "-g", "clawpatch@latest"],
            tools["clawpatch"]["commands"],
        )

    def test_absent_gitnexus_is_not_treated_as_an_installed_tool(self):
        with patch("manageroo.stack_update.shutil.which", return_value=None):
            plan = stack_update_plan()

        gitnexus = next(item for item in plan["tools"] if item["name"] == "gitnexus")
        self.assertFalse(gitnexus["installed"])
        self.assertEqual(gitnexus["commands"], [])
        self.assertIn("will not install one implicitly", gitnexus["note"])

    def test_plan_can_target_one_tool(self):
        def which(name: str):
            return {
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
            }.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which):
            plan = stack_update_plan(["gitnexus"])

        self.assertEqual(plan["selected_tools"], ["gitnexus"])
        self.assertEqual([item["name"] for item in plan["tools"]], ["gitnexus"])

    def test_plain_output_makes_apply_boundary_explicit(self):
        text = format_stack_update(stack_update_plan())
        self.assertIn("No changes were made", text)
        self.assertIn("--apply", text)


if __name__ == "__main__":
    unittest.main()
