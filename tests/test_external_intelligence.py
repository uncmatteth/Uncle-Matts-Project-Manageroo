import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.adapters.mock import MockAdapter
from umsmfburasbofe.orchestrator import Orchestrator
from umsmfburasbofe.project import initialize_project
from umsmfburasbofe.util import read_json


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class ExternalIntelligenceTests(unittest.TestCase):
    def _fixture_repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "UMSMFBURASBOFE Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Product\n", encoding="utf-8")
        (repo / "test_fixture.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('umsmfburasbofe_fixture.txt').read_text(), "
            "'UMSMFBURASBOFE deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        config = repo / ".umsmfburasbofe" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text += (
            "\n[[verification.gates]]\n"
            'id = "fixture-check"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            f"argv = {_toml_array([sys.executable, '-m', 'unittest', 'discover'])}\n"
        )
        config.write_text(text, encoding="utf-8")
        brief = repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md"
        brief.write_text(
            "# Product request\n\nCreate the deterministic fixture file.\n",
            encoding="utf-8",
        )
        return repo

    def test_configured_external_tools_inform_run_without_becoming_required(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".umsmfburasbofe" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "gbrain_search_command = []",
                "gbrain_search_command = "
                + _toml_array([
                    sys.executable,
                    "-c",
                    "import sys; print('GBRAIN HIT:' + sys.argv[1][:32])",
                    "{query}",
                ]),
            )
            text = text.replace(
                "gitnexus_query_command = []",
                "gitnexus_query_command = "
                + _toml_array([
                    sys.executable,
                    "-c",
                    "import sys; print('GITNEXUS OPTIONAL MISS'); sys.exit(7)",
                    "{repo}",
                ]),
            )
            text = text.replace(
                "gbrain_capture_command = []",
                "gbrain_capture_command = "
                + _toml_array([
                    sys.executable,
                    "-c",
                    "import sys; print('CAPTURED:' + sys.argv[1])",
                    "{status}",
                ]),
            )
            config.write_text(text, encoding="utf-8")

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".umsmfburasbofe" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(result["status"], "COMPLETE")
            run_root = Path(result["evidence_paths"]["run_root"])
            external = read_json(
                run_root / "artifacts" / "discovery" / "external-intelligence.json"
            )
            self.assertIn("gbrain-search", external["summary"]["passed"])
            self.assertIn("gitnexus-query", external["summary"]["failed_optional"])
            prompt = next((run_root / "packets").glob("*product-analyst/prompt.md"))
            prompt_text = prompt.read_text(encoding="utf-8")
            self.assertIn("External repo intelligence", prompt_text)
            self.assertIn("GBRAIN HIT:", prompt_text)
            capture = read_json(
                run_root / "artifacts" / "delivery" / "external-capture.json"
            )
            self.assertTrue(capture["summary"]["passed"])
            self.assertIn("CAPTURED:COMPLETE", capture["records"][0]["stdout"])


if __name__ == "__main__":
    unittest.main()
