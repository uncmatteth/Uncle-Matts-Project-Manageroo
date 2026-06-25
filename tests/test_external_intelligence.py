import json
import shlex
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


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


def _text_command(name: str, text: str, *, exit_code: int = 0) -> list[str]:
    root = Path(tempfile.mkdtemp(prefix="manageroo-test-command-"))
    command = root / name
    command.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' {shlex.quote(text)}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return [str(command)]


def _json_command(name: str, payload: dict) -> list[str]:
    return _text_command(name, json.dumps(payload))


def _capture_echo_command() -> list[str]:
    root = Path(tempfile.mkdtemp(prefix="manageroo-test-command-"))
    command = root / "gbrain-capture"
    command.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"CAPTURED:$1\"\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return [str(command), "{status}"]


def _gitnexus_analyze_command(text: str = "GITNEXUS ANALYZE OK", *, exit_code: int = 0) -> list[str]:
    return _text_command("gitnexus-analyze", text, exit_code=exit_code)


def _gitnexus_status_command(text: str = "GITNEXUS STATUS OK", *, exit_code: int = 0) -> list[str]:
    return _text_command("gitnexus-status", text, exit_code=exit_code)


def _autoreview_command(text: str = "AUTOREVIEW OK", *, exit_code: int = 0) -> list[str]:
    return _text_command("autoreview", text, exit_code=exit_code)


def _clawpatch_command(text: str = "CLAWPATCH OK", *, exit_code: int = 0) -> list[str]:
    return _text_command("clawpatch", text, exit_code=exit_code)


def _gitnexus_workspace_marker_commands() -> tuple[list[str], list[str]]:
    root = Path(tempfile.mkdtemp(prefix="manageroo-test-command-"))
    analyze = root / "gitnexus-analyze-marker"
    analyze.write_text(
        "#!/bin/sh\n"
        "printf '%s' 'gitnexus workspace marker' > \"$1/.gitnexus-marker\"\n"
        "printf '%s\\n' \"$1\"\n",
        encoding="utf-8",
    )
    status = root / "gitnexus-status-marker"
    status.write_text(
        "#!/bin/sh\n"
        "printf '%s' 'gitnexus status arg' > \"$1/.gitnexus-status-arg\"\n"
        "printf '%s' 'gitnexus status cwd' > \"$(pwd)/.gitnexus-status-cwd\"\n",
        encoding="utf-8",
    )
    analyze.chmod(0o755)
    status.chmod(0o755)
    return [str(analyze), "{workspace}"], [str(status), "{workspace}"]


