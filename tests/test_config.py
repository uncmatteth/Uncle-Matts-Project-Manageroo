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

    def test_apply_agent_preset_replaces_only_agent_block(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir()
            config_path.write_text(config_template("codex", []), encoding="utf-8")
            result = apply_agent_preset(repo, "gemini")
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(result["preset"], "gemini")
            self.assertEqual(config["agent"]["adapter"], "generic")
            self.assertEqual(config["agent"]["executable"], "gemini")
            self.assertEqual(config["project"]["max_repair_cycles"], 2)


if __name__ == "__main__":
    unittest.main()
