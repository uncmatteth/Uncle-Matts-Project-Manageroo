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

            original_copy2 = skill_pack.shutil.copy2
            calls = {"count": 0}

            def fail_after_first_copy(source, destination, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated staged copy failure")
                return original_copy2(source, destination, *args, **kwargs)

            with patch.object(skill_pack.shutil, "copy2", side_effect=fail_after_first_copy):
                with self.assertRaises(OSError):
                    import_skill_folder(source_root, skills_dir=skills, apply=True)

            self.assertEqual(snapshot(target), before)
            self.assertFalse((skills / ".demo-skill.manageroo-stage").exists())


if __name__ == "__main__":
    unittest.main()
