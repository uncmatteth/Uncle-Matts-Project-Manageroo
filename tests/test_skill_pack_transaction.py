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
    def _replacement_fixture(self, root: Path):
        root = root.resolve()
        source = root / "source" / "demo-skill"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("new skill\n", encoding="utf-8")
        skills = root / "skills"
        target = skills / "demo-skill"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
        (target / "keep.txt").write_text("keep me\n", encoding="utf-8")
        return source, skills, target, snapshot(target)

    def test_failed_multifile_import_preserves_active_destination_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
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
            root = Path(temp).resolve()
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

    def test_source_change_after_scan_preserves_active_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "source"
            source_skill = source_root / "demo-skill"
            source_skill.mkdir(parents=True)
            skill_file = source_skill / "SKILL.md"
            skill_file.write_text(
                "---\nname: demo-skill\n---\nreviewed instructions\n",
                encoding="utf-8",
            )

            skills = root / "skills"
            target = skills / "demo-skill"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (target / "keep.txt").write_text("keep me\n", encoding="utf-8")
            before = snapshot(target)

            import manageroo.skill_pack as skill_pack

            original_scan = skill_pack.scan_skill_folder

            def mutate_after_scan(*args, **kwargs):
                report = original_scan(*args, **kwargs)
                skill_file.write_text(
                    "---\nname: changed-skill\n---\nunreviewed instructions\n",
                    encoding="utf-8",
                )
                return report

            with patch.object(skill_pack, "scan_skill_folder", side_effect=mutate_after_scan):
                with self.assertRaisesRegex(ValueError, "Skill source changed (after scan|during import)"):
                    import_skill_folder(source_root, skills_dir=skills, apply=True)

            self.assertEqual(snapshot(target), before)
            self.assertFalse((skills / "changed-skill").exists())
            self.assertEqual(list(skills.glob(".demo-skill.manageroo-stage-*")), [])
            self.assertEqual(list(skills.glob("demo-skill.manageroo-backup-*")), [])

    def test_support_file_change_after_scan_preserves_active_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "source"
            source_skill = source_root / "demo-skill"
            source_skill.mkdir(parents=True)
            (source_skill / "SKILL.md").write_text(
                "---\nname: demo-skill\n---\nreviewed instructions\n",
                encoding="utf-8",
            )
            helper_file = source_skill / "helper.py"
            helper_file.write_text("print('reviewed')\n", encoding="utf-8")

            skills = root / "skills"
            target = skills / "demo-skill"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (target / "keep.txt").write_text("keep me\n", encoding="utf-8")
            before = snapshot(target)

            import manageroo.skill_pack as skill_pack

            original_scan = skill_pack.scan_skill_folder

            def mutate_after_scan(*args, **kwargs):
                report = original_scan(*args, **kwargs)
                helper_file.write_text("print('unreviewed')\n", encoding="utf-8")
                return report

            with patch.object(skill_pack, "scan_skill_folder", side_effect=mutate_after_scan):
                with self.assertRaisesRegex(ValueError, "Skill source changed after scan"):
                    import_skill_folder(source_root, skills_dir=skills, apply=True)

            self.assertEqual(snapshot(target), before)
            self.assertEqual(list(skills.glob(".demo-skill.manageroo-stage-*")), [])
            self.assertEqual(list(skills.glob("demo-skill.manageroo-backup-*")), [])

    def test_cleanup_failure_cannot_skip_restoration_after_swap_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            import manageroo.skill_pack as skill_pack

            source, skills, target, before = self._replacement_fixture(Path(temp))
            original_rename = Path.rename
            calls = {"restored": False}

            def fail_swap(path, destination):
                if ".manageroo-stage-" in path.name:
                    raise OSError("simulated swap failure")
                if ".manageroo-backup-" in path.name:
                    calls["restored"] = True
                return original_rename(path, destination)

            with patch.object(Path, "rename", new=fail_swap), patch.object(
                skill_pack.shutil,
                "rmtree",
                side_effect=OSError("simulated cleanup failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated swap failure"):
                    skill_pack._transactional_replace_skill(source, target, skills)

            self.assertTrue(calls["restored"])
            self.assertEqual(snapshot(target), before)

    def test_swap_and_restoration_failures_are_both_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            import manageroo.skill_pack as skill_pack

            source, skills, target, _before = self._replacement_fixture(Path(temp))
            original_rename = Path.rename

            def fail_swap_and_restore(path, destination):
                if ".manageroo-stage-" in path.name:
                    raise OSError("simulated swap failure")
                if ".manageroo-backup-" in path.name:
                    raise OSError("simulated restoration failure")
                return original_rename(path, destination)

            with patch.object(Path, "rename", new=fail_swap_and_restore):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "simulated swap failure.*simulated restoration failure",
                ):
                    skill_pack._transactional_replace_skill(source, target, skills)

            self.assertFalse(target.exists())
            self.assertEqual(len(list(skills.glob("demo-skill.manageroo-backup-*"))), 1)


if __name__ == "__main__":
    unittest.main()
