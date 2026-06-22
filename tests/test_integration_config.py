import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.integration_config import configure_integrations
from manageroo.project import initialize_project


class IntegrationConfigTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        return repo

    def test_configures_installed_gbrain_and_gitnexus_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            def which(name):
                return f"/usr/bin/{name}" if name in {"gbrain", "gitnexus"} else None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                result = configure_integrations(repo, apply=True)

            config_path = repo / ".manageroo" / "config.toml"
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])
            self.assertEqual(config["integrations"]["gbrain_search_command"][0], "gbrain")
            self.assertEqual(config["integrations"]["gbrain_capture_command"][0], "gbrain")
            self.assertEqual(config["integrations"]["gitnexus_analyze_command"][0], "gitnexus")
            self.assertEqual(config["integrations"]["gitnexus_query_command"][0], "gitnexus")

    def test_missing_tools_report_one_next_command_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            original = (repo / ".manageroo" / "config.toml").read_text(encoding="utf-8")
            with patch("manageroo.integration_config.shutil.which", return_value=None):
                result = configure_integrations(repo, apply=True)

            current = (repo / ".manageroo" / "config.toml").read_text(encoding="utf-8")
            self.assertFalse(result["ok"])
            self.assertEqual(current, original)
            self.assertEqual(result["next_command"], "Install GBrain, then run `manageroo integrations configure`.")


if __name__ == "__main__":
    unittest.main()
