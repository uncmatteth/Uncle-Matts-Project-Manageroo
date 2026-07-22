import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.token_modes import (
    CORE_HELPER_SKILLS,
    _copy_skill_tree,
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

    def test_existing_user_skill_is_backed_up_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp)
            target = skills / "caveman" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("custom local caveman skill\n", encoding="utf-8")
            install_token_skills(skills)
            backups = list(target.parent.glob("SKILL.md.manageroo-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "custom local caveman skill\n")
            self.assertIn("Ultra-compressed communication mode", target.read_text(encoding="utf-8"))

    def test_existing_user_helper_skill_is_backed_up_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp)
            target = skills / "pimp-my-prompt" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("custom prompt skill\n", encoding="utf-8")
            install_core_helper_skills(skills)
            backups = list(target.parent.glob("SKILL.md.manageroo-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "custom prompt skill\n")
            self.assertIn("Pimp My Prompt", target.read_text(encoding="utf-8"))

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