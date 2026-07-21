import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.config import config_template
from manageroo.integration_config import configure_integrations


class IntegrationConfigRegressionTests(unittest.TestCase):
    def test_configure_integrations_preserves_unknown_custom_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir(parents=True)
            text = config_template("mock", [])
            text = text.replace(
                "gbrain_search_command = []",
                'gbrain_search_command = []\ncustom_tool_command = ["custom", "--flag"]',
            )
            config_path.write_text(text, encoding="utf-8")

            def which(name: str):
                return "/usr/bin/gbrain" if name == "gbrain" else None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                report = configure_integrations(
                    repo,
                    gbrain=True,
                    gitnexus=False,
                    apply=True,
                )

            self.assertTrue(report["applied"])
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["integrations"]["custom_tool_command"], ["custom", "--flag"])
            self.assertEqual(
                parsed["integrations"]["gbrain_search_command"],
                ["gbrain", "search", "{query}", "--json"],
            )


if __name__ == "__main__":
    unittest.main()
