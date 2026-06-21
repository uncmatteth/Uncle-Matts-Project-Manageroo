import os
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.token_modes import (
    install_core_helper_skills,
    install_token_skills,
    read_token_mode,
    set_token_mode,
    token_mode_prompt,
)


class TokenModeTests(unittest.TestCase):
    def test_installs_core_helper_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = install_core_helper_skills(Path(temp))
            self.assertIn("pimp-my-prompt", installed)
            self.assertIn("edit-skill", installed)
            prompt = Path(temp) / "pimp-my-prompt" / "SKILL.md"
            editor = Path(temp) / "edit-skill" / "SKILL.md"
            self.assertTrue(prompt.exists())
            self.assertTrue(editor.exists())
            self.assertIn("rough-draft users", prompt.read_text(encoding="utf-8"))
            self.assertIn("duplicate instructions", editor.read_text(encoding="utf-8"))

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
            self.assertTrue((skills / "caveman" / "SKILL.md").exists())
            self.assertTrue((skills / "uncle-matts-caveman-curse" / "SKILL.md").exists())

    def test_existing_user_skill_is_backed_up_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp)
            target = skills / "caveman" / "SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text("custom local caveman skill\n", encoding="utf-8")
            install_token_skills(skills)
            backups = list(target.parent.glob("SKILL.md.umsmfburasbofe-backup-*"))
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
            backups = list(target.parent.glob("SKILL.md.umsmfburasbofe-backup-*"))
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


if __name__ == "__main__":
    unittest.main()
