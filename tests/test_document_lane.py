import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.mock import MockAdapter
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class DocumentLaneTests(unittest.TestCase):
    def _fixture_repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Product\n", encoding="utf-8")
        (repo / "novel.md").write_text(
            "# Chapter One\n\n"
            + ("The operator needs exact prose handling, not a fake summary. " * 260),
            encoding="utf-8",
        )
        (repo / "test_fixture.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('manageroo_fixture.txt').read_text(), "
            "'MANAGEROO deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
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
        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product request\n\nCreate the deterministic fixture file.\n", encoding="utf-8")
        return repo

    def test_configured_document_command_creates_manifest_and_informs_planning(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "document_analysis_command = []",
                "document_analysis_command = "
                + _toml_array(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import json, sys; "
                            "data=json.load(open(sys.argv[1], encoding='utf-8')); "
                            "print('DOC LANE:' + str(data['summary']['document_files']) + ':' + data['files'][0]['path'])"
                        ),
                        "{document_manifest_file}",
                    ]
                ),
            )
            config.write_text(text, encoding="utf-8")

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(result["status"], "COMPLETE")
            run_root = Path(result["evidence_paths"]["run_root"])
            manifest = read_json(run_root / "artifacts" / "discovery" / "document-manifest.json")
            self.assertGreaterEqual(manifest["summary"]["document_files"], 1)
            self.assertTrue(any(item["path"] == "novel.md" for item in manifest["files"]))
            document = read_json(run_root / "artifacts" / "discovery" / "document-intelligence.json")
            self.assertIn("document-analysis", document["summary"]["passed"])
            self.assertIn("DOC LANE:", document["records"][0]["stdout"])
            external = read_json(run_root / "artifacts" / "discovery" / "external-intelligence.json")
            self.assertIn("document-analysis", external["summary"]["passed"])
            prompt = next((run_root / "packets").glob("*product-analyst/prompt.md"))
            self.assertIn("DOC LANE:", prompt.read_text(encoding="utf-8"))

    def test_failed_document_command_is_recorded_as_optional_context_not_ai_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "document_analysis_command = []",
                "document_analysis_command = "
                + _toml_array([sys.executable, "-c", "print('DOC FAIL'); raise SystemExit(9)"]),
            )
            config.write_text(text, encoding="utf-8")

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(result["status"], "COMPLETE")
            run_root = Path(result["evidence_paths"]["run_root"])
            document = read_json(run_root / "artifacts" / "discovery" / "document-intelligence.json")
            self.assertIn("document-analysis", document["summary"]["failed_optional"])
            self.assertIn("DOC FAIL", document["records"][0]["stdout"])


if __name__ == "__main__":
    unittest.main()
