import multiprocessing
import os
import shutil
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
from manageroo.trufflehog import TRUFFLEHOG_VERSION


def _hold_autoreview_lock_before_owner_publication(
    destination,
    publication_paused,
    publish_owner,
    owner_entered,
    release_owner,
) -> None:
    import manageroo.stack_update_policy as policy

    original_write = policy.os.write

    def delayed_write(descriptor, data):
        publication_paused.set()
        if not publish_owner.wait(timeout=5):
            raise TimeoutError("test did not release owner publication")
        return original_write(descriptor, data)

    policy.os.write = delayed_write
    with policy._destination_lock(Path(destination)):
        owner_entered.set()
        if not release_owner.wait(timeout=5):
            raise TimeoutError("test did not release lock owner")


def _enter_autoreview_lock(destination, lock_opened, entered) -> None:
    import manageroo.stack_update_policy as policy

    original_open = policy.os.open

    def observed_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        lock_opened.set()
        return descriptor

    policy.os.open = observed_open
    with policy._destination_lock(Path(destination)):
        entered.set()


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
                "trufflehog": "/usr/bin/trufflehog",
            }.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update.platform.system", return_value="Linux"
        ), patch("manageroo.stack_update._run", side_effect=self.owned_run), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan()

        self.assertTrue(plan["ok"])
        self.assertFalse(plan["executes_changes"])
        tools = {item["name"]: item for item in plan["tools"]}
        self.assertNotIn(["/usr/bin/gbrain", "upgrade"], tools["gbrain"]["commands"])
        self.assertEqual(tools["gbrain"]["commands"], [["/usr/bin/gbrain", "doctor", "--json"]])
        self.assertIn(["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE], tools["gitnexus"]["commands"])
        self.assertIn(["/usr/bin/pnpm", "add", "-g", CLAWPATCH_PACKAGE], tools["clawpatch"]["commands"])
        self.assertNotIn("@latest", repr(plan))
        self.assertEqual(tools["trufflehog"]["pinned_version"], TRUFFLEHOG_VERSION)

    def test_homebrew_owned_obsidian_update_survives_policy_hardening(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {"brew": "/usr/local/bin/brew", "obsidian": str(obsidian)}.get(name)

            def run(argv, **_kwargs):
                owned = argv == ["/usr/local/bin/brew", "list", "--cask", "obsidian"]
                return {"ok": owned, "exit_code": 0 if owned else 1, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Darwin"
            ), patch("manageroo.stack_update._run", side_effect=run):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/local/bin/brew", "upgrade", "--cask", "obsidian"]],
        )

    def test_flatpak_owned_obsidian_update_survives_policy_hardening(self):
        with tempfile.TemporaryDirectory() as temp:
            obsidian = Path(temp) / "obsidian"
            obsidian.write_text("", encoding="utf-8")

            def which(name: str):
                return {"flatpak": "/usr/bin/flatpak", "obsidian": str(obsidian)}.get(name)

            def run(argv, **_kwargs):
                owned = argv == [
                    "/usr/bin/flatpak",
                    "info",
                    "--user",
                    "md.obsidian.Obsidian",
                ]
                return {"ok": owned, "exit_code": 0 if owned else 1, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update.platform.system", return_value="Linux"
            ), patch("manageroo.stack_update._run", side_effect=run):
                plan = stack_update_plan(["obsidian"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/bin/flatpak", "update", "--user", "-y", "md.obsidian.Obsidian"]],
        )

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
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan(["gitnexus"])
        self.assertEqual(plan["selected_tools"], ["gitnexus"])
        self.assertEqual([item["name"] for item in plan["tools"]], ["gitnexus"])

    def test_trufflehog_update_requires_manageroo_ownership_proof(self):
        with patch("manageroo.stack_update.shutil.which", side_effect=lambda name: "/usr/bin/trufflehog" if name == "trufflehog" else None), patch(
            "manageroo.stack_update._manageroo_owned_trufflehog_path", return_value=None
        ):
            plan = stack_update_plan(["trufflehog"])
        tool = plan["tools"][0]
        self.assertTrue(tool["installed"])
        self.assertEqual(tool["install_paths"], [])
        self.assertIn("ownership", tool["note"].lower())

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
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            result = apply_stack_updates(["gitnexus"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected_tools"], ["gitnexus"])
        self.assertEqual(calls, [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])

    def test_plan_drops_update_when_package_manager_ownership_is_not_proven(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "gitnexus": "/usr/bin/gitnexus"}.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update._run", side_effect=self.owned_run
        ), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=False
        ):
            plan = stack_update_plan(["gitnexus"])

        tool = plan["tools"][0]
        self.assertEqual(tool["commands"], [])
        self.assertIn("ownership", tool["note"])

    def test_plan_updates_npm_owned_clawpatch_when_pnpm_is_absent(self):
        def which(name: str):
            return {"npm": "/usr/bin/npm", "clawpatch": "/usr/bin/clawpatch"}.get(name)

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update_policy._owned_by_manager", return_value=True
        ):
            plan = stack_update_plan(["clawpatch"])

        self.assertEqual(
            plan["tools"][0]["commands"],
            [
                ["/usr/bin/npm", "install", "-g", CLAWPATCH_PACKAGE],
                ["/usr/bin/clawpatch", "doctor"],
            ],
        )

    def test_plan_proves_npm_owned_symlink_and_falls_back_from_wrong_manager(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "npm-prefix"
            npm_bin = prefix / "bin"
            package_root = prefix / "lib" / "node_modules"
            npm_bin.mkdir(parents=True)
            (package_root / "gitnexus" / "dist").mkdir(parents=True)
            (package_root / "clawpatch" / "dist").mkdir(parents=True)
            (package_root / "gitnexus" / "dist" / "cli.js").write_text("", encoding="utf-8")
            (package_root / "clawpatch" / "dist" / "cli.js").write_text("", encoding="utf-8")
            gitnexus = npm_bin / "gitnexus"
            clawpatch = npm_bin / "clawpatch"
            gitnexus.symlink_to(package_root / "gitnexus" / "dist" / "cli.js")
            clawpatch.symlink_to(package_root / "clawpatch" / "dist" / "cli.js")

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "pnpm": "/usr/bin/pnpm",
                    "gitnexus": str(gitnexus),
                    "clawpatch": str(clawpatch),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["prefix", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(prefix) + "\n"}
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["root", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(package_root) + "\n"}
                if argv[0] == "/usr/bin/npm" and argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": "installed\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:] == ["bin", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(Path(temp) / "pnpm-bin") + "\n"}
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "not owned"}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus", "clawpatch"])

            tools = {item["name"]: item for item in plan["tools"]}
            self.assertEqual(tools["gitnexus"]["commands"], [["/usr/bin/npm", "install", "-g", GITNEXUS_PACKAGE]])
            self.assertEqual(
                tools["clawpatch"]["commands"][:1],
                [["/usr/bin/npm", "install", "-g", CLAWPATCH_PACKAGE]],
            )

    def test_plan_falls_back_to_pnpm_for_pnpm_owned_gitnexus(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            npm_prefix = root / "npm-prefix"
            pnpm_bin = root / "pnpm-bin"
            pnpm_bin.mkdir()
            gitnexus = pnpm_bin / "gitnexus"
            gitnexus.write_text("", encoding="utf-8")

            def which(name: str):
                return {
                    "npm": "/usr/bin/npm",
                    "pnpm": "/usr/bin/pnpm",
                    "gitnexus": str(gitnexus),
                }.get(name)

            def run(argv, **_kwargs):
                if argv[0] == "/usr/bin/npm" and argv[1:] == ["prefix", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(npm_prefix) + "\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:] == ["bin", "-g"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": str(pnpm_bin) + "\n"}
                if argv[0] == "/usr/bin/pnpm" and argv[1:4] == ["list", "-g", "--depth=0"]:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": "installed\n"}
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "not owned"}

            with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
                "manageroo.stack_update._run", side_effect=run
            ):
                plan = stack_update_plan(["gitnexus"])

            self.assertEqual(
                plan["tools"][0]["commands"],
                [["/usr/bin/pnpm", "add", "-g", GITNEXUS_PACKAGE]],
            )

    def test_codex_only_autoreview_is_updated_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            codex_target = home / ".codex" / "skills" / "autoreview"
            codex_target.mkdir(parents=True)
            (codex_target / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )

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
            self.assertEqual(
                list(codex_target.parent.glob("autoreview.manageroo-backup-*")),
                [],
            )
            self.assertEqual(
                list((home / ".codex").glob(".autoreview.manageroo-rollback-*")),
                [],
            )
            installation = result["results"][0]["installations"][0]
            self.assertIsNone(installation["backup"])

    def test_autoreview_update_omits_only_the_known_claude_compatibility_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            destination = home / ".codex" / "skills" / "autoreview"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    skill = Path(kwargs["cwd"]) / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text("new\n", encoding="utf-8")
                    (skill / "AGENTS.md").write_text("rules\n", encoding="utf-8")
                    (skill / "CLAUDE.md").symlink_to("AGENTS.md")
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": AUTOREVIEW_COMMIT + "\n"}
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which", side_effect=lambda name: "/usr/bin/git" if name == "git" else None
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertTrue(result["ok"], result)
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertTrue((destination / "AGENTS.md").is_file())
            self.assertFalse((destination / "CLAUDE.md").exists())

    def test_symlinked_autoreview_alias_is_preserved_and_resolved_target_updated_once(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "autoreview"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text(
                "---\nname: autoreview\n---\nold\n",
                encoding="utf-8",
            )
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

    def test_autoreview_alias_targeting_another_skill_is_rejected_without_changes(self):
        if os.name == "nt":
            self.skipTest("symlink setup is platform-dependent on Windows")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex" / "skills" / "other-skill"
            target.mkdir(parents=True)
            original_skill = "---\nname: other-skill\n---\noriginal\n"
            (target / "SKILL.md").write_text(original_skill, encoding="utf-8")
            (target / "KEEP.txt").write_text("keep me\n", encoding="utf-8")
            alias = home / ".agents" / "skills" / "autoreview"
            alias.parent.mkdir(parents=True)
            alias.symlink_to(target, target_is_directory=True)

            def fake_run(argv, **kwargs):
                if argv[1:3] == ["clone", "--no-checkout"]:
                    checkout = Path(argv[-1])
                    checkout.mkdir(parents=True)
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "checkout" in argv:
                    skill = Path(kwargs["cwd"]) / "skills" / "autoreview"
                    skill.mkdir(parents=True)
                    (skill / "SKILL.md").write_text(
                        "---\nname: autoreview\n---\nupdated\n",
                        encoding="utf-8",
                    )
                    return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}
                if "rev-parse" in argv:
                    return {
                        "ok": True,
                        "exit_code": 0,
                        "argv": argv,
                        "output": AUTOREVIEW_COMMIT + "\n",
                    }
                return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

            with patch("manageroo.stack_update.Path.home", return_value=home), patch(
                "manageroo.stack_update.shutil.which",
                side_effect=lambda name: "/usr/bin/git" if name == "git" else None,
            ), patch("manageroo.stack_update._run", side_effect=fake_run):
                result = apply_stack_updates(["autoreview"])

            self.assertFalse(result["ok"], result)
            self.assertIn("unsafe", result["results"][0]["error"].lower())
            self.assertTrue(alias.is_symlink())
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), original_skill)
            self.assertEqual((target / "KEEP.txt").read_text(encoding="utf-8"), "keep me\n")

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
            self.assertEqual(list(root.glob(".autoreview.manageroo-rollback-*")), [])

    def test_autoreview_cleanup_failure_reports_installed_update_with_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new\n", encoding="utf-8")
            destination = root / "skills" / "autoreview"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("old\n", encoding="utf-8")
            real_rmtree = shutil.rmtree

            def fail_rollback_cleanup(path, *args, **kwargs):
                if ".manageroo-rollback-" in Path(path).name:
                    raise OSError("simulated cleanup failure")
                return real_rmtree(path, *args, **kwargs)

            with patch("manageroo.stack_update_policy.shutil.rmtree", side_effect=fail_rollback_cleanup):
                result = _replace_autoreview(source, destination)

            self.assertTrue(result["ok"], result)
            self.assertIn("update was installed", result["cleanup_warning"].lower())
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "new\n")
            self.assertTrue(Path(result["backup"]).is_dir())

    def test_autoreview_lock_blocks_contender_before_owner_metadata_is_published(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            context = multiprocessing.get_context("spawn")
            publication_paused = context.Event()
            publish_owner = context.Event()
            owner_entered = context.Event()
            release_owner = context.Event()
            contender_opened = context.Event()
            contender_entered = context.Event()
            owner = context.Process(
                target=_hold_autoreview_lock_before_owner_publication,
                args=(
                    destination,
                    publication_paused,
                    publish_owner,
                    owner_entered,
                    release_owner,
                ),
            )
            contender = context.Process(
                target=_enter_autoreview_lock,
                args=(destination, contender_opened, contender_entered),
            )

            try:
                owner.start()
                self.assertTrue(publication_paused.wait(timeout=5))
                contender.start()
                self.assertTrue(contender_opened.wait(timeout=5))
                self.assertFalse(contender_entered.wait(timeout=0.3))
                publish_owner.set()
                self.assertTrue(owner_entered.wait(timeout=5))
                self.assertFalse(contender_entered.wait(timeout=0.3))
                release_owner.set()
                owner.join(timeout=5)
                contender.join(timeout=5)
                self.assertEqual(owner.exitcode, 0)
                self.assertEqual(contender.exitcode, 0)
                self.assertTrue(contender_entered.is_set())
            finally:
                publish_owner.set()
                release_owner.set()
                for process in (owner, contender):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

    def test_autoreview_lock_never_unlinks_stale_owner_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "autoreview"
            lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
            lock.write_text("pid=999999999\n", encoding="utf-8")

            with patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=AssertionError("lock path must not be unlinked"),
            ):
                from manageroo.stack_update_policy import _destination_lock

                with _destination_lock(destination):
                    pass

            self.assertTrue(lock.is_file())
            self.assertEqual(lock.read_text(encoding="utf-8"), f"pid={os.getpid()}\n")

    def test_plain_output_makes_apply_boundary_explicit(self):
        text = format_stack_update(stack_update_plan())
        self.assertIn("No changes were made", text)
        self.assertIn("--apply", text)


if __name__ == "__main__":
    unittest.main()
