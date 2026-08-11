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

    def test_configuration_preserves_commented_tables_after_integrations(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "[integrations]\n"
                "gbrain_search_command = []\n"
                "\n"
                "[safety] # policy\n"
                'allowed_programs = ["git"]\n'
                "\n"
                "[custom] # preserve this table too\n"
                'message = "keep me"\n',
                encoding="utf-8",
            )

            def which(name):
                return "/usr/bin/gbrain" if name == "gbrain" else None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                result = configure_integrations(repo, gitnexus=False, apply=True)

            current = config_path.read_text(encoding="utf-8")
            config = tomllib.loads(current)
            self.assertTrue(result["applied"])
            self.assertIn("[safety] # policy", current)
            self.assertIn("[custom] # preserve this table too", current)
            self.assertEqual(config["safety"]["allowed_programs"], ["git"])
            self.assertEqual(config["custom"]["message"], "keep me")

    def test_full_configuration_wires_every_recommended_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            vault = root / "obsidian-vault"
            vault.mkdir()
            (vault / "MANAGEROO").mkdir()

            def which(name):
                if name in {"gbrain", "gitnexus", "autoreview", "clawpatch", "manageroo"}:
                    return f"/usr/bin/{name}"
                return None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                result = configure_integrations(
                    repo,
                    full=True,
                    obsidian_vault=vault,
                    obsidian_export_folder="MANAGEROO",
                    apply=True,
                )

            config = tomllib.loads(
                (repo / ".manageroo" / "config.toml").read_text(encoding="utf-8")
            )["integrations"]
            self.assertTrue(result["ok"])
            self.assertEqual(config["obsidian_vault"], str(vault.resolve()))
            self.assertEqual(config["obsidian_export_folder"], "MANAGEROO")
            self.assertEqual(config["gbrain_search_command"][:2], ["gbrain", "search"])
            self.assertNotIn("--json", config["gitnexus_analyze_command"])
            self.assertEqual(config["gitnexus_analyze_command"][-2:], ["--embedding-device", "cpu"])
            self.assertEqual(config["gitnexus_query_command"][-2:], ["--repo", "{repo}"])
            self.assertEqual(config["document_analysis_command"][1], "document-analyze")
            self.assertEqual(config["autoreview_command"][0], "/usr/bin/autoreview")
            self.assertEqual(config["clawpatch_command"][0], "/usr/bin/clawpatch")


if __name__ == "__main__":
    unittest.main()
