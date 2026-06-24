import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.config import GBRAIN_SEARCH_COMMAND
from manageroo.gbrain_scope import gbrain_query_payload, scope_gbrain_search_record
from manageroo.integration_config import configure_integrations
from manageroo.integrations import ExternalCommandIntegration
from manageroo.project import initialize_project


class RecordingRunner:
    def __init__(self):
        self.argv = None

    def run(self, argv, *, cwd, timeout_seconds, log_name=None):
        self.argv = list(argv)

        class Result:
            passed = True
            exit_code = 0
            timed_out = False
            stdout = "[]"
            stderr = ""
            duration_seconds = 0.0
            log_path = None

        return Result()


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
            self.assertEqual(config["integrations"]["gitnexus_status_command"][0], "gitnexus")

    def test_configure_migrates_old_manageroo_gitnexus_template(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config_path = repo / ".manageroo" / "config.toml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                    'gitnexus_analyze_command = ["gitnexus", "analyze", "{repo}", "--json"]',
                ),
                encoding="utf-8",
            )

            def which(name):
                return f"/usr/bin/{name}" if name in {"gbrain", "gitnexus"} else None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                result = configure_integrations(repo, apply=True)

            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])
            self.assertTrue(result["applied"])
            self.assertEqual(
                config["integrations"]["gitnexus_analyze_command"],
                ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"],
            )

    def test_configure_migrates_old_manageroo_gbrain_template(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config_path = repo / ".manageroo" / "config.toml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                    'gbrain_search_command = ["gbrain", "search", "{query}", "--json"]',
                ),
                encoding="utf-8",
            )

            def which(name):
                return f"/usr/bin/{name}" if name in {"gbrain", "gitnexus"} else None

            with patch("manageroo.integration_config.shutil.which", side_effect=which):
                result = configure_integrations(repo, apply=True)

            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])
            self.assertTrue(result["applied"])
            self.assertEqual(config["integrations"]["gbrain_search_command"], GBRAIN_SEARCH_COMMAND)

    def test_default_gbrain_template_passes_preencoded_json_payload(self):
        runner = RecordingRunner()
        payload = '{"query":"quoted \\" value with {braces}","limit":20,"source_id":"fixture"}'

        ExternalCommandIntegration(GBRAIN_SEARCH_COMMAND, runner).run(
            cwd=Path.cwd(),
            values={"gbrain_query_payload": payload},
            timeout_seconds=30,
        )

        self.assertEqual(runner.argv, ["gbrain", "call", "query", payload])

    def test_gbrain_query_payload_uses_stable_source_id_not_display_name(self):
        payload = json.loads(
            gbrain_query_payload(
                "brief",
                {"matched_sources": [{"id": "release-smoke", "name": "release smoke"}]},
            )
        )

        self.assertEqual(payload["source_id"], "release-smoke")

    def test_gbrain_scope_does_not_authorize_display_name_collision(self):
        scoped = scope_gbrain_search_record(
            {
                "ok": True,
                "stdout": json.dumps(
                    {
                        "results": [
                            {
                                "source_id": "other-source",
                                "source_name": "Shared Display Name",
                                "text": "wrong source",
                            }
                        ]
                    }
                ),
            },
            {"matched_sources": [{"id": "target-source", "name": "Shared Display Name"}]},
        )

        self.assertFalse(scoped["ok"])
        self.assertEqual(scoped["gbrain_source_scope"]["kept"], 0)

    def test_gbrain_scope_scrubs_stderr_from_scoped_records(self):
        scoped = scope_gbrain_search_record(
            {
                "ok": True,
                "stdout": json.dumps(
                    {
                        "results": [
                            {
                                "source_id": "target-source",
                                "text": "right source",
                            }
                        ]
                    }
                ),
                "stderr": "diagnostic from the wrong source",
            },
            {"matched_sources": [{"id": "target-source"}]},
        )

        self.assertTrue(scoped["ok"])
        self.assertEqual(scoped["stderr"], "")
        self.assertNotIn("wrong source", json.dumps(scoped))

    def test_gbrain_scope_scrubs_outputs_from_validation_failures(self):
        scoped = scope_gbrain_search_record(
            {
                "ok": True,
                "stdout": "not json from another source",
                "stderr": "diagnostic from another source",
            },
            {"matched_sources": [{"id": "target-source"}]},
        )

        self.assertFalse(scoped["ok"])
        self.assertEqual(scoped["stdout"], "")
        self.assertEqual(scoped["stderr"], "")

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
