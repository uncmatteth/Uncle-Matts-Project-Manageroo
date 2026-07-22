import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.stack_update import (
    AUTOREVIEW_COMMIT,
    CLAWPATCH_PACKAGE,
    GITNEXUS_PACKAGE,
    _replace_autoreview,
    apply_stack_updates,
    format_stack_update,
    stack_update_plan,
)


class StackUpdateTests(unittest.TestCase):
    @staticmethod
    def owned_run(argv, **_kwargs):
        if argv[1:] == ["prefix", "-g"]:
            return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr\n"}
        if argv[1:] == ["bin", "-g"]:
            return {"ok": True, "exit_code": 0, "argv": argv, "output": "/usr/bin\n"}
        return {"ok": False, "exit_code": 1, "argv": argv, "output": "not installed"}

    def test_plan_is_dry_run_and_uses_release_pinned_update_paths(self):
        def which(name: str):
            return {
                "gbrain": "/usr/bin/gbrain",
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "obsidian": "/usr/bin/obsidian",
            }.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update.platform.system", return_value="Linux"
        ), patch("manageroo.stack_update._run", side_effect=self.owned_run):
            plan = stack_update_plan()

        self.assertTrue(plan["ok"])
        self.assertFalse(plan["executes_changes"])
        tools = {item["name"]: item for item in plan["tools"]}
        self.assertNotIn(["/usr/bin/gbrain", "upgrade"], tools["gbrain"]["commands"])
        self.assertEqual(tools["gbrain"]["commands"], [["/usr/bin/gbrain", "doctor", "--json"]])
        self.assertIn(["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE], tools["gitnexus"]["commands"])
        self.assertIn(["/usr/bin/pnpm", "add", "-g", CLAWPATCH_PACKAGE], tools["clawpatch"]["commands"])
        self.assertNotIn("@latest", repr(plan))

    def test_absent_gitnexus_is_not_treated_as_an_installed_tool(self):
        with patch("manageroo.stack_update.shutil.which", return_value=None):
            plan = stack_update_plan()
        gitnexus = next(item for item in plan["tools"] if item["name"] == "gitnexus")
        self.assertFalse(gitnexus["installed"])
        self.assertEqual(gitnexus["commands"], [])
        self.assertIn("will not install one implicitly", gitnexus["note"])

    def test_plan_can_target_one_tool(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "gitnexus": "/usr/bin/gitnexus"}.get(name)
        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=self.owned_run
        ):
            plan = stack_update_plan(["gitnexus"])
        self.assertEqual(plan["selected_tools"], ["gitnexus"])
        self.assertEqual([item["name"] for item in plan["tools"]], ["gitnexus"])

    def test_apply_one_tool_executes_no_unselected_tool_commands(self):
        calls: list[list[str]] = []

        def which(name: str):
            return {
                "npm": "/usr/bin/npm",
                "gitnexus": "/usr/bin/gitnexus",
                "pnpm": "/usr/bin/pnpm",
                "clawpatch": "/usr/bin/clawpatch",
                "gbrain": "/usr/bin/gbrain",
            }.get(name)

        def run(argv, **_kwargs):
            if argv[1:] == ["prefix", "-g"]:
                return {"ok": True, "exit_code": 0, "argv": list(argv), "output": "/usr\n"}
            calls.append(list(argv))
            return {"ok": True, "exit_code": 0, "argv": list(argv), "output": ""}

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=run
        ):
            result = apply_stack_updates(["gitnexus"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_tools"], ["gitnexus"])
        self.assertEqual(calls, [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])

    def test_codex_only_autoreview_is_updated_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            codex_target = home / ".codex" / "skills" / "autoreview"
            codex_target.mkdir(parents=True)
            (codex_target / "SKILL.md").write_text("old\n", encoding="utf-8")

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    checkout = Path(kwargs["cwd"])
                    skill = checkout / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": AUTOREVIEW_COMMIT + "\n"}
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            def which(name: str):
                return "/usr/bin/git" if name == "git" else None

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", side_effect=which
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertTrue(result["ok"])
            self.assertEqual((codex_target / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertFalse((home / ".agents" / "skills" / "autoreview").exists())

    def test_symlinked_autoreview_alias_is_preserved_and_resolved_target_updated_once(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "autoreview"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n", encoding="utf-8")
            alias = home / ".agents" / "skills" / "autoreview"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(target, target_is_directory=True)
            replacements = []

            def fake_update(destinations):
                resolved = [Path(path).resolve() for path in destinations]
                replacements.extend(resolved)
                return {"ok": True, "name": "autoreview", "installations": []}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update._update_autoreview", side_effect=fake_update
            ):
                result = apply_stack_updates(["autoreview"])
            self.assertTrue(result["ok"])
            self.assertTrue(alias.is_symlink())
            self.assertEqual(replacements, [target.resolve()])

    def test_autoreview_failed_swap_restores_original_and_preserves_old_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n", encoding="utf-8")
            destination = root / "autoreview"
            destination.mkdir()
            (destination / "SKILL.md").write_text("old\n", encoding="utf-8")
            prior_backup = root / "autoreview.manageroo-backup-prior"
            prior_backup.mkdir()
            (prior_backup / "SKILL.md").write_text("older\n", encoding="utf-8")

            original_rename = Path.rename

            def fail_stage_rename(path, target):
                if ".manageroo-stage" in path.name:
                    raise OSError("simulated swap failure")
                return original_rename(path, target)

            with patch.object(Path, "rename", autospec=True, side_effect=fail_stage_rename):
                result = _replace_autoreview(source, destination)

            self.assertFalse(result["ok"])
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "old\n")
            self.assertEqual((prior_backup / "SKILL.md").read_text(encoding="utf-8"), "older\n")

    def test_plain_output_makes_apply_boundary_explicit(self):
        text = format_stack_update(stack_update_plan())
        self.assertIn("No changes were made", text)
        self.assertIn("--apply", text)


if __name__ == "__main__":
    unittest.main()
