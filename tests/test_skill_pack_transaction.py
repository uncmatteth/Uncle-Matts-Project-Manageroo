import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.skill_pack import import_skill_folder


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


class SkillPackTransactionTests(unittest.TestCase):
    def test_failed_multifile_import_preserves_active_destination_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "source"
            source_skill = source_root / "demo-skill"
            source_skill.mkdir(parents=True)
            (source_skill / "SKILL.md").write_text("---\nname: demo-skill\n---\nnew skill\n", encoding="utf-8")
            (source_skill / "one.txt").write_text("new one\n", encoding="utf-8")
            (source_skill / "two.txt").write_text("new two\n", encoding="utf-8")

            skills = root / "skills"
            target = skills / "demo-skill"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("---\nname: demo-skill\n---\nold skill\n", encoding="utf-8")
            (target / "one.txt").write_text("old one\n", encoding="utf-8")
            (target / "keep.txt").write_text("keep me\n", encoding="utf-8")
            before = snapshot(target)

            import manageroo.skill_pack as skill_pack

            original_copy = skill_pack._copy_validated_source_file
            calls = {"count": 0}

            def fail_after_first_copy(source, destination, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated staged copy failure")
                return original_copy(source, destination, *args, **kwargs)

            with patch.object(
                skill_pack,
                "_copy_validated_source_file",
                side_effect=fail_after_first_copy,
            ):
                with self.assertRaises(OSError):
                    import_skill_folder(source_root, skills_dir=skills, apply=True)

            self.assertEqual(snapshot(target), before)
            self.assertFalse((skills / ".demo-skill.manageroo-stage").exists())

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires no-follow file opening")
    def test_source_symlink_swap_after_validation_preserves_active_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "source"
            source_skill = source_root / "demo-skill"
            source_skill.mkdir(parents=True)
            (source_skill / "SKILL.md").write_text(
                "---\nname: demo-skill\n---\nnew skill\n",
                encoding="utf-8",
            )
            payload = source_skill / "payload.txt"
            payload.write_text("safe payload\n", encoding="utf-8")
            linked_secret = root / "linked-secret.txt"
            linked_secret.write_text("must not be installed\n", encoding="utf-8")

            skills = root / "skills"
            target = skills / "demo-skill"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (target / "keep.txt").write_text("keep me\n", encoding="utf-8")
            before = snapshot(target)

            import manageroo.skill_pack as skill_pack

            original_copy = skill_pack._copy_validated_source_file

            def swap_before_open(source_file, destination):
                if source_file.path == payload:
                    payload.unlink()
                    payload.symlink_to(linked_secret)
                return original_copy(source_file, destination)

            with patch.object(
                skill_pack,
                "_copy_validated_source_file",
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(ValueError, "Skill source changed during import"):
                    import_skill_folder(source_root, skills_dir=skills, apply=True)

            self.assertEqual(snapshot(target), before)
            self.assertEqual(list(skills.glob(".demo-skill.manageroo-stage-*")), [])
            installed = snapshot(target).values()
            self.assertFalse(any(linked_secret.read_bytes() in content for content in installed))


if __name__ == "__main__":
    unittest.main()
