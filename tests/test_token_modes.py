import json
import multiprocessing
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import symlink_or_skip

from manageroo.token_modes import (
    CORE_HELPER_SKILLS,
    _copy_skill_tree,
    _skill_install_lock,
    _skill_tree_sha256,
    install_core_helper_skills,
    install_token_skills,
    read_token_mode,
    set_token_mode,
    token_mode_prompt,
)


def _hold_skill_lock_before_owner_publication(root, publication_paused, release) -> None:
    import manageroo.token_modes as token_modes

    original_write = token_modes.os.write

    def delayed_write(descriptor, data):
        publication_paused.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release skill-lock owner publication")
        return original_write(descriptor, data)

    token_modes.os.write = delayed_write
    with token_modes._skill_install_lock(Path(root)):
        pass


def _enter_skill_lock(root, lock_opened, entered) -> None:
    import manageroo.token_modes as token_modes

    original_open = token_modes.os.open

    def observed_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        lock_opened.set()
        return descriptor

    token_modes.os.open = observed_open
    with token_modes._skill_install_lock(Path(root)):
        entered.set()


class TokenModeTests(unittest.TestCase):
    def test_contender_waits_while_skill_lock_owner_metadata_is_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = multiprocessing.get_context("spawn")
            publication_paused = context.Event()
            release = context.Event()
            contender_opened = context.Event()
            contender_entered = context.Event()
            owner = context.Process(
                target=_hold_skill_lock_before_owner_publication,
                args=(root, publication_paused, release),
            )
            contender = context.Process(
                target=_enter_skill_lock,
                args=(root, contender_opened, contender_entered),
            )

            try:
                owner.start()
                self.assertTrue(publication_paused.wait(timeout=5))
                contender.start()
                self.assertTrue(contender_opened.wait(timeout=5))
                self.assertFalse(contender_entered.wait(timeout=0.3))
                release.set()
                owner.join(timeout=5)
                contender.join(timeout=5)
                self.assertEqual(owner.exitcode, 0)
                self.assertEqual(contender.exitcode, 0)
                self.assertTrue(contender_entered.is_set())
            finally:
                release.set()
                for process in (owner, contender):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

    @unittest.skipIf(os.name == "nt", "hard-link setup is platform-dependent on Windows")
    def test_skill_lock_rejects_hard_link_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "do-not-overwrite.txt"
            target.write_text("keep me\n", encoding="utf-8")
            os.link(target, root / ".manageroo-skill-install.lock")

            with self.assertRaisesRegex(OSError, "private regular file"):
                with _skill_install_lock(root):
                    self.fail("hard-linked lock must not be acquired")

            self.assertEqual(target.read_text(encoding="utf-8"), "keep me\n")

    def test_existing_skill_lock_contents_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / ".manageroo-skill-install.lock"
            lock.write_text("existing user data\n", encoding="utf-8")

            with _skill_install_lock(root):
                pass

            self.assertEqual(lock.read_text(encoding="utf-8"), "existing user data\n")

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

    def test_installs_token_skills_with_relative_root(self):
        with tempfile.TemporaryDirectory() as temp:
            previous_cwd = Path.cwd()
            os.chdir(temp)
            try:
                installed = install_token_skills(Path("skills"))
            finally:
                os.chdir(previous_cwd)

            root = Path(temp) / "skills"
            self.assertEqual(Path(installed["caveman"]), root / "caveman" / "SKILL.md")
            self.assertEqual(
                Path(installed["curse"]),
                root / "uncle-matts-caveman-curse" / "SKILL.md",
            )
            self.assertTrue((root / "caveman" / "SKILL.md").is_file())
            self.assertTrue((root / "uncle-matts-caveman-curse" / "SKILL.md").is_file())

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

    def test_failed_token_mode_write_rolls_back_installed_skill_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            state = base / "token-mode.json"
            skills = base / "skills"
            ownership = skills / ".manageroo-ownership.json"
            set_token_mode("off", state_path=state, install_skills=False)
            install_token_skills(skills)

            target = skills / "caveman" / "SKILL.md"
            target.write_text("previous active manageroo skill\n", encoding="utf-8")
            ownership_data = json.loads(ownership.read_text(encoding="utf-8"))
            ownership_data["skills"][str(target.parent.resolve())]["tree_sha256"] = (
                _skill_tree_sha256(target.parent)
            )
            curse_dir = skills / "uncle-matts-caveman-curse"
            shutil.rmtree(curse_dir)
            ownership_data["skills"].pop(str(curse_dir.resolve()))
            ownership.write_text(
                json.dumps(ownership_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            state_before = state.read_bytes()
            ownership_before = ownership.read_bytes()
            skill_before = target.read_bytes()
            from manageroo import token_modes

            original_write = token_modes.atomic_write_json

            def fail_state_write(path, data):
                if Path(path).resolve() == state.resolve():
                    original_write(path, data)
                    raise OSError("state disk full")
                return original_write(path, data)

            with patch("manageroo.token_modes.atomic_write_json", side_effect=fail_state_write):
                with self.assertRaisesRegex(OSError, "state disk full"):
                    set_token_mode("curse", state_path=state, skills_dir=skills)

            self.assertEqual(state.read_bytes(), state_before)
            self.assertEqual(ownership.read_bytes(), ownership_before)
            self.assertEqual(target.read_bytes(), skill_before)
            self.assertFalse(curse_dir.exists())

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

    def test_concurrent_edit_during_owned_skill_replacement_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            skills = base / "skills"
            ownership = base / "ownership.json"
            install_core_helper_skills(skills, ownership_path=ownership)
            target = skills / "diagnose" / "SKILL.md"
            target.write_text("previous manageroo diagnose\n", encoding="utf-8")
            ownership_data = json.loads(ownership.read_text(encoding="utf-8"))
            ownership_data["skills"][str(target.parent.resolve())]["tree_sha256"] = (
                _skill_tree_sha256(target.parent)
            )
            ownership.write_text(
                json.dumps(ownership_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            from manageroo import token_modes

            original = token_modes._replace_owned_skill

            def edit_before_replace(
                source_dir,
                destination_dir,
                root_real,
                *,
                expected_identity=None,
            ):
                target.write_text("concurrent user edit\n", encoding="utf-8")
                return original(
                    source_dir,
                    destination_dir,
                    root_real,
                    expected_identity=expected_identity,
                )

            with patch("manageroo.token_modes._replace_owned_skill", side_effect=edit_before_replace):
                with self.assertRaisesRegex(RuntimeError, "changed during replacement"):
                    install_core_helper_skills(skills, ownership_path=ownership)

            self.assertEqual(target.read_text(encoding="utf-8"), "concurrent user edit\n")

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
            symlink_or_skip(self, outside, target)
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
            symlink_or_skip(
                self,
                outside,
                skills / "pimp-my-prompt",
                target_is_directory=True,
            )
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
            symlink_or_skip(self, outside, linked, target_is_directory=True)
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
