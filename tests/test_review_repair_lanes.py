import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from manageroo.adapters.mock import MockAdapter
from manageroo.errors import ValidationError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json


ROOT = Path(__file__).resolve().parents[1]


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


def _load_installer_module():
    spec = importlib.util.spec_from_file_location(
        "manageroo_install_script",
        ROOT / "scripts" / "install.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ReviewRepairLaneTests(unittest.TestCase):
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

    def test_docs_and_router_skill_lock_command_owned_lane_rule(self):
        docs = (ROOT / "docs" / "REVIEW_REPAIR_LANES.md").read_text(encoding="utf-8")
        skill = (
            ROOT
            / "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("command-owned repair lanes", docs)
        self.assertIn("must not freehand fixes", docs)
        self.assertIn("Run the configured AUTOREVIEW command", skill)
        self.assertIn("Run the configured Clawpatch command", skill)
        self.assertIn("must not freehand fixes", skill)

    def test_configured_external_lane_runs_as_command_owned_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "autoreview_command = []",
                "autoreview_command = "
                + _toml_array(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import pathlib, sys; "
                            "state = pathlib.Path(sys.argv[1]); "
                            "state.mkdir(parents=True, exist_ok=True); "
                            "(state / 'autoreview.txt').write_text('ok', encoding='utf-8'); "
                            "print('AUTOREVIEW LANE')"
                        ),
                        "{external_state_dir}",
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
            external = read_json(run_root / "artifacts" / "review" / "external-review-repair.json")
            self.assertTrue(external["summary"]["command_owned_repair_lanes"])
            self.assertFalse(external["summary"]["ai_freehand_repair_allowed"])
            self.assertIn("autoreview", external["summary"]["passed"])
            self.assertIn("AUTOREVIEW LANE", external["records"][0]["stdout"])
            self.assertTrue(
                (run_root / "artifacts" / "review" / "external-state" / "autoreview.txt").is_file()
            )

    def test_external_lane_failure_blocks_without_ai_repair_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "clawpatch_command = []",
                "clawpatch_command = "
                + _toml_array([sys.executable, "-c", "print('CLAWPATCH FAIL'); raise SystemExit(7)"]),
            )
            config.write_text(text, encoding="utf-8")

            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            with self.assertRaises(ValidationError):
                orchestrator.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )

            external = read_json(
                orchestrator.run_root / "artifacts" / "review" / "external-review-repair.json"
            )
            self.assertIn("clawpatch", external["summary"]["failed"])
            self.assertIn("not fed to the AI repairer", external["note"])
            self.assertIn("CLAWPATCH FAIL", external["records"][0]["stdout"])

    def test_installer_exposes_official_gbrain_lane_without_guessing_setup(self):
        installer = _load_installer_module()
        with mock.patch.object(installer, "command_version", return_value="not installed"):
            result = installer.install_gbrain([], lane="official")
        self.assertFalse(result["installed"])
        self.assertEqual(result["lane"], "official-agent-protocol")
        self.assertIn("INSTALL_FOR_AGENTS.md", result["official_protocol_url"])
        self.assertIn("API keys", result["guidance"])

    def test_installed_clawpatch_checks_codex_provider_without_installing_pnpm(self):
        installer = _load_installer_module()

        def fake_which(name):
            if name == "clawpatch":
                return "/usr/local/bin/clawpatch"
            if name == "codex":
                return "/usr/local/bin/codex"
            return None

        with (
            mock.patch.object(installer, "command_version", return_value="clawpatch 1.0.0"),
            mock.patch.object(installer.shutil, "which", side_effect=fake_which),
            mock.patch.object(installer, "ensure_pnpm", side_effect=AssertionError("pnpm not needed")),
            mock.patch.object(installer, "optional_run", return_value={"ok": True, "argv": ["clawpatch", "doctor"]}),
            mock.patch.object(
                installer,
                "probe_command",
                return_value={"ok": False, "exit_code": 1, "argv": ["codex", "login", "status"], "output": ""},
            ),
        ):
            result = installer.install_clawpatch([], codex_login_mode="skip")

        self.assertTrue(result["installed"])
        self.assertFalse(result["configured"])
        self.assertIn("codex login", result["next_commands"])
        self.assertIn("clawpatch doctor", result["next_commands"])


if __name__ == "__main__":
    unittest.main()
