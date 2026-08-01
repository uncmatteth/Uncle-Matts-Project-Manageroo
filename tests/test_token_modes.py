import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.token_modes import (
    CORE_HELPER_SKILLS,
    _copy_skill_tree,
    _skill_tree_sha256,
    install_core_helper_skills,
    install_token_skills,
    read_token_mode,
    set_token_mode,
    token_mode_prompt,
)


class TokenModeTests(unittest.TestCase):
    def test_public_token_mode_apis_import_and_core_is_18_skills(self):
        self.assertEqual(len(CORE_HELPER_SKILLS), 18)
        self.assertIn("skill-vetter", CORE_HELPER_SKILLS)
        self.assertIn("uncle-matts-project-manageroo", CORE_HELPER_SKILLS)

    def test_installs_portable_core_helper_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            installed = install_core_helper_skills(root)
            self.assertEqual(set(installed), set(CORE_HELPER_SKILLS))
            self.assertEqual(len(installed), 18)
            for name in CORE_HELPER_SKILLS:
                self.assertTrue((root / name / "SKILL.md").is_file(), name)
            self.assertFalse((root / "brain-ops" / "SKILL.md").exists())
            self.assertFalse((root / "autoreview" / "SKILL.md").exists())
            controller = (root / "uncle-matts-project-manageroo" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Do not load the whole pack for every job", controller)
            self.assertIn("Route only to relevant helpers", controller)
            self.assertIn("use-installed-skills-first", controller)

    def test_installs_bundled_caveman_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = install_token_skills(Path(temp))
            self.assertIn("caveman", installed)
            self.assertIn("curse", installed)
            self.assertTrue((Path(temp) / "caveman" / "SKILL.md").exists())
            curse = Path(temp) / "uncle-matts-caveman-curse" / "SKILL.md"
            self.assertTrue(curse.exists())
            self.assertIn("69% MORE PROFANITY", curse.read_text(encoding="utf-8"))

    def test_set_and_read_token_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "token-mode.json"
            skills = Path(temp) / "skills"
            result = set_token_mode("curse", state_path=state, skills_dir=skills)
            self.assertEqual(result["mode"], "curse")
            self.assertEqual(read_token_mode(state)["mode"], "curse")
            self.assertIn("Uncle Matt's Caveman Curse", token_mode_prompt("curse"))
            self.assertIn("appropriately placed, well-used profanity", token_mode_prompt("curse"))
            self.assertTrue((skills / "caveman" / "SKILL.md").exists())
            self.assertTrue((skills / "uncle-matts-caveman-curse" / "SKILL.md").exists())

    def test_failed_atomic_token_mode_write_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "token-mode.json"
            set_token_mode("off", state_path=state, install_skills=False)
            before = state.read_bytes()
            with patch("manageroo.token_modes.atomic_write_json", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    set_token_mode("curse", state_path=state, install_skills=False)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(read_token_mode(state)["mode"], "off")

    def test_existing_user_skill_is_reused_without_backup_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp)
            target = skills / "caveman" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("custom local caveman skill\n", encoding="utf-8")
            installed = install_token_skills(skills)
            backups = list(target.parent.glob("SKILL.md.manageroo-backup-*"))
            self.assertEqual(backups, [])
            self.assertEqual(target.read_text(encoding="utf-8"), "custom local caveman skill\n")
            self.assertEqual(installed["caveman"], str(target))

    def test_existing_user_helper_skill_is_reused_without_backup_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp)
            target = skills / "pimp-my-prompt" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("custom prompt skill\n", encoding="utf-8")
            installed = install_core_helper_skills(skills)
            backups = list(target.parent.glob("SKILL.md.manageroo-backup-*"))
            self.assertEqual(backups, [])
            self.assertEqual(target.read_text(encoding="utf-8"), "custom prompt skill\n")
            self.assertEqual(installed["pimp-my-prompt"], str(target))

    def test_existing_skill_in_another_agent_root_is_reused_without_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target_root = base / ".agents" / "skills"
            existing_root = base / ".codex" / "skills"
            existing = existing_root / "diagnose" / "SKILL.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing diagnose skill\n", encoding="utf-8")

            installed = install_core_helper_skills(
                target_root,
                search_roots=[existing_root],
                ownership_path=base / "ownership.json",
            )

            self.assertEqual(installed["diagnose"], str(existing))
            self.assertFalse((target_root / "diagnose").exists())

    def test_user_edit_to_manageroo_installed_skill_is_preserved_on_reinstall(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"
            install_core_helper_skills(skills, ownership_path=ownership)
            target = skills / "diagnose" / "SKILL.md"
            target.write_text("user customized diagnose\n", encoding="utf-8")

            install_core_helper_skills(skills, ownership_path=ownership)

            self.assertEqual(target.read_text(encoding="utf-8"), "user customized diagnose\n")
            self.assertEqual(list(target.parent.glob("*.manageroo-backup-*")), [])

    def test_preledger_manageroo_skill_is_migrated_into_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"
            install_core_helper_skills(skills, ownership_path=ownership)
            ownership.unlink()

            install_core_helper_skills(skills, ownership_path=ownership)

            payload = json.loads(ownership.read_text(encoding="utf-8"))
            diagnose_key = str((skills / "diagnose").resolve())
            self.assertIn(diagnose_key, payload["skills"])

    def test_midpack_failure_rolls_back_all_new_skill_trees(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"
            from manageroo import token_modes

            original = token_modes._install_bundled_skill
            calls = 0

            def fail_third(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected mid-pack failure")
                return original(*args, **kwargs)

            with patch("manageroo.token_modes._install_bundled_skill", side_effect=fail_third):
                with self.assertRaisesRegex(OSError, "mid-pack"):
                    install_core_helper_skills(skills, ownership_path=ownership)

            self.assertEqual(
                [path for path in skills.iterdir() if path.is_dir()],
                [],
            )
            self.assertFalse(ownership.exists())

    def test_midpack_rollback_preserves_concurrently_replaced_skill_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"
            from manageroo import token_modes

            original = token_modes._install_bundled_skill
            calls = 0
            first_name = next(iter(CORE_HELPER_SKILLS))

            def replace_then_fail(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    first = skills / first_name
                    if first.exists():
                        import shutil

                        shutil.rmtree(first)
                    first.mkdir(parents=True)
                    (first / "SKILL.md").write_text("user-created concurrently\n", encoding="utf-8")
                if calls == 3:
                    raise OSError("injected mid-pack failure")
                return original(*args, **kwargs)

            with patch("manageroo.token_modes._install_bundled_skill", side_effect=replace_then_fail):
                with self.assertRaisesRegex(OSError, "mid-pack"):
                    install_core_helper_skills(skills, ownership_path=ownership)

            self.assertEqual(
                (skills / first_name / "SKILL.md").read_text(encoding="utf-8"),
                "user-created concurrently\n",
            )

    def test_cross_root_reuse_ignores_symlinked_or_unsafe_skill_tree(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target_root = base / "target"
            search_root = base / "search"
            outside = base / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("unsafe external copy\n", encoding="utf-8")
            search_root.mkdir()
            (search_root / "diagnose").symlink_to(outside, target_is_directory=True)

            installed = install_core_helper_skills(
                target_root,
                search_roots=[search_root],
                ownership_path=base / "ownership.json",
            )

            self.assertEqual(Path(installed["diagnose"]), target_root / "diagnose" / "SKILL.md")
            self.assertFalse((target_root / "diagnose").is_symlink())

    def test_skill_tree_digest_includes_directory_structure_and_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skill"
            root.mkdir()
            (root / "SKILL.md").write_text("same bytes\n", encoding="utf-8")
            before = _skill_tree_sha256(root)
            (root / "empty-support-directory").mkdir()
            after = _skill_tree_sha256(root)
            self.assertNotEqual(before, after)

    def test_ownership_write_failure_rolls_back_all_new_skill_trees(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"

            with patch("manageroo.token_modes.atomic_write_json", side_effect=OSError("ledger full")):
                with self.assertRaisesRegex(OSError, "ledger full"):
                    install_core_helper_skills(skills, ownership_path=ownership)

            self.assertEqual(
                [path for path in skills.iterdir() if path.is_dir()],
                [],
            )
            self.assertFalse(ownership.exists())

    def test_oversized_existing_skill_tree_is_bounded_before_install(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            target = skills / "diagnose"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("custom diagnose\n", encoding="utf-8")
            for index in range(130):
                (target / f"file-{index}.txt").write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "ownership file limit"):
                install_core_helper_skills(
                    skills,
                    ownership_path=base / "ownership.json",
                )

            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "custom diagnose\n")

    def test_refuses_to_overwrite_symlinked_skill_file(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / "skills"
            outside = Path(temp) / "outside.md"
            outside.write_text("do not overwrite\n", encoding="utf-8")
            target = skills / "pimp-my-prompt" / "SKILL.md"
            target.parent.mkdir(parents=True)
            os.symlink(outside, target)
            with self.assertRaises(ValueError):
                install_core_helper_skills(skills)
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_refuses_symlinked_skill_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            skills.mkdir()
            outside = base / "outside-skill"
            outside.mkdir()
            marker = outside / "SKILL.md"
            marker.write_text("do not overwrite\n", encoding="utf-8")
            os.symlink(outside, skills / "pimp-my-prompt")
            with self.assertRaises(ValueError):
                install_core_helper_skills(skills)
            self.assertEqual(marker.read_text(encoding="utf-8"), "do not overwrite\n")
            self.assertEqual(sorted(path.name for path in outside.iterdir()), ["SKILL.md"])

    def test_refuses_symlinked_skills_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            outside = base / "outside"
            outside.mkdir()
            linked = base / "skills"
            os.symlink(outside, linked)
            with self.assertRaises(ValueError):
                install_core_helper_skills(linked)
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "symlink setup is platform-dependent on Windows")
    def test_refuses_symlinked_intermediate_directory_in_skill_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            (source / "references").mkdir(parents=True)
            (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (source / "references" / "guide.md").write_text("guide\n", encoding="utf-8")

            skills_root = base / "skills"
            target = skills_root / "sample"
            target.mkdir(parents=True)
            outside = base / "outside"
            outside.mkdir()
            (target / "references").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                _copy_skill_tree(source, target, root_real=skills_root.resolve())
            self.assertFalse((outside / "guide.md").exists())


if __name__ == "__main__":
    unittest.main()
