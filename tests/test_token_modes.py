import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.token_modes import (
    install_token_skills,
    read_token_mode,
    set_token_mode,
    token_mode_prompt,
)


class TokenModeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
