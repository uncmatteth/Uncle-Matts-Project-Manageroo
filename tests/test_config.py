import multiprocessing
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from manageroo.config import apply_agent_preset, config_template
from manageroo.config_lock import config_mutation_lock
from manageroo.errors import SafetyError


def _hold_lock_before_owner_publication(config_path, publication_paused, release) -> None:
    import manageroo.config_lock as config_lock

    original_write = config_lock.os.write

    def delayed_write(descriptor, data):
        publication_paused.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release owner publication")
        return original_write(descriptor, data)

    config_lock.os.write = delayed_write
    with config_lock.config_mutation_lock(Path(config_path)):
        pass


def _enter_config_lock(config_path, lock_opened, entered) -> None:
    import manageroo.config_lock as config_lock

    original_open = config_lock.os.open

    def observed_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        lock_opened.set()
        return descriptor

    config_lock.os.open = observed_open
    with config_lock.config_mutation_lock(Path(config_path)):
        entered.set()


class ConfigTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX directory permissions")
    def test_config_lock_rejects_writable_existing_cache_before_creating_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.toml"
            cache = root / "cache"
            cache.mkdir()
            cache.chmod(0o777)
            lock_path = cache / "config.toml.manageroo.lock"

            with self.assertRaisesRegex(SafetyError, "directory is unsafe"):
                with config_mutation_lock(config_path):
                    self.fail("unsafe cache directory must not be used")

            self.assertFalse(lock_path.exists())
            self.assertEqual(cache.stat().st_mode & 0o777, 0o777)

    def test_config_lock_rejects_hard_link_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.toml"
            cache = root / "cache"
            cache.mkdir()
            target = root / "do-not-overwrite.txt"
            target.write_text("keep me\n", encoding="utf-8")
            target.chmod(0o600)
            try:
                os.link(target, cache / "config.toml.manageroo.lock")
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this platform")

            with self.assertRaisesRegex(SafetyError, "unsafe"):
                with config_mutation_lock(config_path):
                    self.fail("hard-linked lock must not be acquired")

            self.assertEqual(target.read_text(encoding="utf-8"), "keep me\n")

    def test_contender_waits_while_owner_metadata_is_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.toml"
            context = multiprocessing.get_context("spawn")
            publication_paused = context.Event()
            release = context.Event()
            contender_opened = context.Event()
            contender_entered = context.Event()
            owner = context.Process(
                target=_hold_lock_before_owner_publication,
                args=(config_path, publication_paused, release),
            )
            contender = context.Process(
                target=_enter_config_lock,
                args=(config_path, contender_opened, contender_entered),
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

    def test_config_template_writes_generic_agent_argv_template(self):
        config = tomllib.loads(config_template("generic", []))
        self.assertEqual(config["agent"]["adapter"], "generic")
        self.assertEqual(config["agent"]["argv_template"][0], "YOUR_AGENT")
        self.assertIn("{prompt}", config["agent"]["argv_template"])
        self.assertEqual(config["integrations"]["document_analysis_command"], [])

    def test_auto_config_is_vendor_neutral_and_budgeted(self):
        config = tomllib.loads(config_template("auto", []))
        self.assertEqual(config["agent"]["adapter"], "auto")
        self.assertEqual(
            config["agent"]["candidates"],
            ["codex", "claude-code", "gemini"],
        )
        self.assertGreater(config["budget"]["max_total_worker_calls"], 0)
        self.assertGreater(config["budget"]["max_runtime_minutes"], 0)

    def test_apply_agent_preset_replaces_only_agent_block(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir()
            text = config_template(
                "codex",
                [
                    {
                        "id": "custom-smoke",
                        "kind": "check",
                        "required": True,
                        "timeout_seconds": 321,
                        "argv": ["python3", "-c", "print('custom')"],
                    }
                ],
            )
            text = text.replace("max_repair_cycles = 2", "max_repair_cycles = 9")
            text = text.replace("max_total_worker_calls = 80", "max_total_worker_calls = 17")
            text = text.replace("max_runtime_minutes = 240", "max_runtime_minutes = 33")
            text = text.replace(
                "gbrain_search_command = []",
                'gbrain_search_command = ["gbrain", "search", "--json"]\ncustom_tool_command = ["custom", "--flag"]',
            )
            config_path.write_text(text, encoding="utf-8")
            before = tomllib.loads(config_path.read_text(encoding="utf-8"))

            result = apply_agent_preset(repo, "gemini")
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(result["preset"], "gemini")
            self.assertEqual(config["agent"]["adapter"], "generic")
            self.assertEqual(config["agent"]["executable"], "gemini")
            self.assertEqual(config["agent"]["prompt_transport"], "stdin")
            self.assertIn("--approval-mode=plan", config["agent"]["sandbox_read_only_argv"])
            self.assertNotIn("--sandbox", config["agent"]["sandbox_read_only_argv"])
            self.assertEqual(config["agent"]["doctor_argv"], ["gemini", "--help"])
            self.assertEqual(config["agent"]["required_help_flags"], ["--approval-mode", "--prompt"])

            for section in ("project", "context", "orchestration", "budget", "safety", "integrations", "verification"):
                with self.subTest(section=section):
                    self.assertEqual(config[section], before[section])
            self.assertEqual(config["project"]["max_repair_cycles"], 9)
            self.assertEqual(config["budget"]["max_total_worker_calls"], 17)
            self.assertEqual(config["budget"]["max_runtime_minutes"], 33)
            self.assertEqual(config["integrations"]["custom_tool_command"], ["custom", "--flag"])
            self.assertEqual(config["verification"]["gates"][0]["id"], "custom-smoke")

    def test_apply_agent_preset_handles_multiline_agent_values(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir()
            text = config_template("codex", []).replace(
                'model = ""\n',
                '''model = ""
notes = """
[literal]
"""
nested = [
    [
        "old-agent-only",
    ],
]
''',
            )
            config_path.write_text(text, encoding="utf-8")
            before = tomllib.loads(text)

            apply_agent_preset(repo, "gemini")
            updated_text = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(updated_text)

            self.assertEqual(config["agent"]["executable"], "gemini")
            self.assertNotIn("notes", config["agent"])
            self.assertNotIn("nested", config["agent"])
            self.assertNotIn("old-agent-only", updated_text)
            self.assertEqual(
                {key: value for key, value in config.items() if key != "agent"},
                {key: value for key, value in before.items() if key != "agent"},
            )

    def test_directly_imported_apply_agent_preset_acquires_mutation_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(config_template("codex", []), encoding="utf-8")

            with mock.patch("manageroo.config.config_mutation_lock", wraps=config_mutation_lock) as lock:
                apply_agent_preset(repo, "gemini")

            lock.assert_called_once_with(config_path)


if __name__ == "__main__":
    unittest.main()