def _failing_then_recovered_capture_command(state_path: Path) -> list[str]:
    root = Path(tempfile.mkdtemp(prefix="manageroo-test-command-"))
    command = root / "gbrain-capture-retry"
    command.write_text(
        "#!/bin/sh\n"
        "report=\"$1\"\n"
        "state=\"$2\"\n"
        "if [ -f \"$state\" ] && grep -Fq '**Status:** **COMPLETE**' \"$report\" "
        "&& ! grep -Fq '**Status:** **BLOCKED**' \"$report\"; then\n"
        "  printf '%s\\n' 'GBRAIN CAPTURE RECOVERED'\n"
        "  exit 0\n"
        "fi\n"
        "grep -F '**Status:**' \"$report\" > \"$state\" 2>/dev/null || true\n"
        "printf '%s\\n' 'GBRAIN CAPTURE MISS'\n"
        "exit 9\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return [str(command), "{report_file}", str(state_path)]


GBRAIN_SOURCE_OK = {
    "name": "gbrain",
    "ok": True,
    "detail": "test repo-scoped source is mapped",
    "next": "",
    "required": True,
    "matched_sources": [{"id": "fixture"}],
}


def _gbrain_search_command(
    text: str = "GBRAIN HIT",
    *,
    extra_results: list[dict] | None = None,
) -> list[str]:
    results = [
        *(extra_results or []),
        {"source_id": "fixture", "text": text},
    ]
    return _json_command("gbrain-search", {"results": results})


def _gbrain_path_search_command(child_path: Path, parent_path: Path, sibling_path: Path) -> list[str]:
    return _json_command(
        "gbrain-path-search",
        {
            "results": [
                {"file_path": str(child_path), "text": "CHILD REPO HIT"},
                {"file_path": str(parent_path), "text": "PARENT SOURCE LEAK"},
                {"file_path": str(sibling_path), "text": "SIBLING SOURCE LEAK"},
            ]
        },
    )


def _gbrain_search_with_top_level_command() -> list[str]:
    return _json_command(
        "gbrain-search-top-level",
        {
            "summary": "SECRET OTHER SOURCE SUMMARY",
            "results": [
                {"source_id": "other", "text": "SECRET OTHER SOURCE"},
                {"source_id": "fixture", "text": "GBRAIN HIT"},
            ],
        },
    )


class ExternalIntelligenceTests(unittest.TestCase):
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
            'autoreview_command = ["autoreview", "--mode", "local"]',
            "autoreview_command = " + _toml_array(_autoreview_command()),
        )
        text = text.replace(
            'clawpatch_command = ["clawpatch", "review", "--limit", "3", "--jobs", "3", "--state-dir", "{external_state_dir}/clawpatch"]',
            "clawpatch_command = " + _toml_array(_clawpatch_command()),
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
        brief.write_text(
            "# Product request\n\nCreate the deterministic fixture file.\n",
            encoding="utf-8",
        )
        return repo

    def test_required_external_tools_inform_run_when_all_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                "gbrain_search_command = " + _toml_array(_gbrain_search_command("GBRAIN HIT:")),
            )
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
            )
            text = text.replace(
                'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]',
                "gbrain_capture_command = " + _toml_array(_capture_echo_command()),
            )
            config.write_text(text, encoding="utf-8")

            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                result = Orchestrator(repo, adapter=MockAdapter()).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )

            self.assertEqual(result["status"], "COMPLETE")
            run_root = Path(result["evidence_paths"]["run_root"])
            external = read_json(
                run_root / "artifacts" / "discovery" / "external-intelligence.json"
            )
            self.assertIn("gbrain-search", external["summary"]["passed"])
            self.assertIn("gitnexus-analyze", external["summary"]["passed"])
            self.assertIn("gitnexus-status", external["summary"]["passed"])
            self.assertEqual(external["summary"]["failed_required"], [])
            prompt = next((run_root / "packets").glob("*product-analyst/*/prompt.md"))
            prompt_text = prompt.read_text(encoding="utf-8")
            self.assertIn("External repo intelligence", prompt_text)
            self.assertIn("GBRAIN HIT:", prompt_text)
            capture = read_json(
                run_root / "artifacts" / "delivery" / "external-capture.json"
            )
            self.assertTrue(capture["summary"]["passed"])
            self.assertIn("CAPTURED:COMPLETE", capture["records"][0]["stdout"])

    def test_gitnexus_lanes_run_against_workspace_not_source_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                "gbrain_search_command = " + _toml_array(_gbrain_search_command()),
            )
            analyze_command, status_command = _gitnexus_workspace_marker_commands()
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(analyze_command),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = " + _toml_array(status_command),
            )
            config.write_text(text, encoding="utf-8")

            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.workspace = orchestrator.mirror.create()
            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                external = orchestrator._external_intelligence("brief", {"files": []})

            self.assertIn("gitnexus-analyze", external["summary"]["passed"])
            self.assertIn("gitnexus-status", external["summary"]["passed"])
            self.assertFalse((repo / ".gitnexus-marker").exists())
            self.assertFalse((repo / ".gitnexus-status-arg").exists())
            self.assertFalse((repo / ".gitnexus-status-cwd").exists())
            gitnexus_workspace = orchestrator.run_root / "gitnexus-workspace"
            self.assertFalse((orchestrator.workspace / ".gitnexus-marker").exists())
            self.assertFalse((orchestrator.workspace / ".gitnexus-status-arg").exists())
            self.assertFalse((orchestrator.workspace / ".gitnexus-status-cwd").exists())
            self.assertTrue((gitnexus_workspace / ".gitnexus-marker").is_file())
            self.assertTrue((gitnexus_workspace / ".gitnexus-status-arg").is_file())
            self.assertTrue((gitnexus_workspace / ".gitnexus-status-cwd").is_file())

    def test_gbrain_search_is_filtered_to_exact_repo_source(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                "gbrain_search_command = "
                + _toml_array(_gbrain_search_with_top_level_command()),
            )
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
            )
            config.write_text(text, encoding="utf-8")

            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.workspace = orchestrator.mirror.create()
            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                external = orchestrator._external_intelligence("brief", {"files": []})

            gbrain = [item for item in external["records"] if item["name"] == "gbrain-search"][0]
            self.assertTrue(gbrain["ok"], gbrain)
            self.assertIn("GBRAIN HIT", gbrain["stdout"])
            self.assertNotIn("SECRET OTHER SOURCE", gbrain["stdout"])
            self.assertNotIn("SECRET OTHER SOURCE SUMMARY", gbrain["stdout"])
            self.assertEqual(gbrain["gbrain_source_scope"]["kept"], 1)
            self.assertEqual(gbrain["gbrain_source_scope"]["dropped"], 1)

    def test_gbrain_search_accepts_file_paths_inside_exact_repo_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._fixture_repo(root)
            sibling = root / "other-product" / "README.md"
            source_item = {
                "name": "gbrain",
                "ok": True,
                "detail": "test repo path source is mapped",
                "next": "",
                "required": True,
                "matched_sources": [{"path": str(repo)}],
            }
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                "gbrain_search_command = "
                + _toml_array(
                    _gbrain_path_search_command(
                        repo / "src" / "app.py",
                        repo.parent,
                        sibling,
                    )
                ),
            )
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
            )
            config.write_text(text, encoding="utf-8")

            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.workspace = orchestrator.mirror.create()
            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=source_item):
                external = orchestrator._external_intelligence("brief", {"files": []})

            gbrain = [item for item in external["records"] if item["name"] == "gbrain-search"][0]
            self.assertTrue(gbrain["ok"], gbrain)
            self.assertIn("CHILD REPO HIT", gbrain["stdout"])
            self.assertNotIn("PARENT SOURCE LEAK", gbrain["stdout"])
            self.assertNotIn("SIBLING SOURCE LEAK", gbrain["stdout"])
            self.assertEqual(gbrain["gbrain_source_scope"]["kept"], 1)
            self.assertEqual(gbrain["gbrain_source_scope"]["dropped"], 2)

    def test_run_blocks_without_exact_gbrain_repo_source(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            gbrain_status = {
                "ok": True,
                "status": {
                    "source_count": 1,
                    "sources": [{"id": "other", "path": str(repo.parent)}],
                },
            }

            with patch("manageroo.readiness.gbrain_setup_status", return_value=gbrain_status):
                with self.assertRaisesRegex(ValidationError, "Required GBrain repo source is not ready"):
                    Orchestrator(repo, adapter=MockAdapter()).run(
                        brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                        mode="build",
                        apply_on_success=True,
                    )

            source_files = sorted(
                (repo / ".manageroo" / "runs").glob("*/artifacts/discovery/gbrain-source-readiness.json")
            )
            self.assertTrue(source_files)
            source = read_json(source_files[-1])
            self.assertFalse(source["ok"])
            self.assertIn("none match this repo", source["detail"])

    def test_direct_run_blocks_repo_local_required_template_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            marker = repo / "repo-local-template-ran.txt"
            tools = repo / "tools"
            tools.mkdir()
            evil = tools / "evil-gbrain"
            evil.write_text(
                "#!/bin/sh\n"
                f"printf ran > {marker}\n"
                "printf '{}\\n'\n",
                encoding="utf-8",
            )
            evil.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = "\n".join(
                "gbrain_readiness_probe_command = []"
                if line.startswith("gbrain_readiness_probe_command = ")
                else line
                for line in text.splitlines()
            ) + "\n"
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                'gbrain_search_command = ["tools/evil-gbrain", "search", "{query}"]',
            )
            text = text.replace(
                'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]',
                "gbrain_capture_command = " + _toml_array(_text_command("gbrain-capture", "GBRAIN CAPTURE OK")),
            )
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
            )
            config.write_text(text, encoding="utf-8")

            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.workspace = orchestrator.mirror.create()
            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                with self.assertRaisesRegex(ValidationError, "Required stack command readiness failed"):
                    orchestrator._external_intelligence("brief", {"files": []})
            self.assertFalse(marker.exists())

    def test_required_external_tool_failure_blocks_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                "gbrain_search_command = " + _toml_array(_gbrain_search_command()),
            )
            text = text.replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
            )
            text = text.replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                "gitnexus_status_command = "
                + _toml_array(_gitnexus_status_command("GITNEXUS REQUIRED MISS", exit_code=7)),
            )
            config.write_text(text, encoding="utf-8")

            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                with self.assertRaisesRegex(ValidationError, "Required repo-intelligence lane failed"):
                    Orchestrator(repo, adapter=MockAdapter()).run(
                        brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                        mode="build",
                        apply_on_success=True,
                    )

            external_files = sorted((repo / ".manageroo" / "runs").glob("*/artifacts/discovery/external-intelligence.json"))
            self.assertTrue(external_files)
            external = read_json(external_files[-1])
            self.assertIn("gitnexus-status", external["summary"]["failed_required"])
            self.assertNotIn("gitnexus-status", external["summary"]["failed_optional"])
            run_id = external_files[-1].parents[2].name
            learning = read_json(
                repo
                / ".manageroo"
                / "runs"
                / run_id
                / "artifacts"
                / "learning"
                / "improvement-cards.json"
            )
            titles = [card["title"] for card in learning["cards"]]
            self.assertIn("Fix required repo intelligence tools that failed", titles)

            with self.assertRaisesRegex(ValidationError, "existing run artifact"):
                Orchestrator(
                    repo,
                    adapter=MockAdapter(),
                    run_id=run_id,
                    continue_existing=True,
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )

    def test_legacy_optional_external_intelligence_artifact_blocks_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            orchestrator.artifacts.write_json(
                "discovery/external-intelligence.json",
                {
                    "summary": {
                        "passed": ["gbrain-search", "gitnexus-analyze"],
                        "failed_optional": ["gitnexus-status"],
                    },
                    "records": [],
                },
                lock=True,
            )
            orchestrator.continuing = True

            with self.assertRaisesRegex(ValidationError, "legacy optional failure"):
                orchestrator._external_intelligence("brief", {"files": []})

    def test_required_capture_tool_failure_blocks_before_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            capture_state = Path(temp) / "capture-state.txt"
            failed_capture = _toml_array(_failing_then_recovered_capture_command(capture_state))
            replacements = {
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]':
                    "gbrain_search_command = " + _toml_array(_gbrain_search_command()),
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]':
                    "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
                'gitnexus_status_command = ["gitnexus", "status"]':
                    "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
                'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]':
                    "gbrain_capture_command = " + failed_capture,
            }
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            config.write_text(text, encoding="utf-8")

            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                with self.assertRaisesRegex(ValidationError, "Required external capture lane failed"):
                    Orchestrator(repo, adapter=MockAdapter()).run(
                        brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                        mode="build",
                        apply_on_success=True,
                    )

            capture_files = sorted((repo / ".manageroo" / "runs").glob("*/artifacts/delivery/external-capture.json"))
            self.assertTrue(capture_files)
            run_root = capture_files[-1].parents[2]
            self.assertFalse((repo / "manageroo_fixture.txt").exists())
            final_result_path = run_root / "delivery" / "final-result.json"
            self.assertTrue(final_result_path.exists())
            final_result = read_json(final_result_path)
            self.assertFalse(final_result["applied_to_source"])
            report_path = run_root / "delivery" / "FINAL-REPORT.md"
            self.assertIn("**Status:** **BLOCKED**", report_path.read_text(encoding="utf-8"))
            capture = read_json(capture_files[-1])
            self.assertIn("gbrain-capture", capture["summary"]["failed_required"])
            self.assertEqual(capture["summary"]["failed_optional"], [])

            class ExplodingAdapter(MockAdapter):
                def run(self, *args, **kwargs):
                    raise AssertionError("continuing blocked capture should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=run_root.name,
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )
            self.assertTrue(continued["applied_to_source"])
            self.assertTrue(continued["external_capture"]["summary"]["passed"])
            self.assertIn("**Status:** **COMPLETE**", capture_state.read_text(encoding="utf-8"))
            self.assertEqual(
                (repo / "manageroo_fixture.txt").read_text(encoding="utf-8"),
                "MANAGEROO deterministic fixture completed\n",
            )

    def test_empty_required_capture_tool_blocks_direct_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            replacements = {
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]':
                    "gbrain_search_command = " + _toml_array(_gbrain_search_command()),
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]':
                    "gitnexus_analyze_command = " + _toml_array(_gitnexus_analyze_command()),
                'gitnexus_status_command = ["gitnexus", "status"]':
                    "gitnexus_status_command = " + _toml_array(_gitnexus_status_command()),
                'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]':
                    "gbrain_capture_command = []",
            }
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            config.write_text(text, encoding="utf-8")

            with patch("manageroo.orchestrator.gbrain_repo_source_item", return_value=GBRAIN_SOURCE_OK):
                with self.assertRaisesRegex(ValidationError, "Required stack command readiness failed"):
                    Orchestrator(repo, adapter=MockAdapter()).run(
                        brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                        mode="build",
                        apply_on_success=False,
                    )

            capture_files = sorted((repo / ".manageroo" / "runs").glob("*/artifacts/delivery/external-capture.json"))
            self.assertFalse(capture_files)


if __name__ == "__main__":
    unittest.main()
