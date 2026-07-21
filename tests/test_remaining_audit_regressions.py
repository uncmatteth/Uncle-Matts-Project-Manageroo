import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.acceptance import _needs_demonstration
from manageroo.errors import SafetyError
from manageroo.install_status import stack_status, uninstall_plan
from manageroo.jobs import JobStore
from manageroo.policy import ScopePolicy, validate_allowed_scope_patterns
from manageroo.readiness import _mentions
from manageroo.runner import CommandRunner
from manageroo.skill_pack import import_skill_folder
from manageroo.stack_update import stack_update_plan
from manageroo.util import redact_text


class RemainingAuditRegressionTests(unittest.TestCase):
    def test_secret_redaction_covers_json_quoted_values_plain_pairs_and_bearer_tokens(self):
        fixtures = [
            ('{"password":"s3cr3t"}', "s3cr3t"),
            ('{"api_key": "abc 123"}', "abc 123"),
            ("token=hunter2", "hunter2"),
            ("Authorization: Bearer deadbeef", "deadbeef"),
        ]
        for text, secret in fixtures:
            with self.subTest(text=text):
                redacted = redact_text(text)
                self.assertNotIn(secret, redacted)
                self.assertIn("REDACTED", redacted)

    def test_missing_executable_returns_failed_result_instead_of_raising_oserror(self):
        with tempfile.TemporaryDirectory() as temp:
            result = CommandRunner().run(
                ["manageroo-command-that-does-not-exist-4f897f"],
                cwd=Path(temp),
                timeout_seconds=5,
            )
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 127)
        self.assertIn("Could not launch command", result.stderr)

    def test_top_level_and_nested_secret_and_credential_paths_are_forbidden(self):
        sensitive = (
            "client-secret.json",
            "credentials.toml",
            "config/client-secret.json",
            "config/service-credential.txt",
        )
        for path in sensitive:
            with self.subTest(path=path):
                with self.assertRaises(SafetyError):
                    validate_allowed_scope_patterns([path])
                with self.assertRaises(SafetyError):
                    ScopePolicy((path,)).validate_paths([path])

    def test_job_and_attempt_identifiers_and_artifact_paths_reject_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = JobStore(root / "run")
            for bad_id in ("../victim", "../../victim", "a/b"):
                with self.subTest(job_id=bad_id), self.assertRaises(SafetyError):
                    store.create_or_load_job(
                        bad_id,
                        role="test",
                        schema="schema.json",
                        instructions="test",
                    )
            job = store.create_or_load_job(
                "safe-job",
                role="test",
                schema="schema.json",
                instructions="test",
            )
            with self.assertRaises(SafetyError):
                store._attempt_path(job.id, "../attempt")
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaises(SafetyError):
                store.complete_job(
                    job.id,
                    output_artifact="../../outside.json",
                    data={},
                    artifact_path=outside,
                )

    def test_readiness_terms_use_boundaries_while_real_document_terms_still_match(self):
        self.assertEqual(_mentions("Fix the bookkeeping calculation", ("book",)), [])
        self.assertEqual(_mentions("Update the book metadata", ("book",)), ["book"])
        self.assertEqual(_mentions("Read the PDF", ("pdf",)), ["pdf"])

    def test_acceptance_auth_term_does_not_match_author_but_real_auth_terms_do(self):
        self.assertFalse(_needs_demonstration("Update author documentation"))
        self.assertTrue(_needs_demonstration("Authentication must continue working"))
        self.assertTrue(_needs_demonstration("User can log in"))
        self.assertTrue(_needs_demonstration("Deploy the release"))

    def test_uninstall_plan_uses_recorded_custom_launcher_and_not_default_bin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            prefix.mkdir()
            custom_launcher = root / "custom-bin" / "manageroo"
            custom_launcher.parent.mkdir()
            custom_launcher.write_text("launcher", encoding="utf-8")
            (prefix / "install-lock.json").write_text(
                json.dumps({"launcher": str(custom_launcher), "external_tools": []}),
                encoding="utf-8",
            )
            plan = uninstall_plan(prefix=prefix)
            self.assertIn(str(custom_launcher), plan["core_paths"])
            self.assertTrue(plan["launcher_ownership_known"])
            default_launcher = str(Path.home() / ".local" / "bin" / "manageroo")
            if default_launcher != str(custom_launcher):
                self.assertNotIn(default_launcher, plan["core_paths"])

    def test_structurally_invalid_install_locks_return_diagnostics(self):
        invalid_payloads = [
            {"external_tools": None},
            {"external_tools": {}},
            {"external_tools": ["bad"]},
            {"external_tools": [{"name": "x", "next_commands": None}]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "install-lock.json"
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    report = stack_status(path)
                    self.assertFalse(report["ok"])
                    self.assertIn("invalid", report["error"])

    @unittest.skipUnless(os.name == "posix", "Linux package ownership matrix is POSIX-specific")
    def test_obsidian_update_prefers_the_package_manager_that_owns_the_install(self):
        def which(name: str):
            return {
                "obsidian": "/snap/bin/obsidian",
                "flatpak": "/usr/bin/flatpak",
                "snap": "/usr/bin/snap",
            }.get(name)

        def run(argv, **_kwargs):
            if argv[:3] == ["/usr/bin/flatpak", "info", "--user"]:
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "not installed"}
            if argv[:3] == ["/usr/bin/snap", "list", "obsidian"]:
                return {"ok": True, "exit_code": 0, "argv": argv, "output": "obsidian"}
            return {"ok": False, "exit_code": 1, "argv": argv, "output": "unexpected"}

        with patch("manageroo.stack_update.shutil.which", side_effect=which), patch(
            "manageroo.stack_update.platform.system", return_value="Linux"
        ), patch("manageroo.stack_update._run", side_effect=run):
            plan = stack_update_plan(["obsidian"])
        self.assertEqual(
            plan["tools"][0]["commands"],
            [["/usr/bin/snap", "refresh", "obsidian"]],
        )

    def test_failed_skill_import_staging_leaves_active_destination_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            skill = source / "sample-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: sample-skill\n---\nnew\n", encoding="utf-8")
            (skill / "extra.txt").write_text("new extra\n", encoding="utf-8")
            target_root = root / "target"
            destination = target_root / "sample-skill"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (destination / "keep.txt").write_text("keep\n", encoding="utf-8")
            before = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            }
            real_copy2 = shutil.copy2
            calls = {"count": 0}

            def fail_second(source_path, destination_path, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated staged copy failure")
                return real_copy2(source_path, destination_path, *args, **kwargs)

            with patch("manageroo.skill_pack.shutil.copy2", side_effect=fail_second):
                with self.assertRaises(OSError):
                    import_skill_folder(source, skills_dir=target_root, apply=True)
            after = {
                path.relative_to(destination).as_posix(): path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
