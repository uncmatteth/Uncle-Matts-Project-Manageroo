import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.mock import MockAdapter
from manageroo.errors import ValidationError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json
from tests.stack_shims import (
    gbrain_capture_command,
    gbrain_search_command,
    gitnexus_analyze_command,
    gitnexus_status_command,
)


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class DocumentLaneTests(unittest.TestCase):
    def setUp(self):
        self._gbrain_source_patch = patch(
            "manageroo.orchestrator.gbrain_repo_source_item",
            return_value={
                "name": "gbrain",
                "ok": True,
                "detail": "test repo-scoped source is mapped",
                "next": "",
                "required": True,
                "matched_sources": [{"id": "fixture"}],
            },
        )
        self._gbrain_source_patch.start()

    def tearDown(self):
        self._gbrain_source_patch.stop()

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
        probe_dir = root / "operator-bin"
        probe_dir.mkdir()
        gbrain_probe = probe_dir / "gbrain-readiness-probe"
        gitnexus_probe = probe_dir / "gitnexus-readiness-probe"
        for probe in (gbrain_probe, gitnexus_probe):
            probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            probe.chmod(0o755)
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text = text.replace(
            "gbrain_readiness_probe_command = []",
            "gbrain_readiness_probe_command = " + _toml_array([str(gbrain_probe)]),
        )
        text = text.replace(
            "gitnexus_readiness_probe_command = []",
            "gitnexus_readiness_probe_command = " + _toml_array([str(gitnexus_probe)]),
        )
        text = text.replace(
            'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
            "gbrain_search_command = " + _toml_array(gbrain_search_command()),
        )
        text = text.replace(
            'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]',
            "gbrain_capture_command = " + _toml_array(gbrain_capture_command()),
        )
        text = text.replace(
            'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
            "gitnexus_analyze_command = " + _toml_array(gitnexus_analyze_command()),
        )
        text = text.replace(
            'gitnexus_status_command = ["gitnexus", "status"]',
            "gitnexus_status_command = " + _toml_array(gitnexus_status_command()),
        )
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
            prompt = next((run_root / "packets").glob("*product-analyst/*/prompt.md"))
            self.assertIn("DOC LANE:", prompt.read_text(encoding="utf-8"))

    def test_failed_document_command_for_passive_repo_docs_is_optional_context_not_ai_repair(self):
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

    def test_failed_document_command_blocks_when_brief_requests_document_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            brief.write_text(
                "# Product request\n\nPreserve exact wording in this long prose chapter.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "document_analysis_command = []",
                "document_analysis_command = "
                + _toml_array([sys.executable, "-c", "print('DOC FAIL'); raise SystemExit(9)"]),
            )
            config.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(ValidationError, "document-analysis"):
                Orchestrator(repo, adapter=MockAdapter()).run(
                    brief_path=brief,
                    mode="build",
                    apply_on_success=True,
                )


if __name__ == "__main__":
    unittest.main()
