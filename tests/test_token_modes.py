import os
import tempfile
import unittest
from pathlib import Path

from manageroo.token_modes import (
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
            self.assertIn("brain-ops", installed)
            self.assertIn("query", installed)
            self.assertIn("ingest", installed)
            self.assertIn("idea-ingest", installed)
            self.assertIn("media-ingest", installed)
            self.assertIn("voice-note-ingest", installed)
            self.assertIn("article-enrichment", installed)
            self.assertIn("book-mirror", installed)
            self.assertIn("strategic-reading", installed)
            self.assertIn("pdf", installed)
            self.assertIn("brain-pdf", installed)
            self.assertIn("citation-fixer", installed)
            self.assertIn("reports", installed)
            self.assertIn("exact-text-replacement", installed)
            self.assertIn("edit-skill", installed)
            self.assertIn("write-a-skill", installed)
            self.assertIn("skillify", installed)
            self.assertIn("diagnose", installed)
            self.assertIn("tdd", installed)
            self.assertIn("autoreview", installed)
            self.assertIn("plain-web-copy", installed)
            self.assertIn("fix-my-bad-website", installed)
            self.assertIn("caveman", installed)
            self.assertIn("uncle-matts-caveman-curse", installed)
            self.assertIn(
                "uncle-matts-project-manageroo",
                installed,
            )
            prompt = Path(temp) / "pimp-my-prompt" / "SKILL.md"
            brain_ops = Path(temp) / "brain-ops" / "SKILL.md"
            query = Path(temp) / "query" / "SKILL.md"
            media_ingest = Path(temp) / "media-ingest" / "SKILL.md"
            book_mirror = Path(temp) / "book-mirror" / "SKILL.md"
            brain_pdf = Path(temp) / "brain-pdf" / "SKILL.md"
            exact_text = Path(temp) / "exact-text-replacement" / "SKILL.md"
            editor = Path(temp) / "edit-skill" / "SKILL.md"
            writer = Path(temp) / "write-a-skill" / "SKILL.md"
            skillify = Path(temp) / "skillify" / "SKILL.md"
            diagnose = Path(temp) / "diagnose" / "SKILL.md"
            tdd = Path(temp) / "tdd" / "SKILL.md"
            autoreview = Path(temp) / "autoreview" / "SKILL.md"
            plain_web_copy = Path(temp) / "plain-web-copy" / "SKILL.md"
            fix_website = Path(temp) / "fix-my-bad-website" / "SKILL.md"
            controller = (
                Path(temp)
                / "uncle-matts-project-manageroo"
                / "SKILL.md"
            )
            self.assertTrue(prompt.exists())
            self.assertTrue(brain_ops.exists())
            self.assertTrue(query.exists())
            self.assertTrue(media_ingest.exists())
            self.assertTrue(book_mirror.exists())
            self.assertTrue(brain_pdf.exists())
            self.assertTrue(exact_text.exists())
            self.assertTrue(editor.exists())
            self.assertTrue(writer.exists())
            self.assertTrue(skillify.exists())
            self.assertTrue(diagnose.exists())
            self.assertTrue(tdd.exists())
            self.assertTrue(autoreview.exists())
            self.assertTrue(plain_web_copy.exists())
            self.assertTrue(fix_website.exists())
            self.assertTrue((Path(temp) / "caveman" / "SKILL.md").exists())
            self.assertTrue((Path(temp) / "uncle-matts-caveman-curse" / "SKILL.md").exists())
            self.assertTrue(controller.exists())
            self.assertIn("rough-draft users", prompt.read_text(encoding="utf-8"))
            self.assertIn("Brain Ops", brain_ops.read_text(encoding="utf-8"))
            self.assertIn("# Query", query.read_text(encoding="utf-8"))
            self.assertIn("Media Ingest", media_ingest.read_text(encoding="utf-8"))
            self.assertIn("Book Mirror", book_mirror.read_text(encoding="utf-8"))
            self.assertIn("Brain PDF", brain_pdf.read_text(encoding="utf-8"))
            self.assertIn("Exact Text Replacement", exact_text.read_text(encoding="utf-8"))
            self.assertIn("duplicate instructions", editor.read_text(encoding="utf-8"))
            self.assertIn("Create a new local agent skill", writer.read_text(encoding="utf-8"))
            self.assertIn("Skillify only when", skillify.read_text(encoding="utf-8"))
            self.assertIn("Build a feedback loop first", diagnose.read_text(encoding="utf-8"))
            self.assertIn("one behavior test", tdd.read_text(encoding="utf-8"))
            self.assertIn("closeout code review", autoreview.read_text(encoding="utf-8"))
            self.assertIn("truth before tone", plain_web_copy.read_text(encoding="utf-8"))
            self.assertIn("not generic AI output", fix_website.read_text(encoding="utf-8"))
            self.assertIn("Do not make the user remember skill names", controller.read_text(encoding="utf-8"))

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


if __name__ == "__main__":
    unittest.main()
