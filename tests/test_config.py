import tempfile
import tomllib
import unittest
from pathlib import Path

from manageroo.config import apply_agent_preset, config_template


class ConfigTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
