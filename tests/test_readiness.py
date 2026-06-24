import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.project import initialize_project
from manageroo.readiness import format_readiness, helper_skill_items, readiness


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


GBRAIN_SEARCH_TEMPLATE = 'gbrain_search_command = ["tools/gbrain-wrapper", "search", "{query}"]'
GBRAIN_CAPTURE_TEMPLATE = 'gbrain_capture_command = ["tools/gbrain-wrapper", "capture", "{report_file}"]'
GITNEXUS_ANALYZE_TEMPLATE = 'gitnexus_analyze_command = ["tools/gitnexus-wrapper", "analyze", "{repo}"]'
GITNEXUS_STATUS_TEMPLATE = 'gitnexus_status_command = ["tools/gitnexus-wrapper", "status"]'


def _gbrain_status_for(repo: Path) -> dict:
    return {
        "ok": True,
        "status": {
            "source_count": 1,
            "sources": [{"id": "fixture", "path": str(repo)}],
        },
    }


def _gbrain_status_without_repo_source(repo: Path) -> dict:
    return {
        "ok": True,
        "status": {
            "source_count": 1,
            "sources": [{"id": "other", "path": str(repo.parent / "other")}],
        },
    }


class ReadinessTests(unittest.TestCase):
    def _which_stack(self, name: str) -> str | None:
        if name in {"git", "gbrain", "gitnexus", "codex"}:
            return f"/usr/bin/{name}"
        return None

    def _ready_repo(self, root: Path, brief: str) -> Path:
        repo = root
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        tools = repo / "tools"
        tools.mkdir()
        for name in ("gbrain-wrapper", "gitnexus-wrapper"):
            wrapper = tools / name
            wrapper.write_text("#!/bin/sh\nprintf '%s\\n' readiness-probe-ok\n", encoding="utf-8")
            wrapper.chmod(0o755)
        config = repo / ".manageroo" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            .replace(
                'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                GBRAIN_SEARCH_TEMPLATE,
            )
            .replace(
                'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]',
                GBRAIN_CAPTURE_TEMPLATE,
            )
            .replace(
                'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
                GITNEXUS_ANALYZE_TEMPLATE,
            )
            .replace(
                'gitnexus_status_command = ["gitnexus", "status"]',
                GITNEXUS_STATUS_TEMPLATE,
            )
            + "\n[[verification.gates]]\n"
            + 'id = "smoke"\n'
            + 'kind = "test"\n'
            + "required = true\n"
            + "timeout_seconds = 60\n"
            + 'argv = ["python3", "-m", "compileall", "."]\n',
            encoding="utf-8",
        )
        (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(brief, encoding="utf-8")
        return repo

    def _with_operator_stack_commands(self, text: str, operator_bin: Path) -> str:
        gbrain_command = operator_bin / "gbrain-command"
        gitnexus_command = operator_bin / "gitnexus-command"
        for command in (gbrain_command, gitnexus_command):
            command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command.chmod(0o755)
        replacements = {
            GBRAIN_SEARCH_TEMPLATE:
                "gbrain_search_command = " + _toml_array([str(gbrain_command), "search", "{query}"]),
            GBRAIN_CAPTURE_TEMPLATE:
                "gbrain_capture_command = " + _toml_array([str(gbrain_command), "capture", "{report_file}"]),
            GITNEXUS_ANALYZE_TEMPLATE:
                "gitnexus_analyze_command = " + _toml_array([str(gitnexus_command), "analyze", "{workspace}"]),
            GITNEXUS_STATUS_TEMPLATE:
                "gitnexus_status_command = " + _toml_array([str(gitnexus_command), "status"]),
        }
        for original, replacement in replacements.items():
            text = text.replace(original, replacement)
        return text

    def test_missing_core_helper_skill_is_required(self):
        with patch(
            "manageroo.readiness.CORE_HELPER_SKILLS",
            {"missing-required-helper": "skills/missing-required-helper/SKILL.md"},
        ):
            items = helper_skill_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "skill-pack:missing-required-helper")
        self.assertFalse(items[0]["ok"])
        self.assertTrue(items[0]["required"])
        self.assertEqual(items[0]["severity"], "required")

    def test_readiness_reports_exact_next_step_for_missing_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[
                    {
                        "name": "helper:test",
                        "ok": True,
                        "detail": "mock",
                        "next": "",
                        "required": True,
                    }
                ],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            checks = [item for item in report["items"] if item["name"] == "checks"][0]
            self.assertFalse(checks["ok"])
            self.assertEqual(checks["next"], "manageroo checks suggest --apply-first")
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertTrue(gbrain["required"])

    def test_readiness_reports_missing_project_memory_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PROJECT-MEMORY.md").unlink()
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[
                    {
                        "name": "helper:test",
                        "ok": True,
                        "detail": "mock",
                        "next": "",
                        "required": True,
                    }
                ],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            memory = [item for item in report["items"] if item["name"] == "project memory"][0]
            self.assertFalse(memory["ok"])
            self.assertIn("manageroo memory init", memory["next"])

    def test_explicit_document_request_blocks_when_document_lane_is_unconfigured(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(
                Path(temp),
                "# Product brief\n\nClean up this PDF transcript and preserve exact wording.\n",
            )
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            lane = [item for item in report["items"] if item["name"] == "document/prose lane"][0]
            self.assertFalse(lane["ok"])
            self.assertTrue(lane["required"])
            self.assertIn("document_analysis_command", lane["detail"])
            self.assertIn("document_analysis_command", lane["next"])
            self.assertIn("ACTION document/prose lane", format_readiness(report))

    def test_repo_media_without_explicit_request_warns_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake the app work.\n")
            media = repo / "assets" / "screenshot.png"
            media.parent.mkdir()
            media.write_bytes(b"\x89PNG\r\n\x1a\n")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ), patch(
                "manageroo.readiness._stack_command_item",
                side_effect=lambda repo, config, name, lane, keys, probe_keys=None, probe_command_key="", **kwargs: {
                    "name": name,
                    "ok": True,
                    "detail": "mock stack ok",
                    "next": "",
                    "required": True,
                    "severity": "required",
                },
            ):
                report = readiness(repo)
            self.assertTrue(report["ok"])
            lane = [item for item in report["items"] if item["name"] == "document/prose lane"][0]
            self.assertFalse(lane["ok"])
            self.assertFalse(lane["required"])
            self.assertEqual(lane["severity"], "warning")
            self.assertIn("repo contains", lane["detail"])
            self.assertIn("WARN document/prose lane", format_readiness(report))

    def test_memory_request_requires_gbrain_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(
                Path(temp),
                "# Product brief\n\nUse GBrain memory and prior decisions before changing this.\n",
            )
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["ok"])
            self.assertTrue(gbrain["required"])
            self.assertIn("brief asks for memory", gbrain["detail"])

    def test_gbrain_source_must_match_current_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_path = root / "repo"
            repo_path.mkdir()
            repo = self._ready_repo(repo_path, "# Product brief\n\nMake it work.\n")
            unrelated = root / "other-project"
            unrelated.mkdir()
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={
                    "ok": True,
                    "status": {
                        "source_count": 1,
                        "sources": [{"id": "other", "path": str(unrelated)}],
                    },
                },
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["ok"])
            self.assertIn("none match this repo", gbrain["detail"])
            self.assertIn(f"--path {repo}", gbrain["next"])

    def test_broad_parent_gbrain_source_does_not_match_current_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_path = root / "repo"
            repo_path.mkdir()
            repo = self._ready_repo(repo_path, "# Product brief\n\nMake it work.\n")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={
                    "ok": True,
                    "status": {
                        "source_count": 1,
                        "sources": [{"id": "broad", "path": str(root)}],
                    },
                },
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["ok"])
            self.assertIn("none match this repo", gbrain["detail"])

    def test_nested_gbrain_source_does_not_match_whole_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            docs = repo / "docs"
            docs.mkdir()
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={
                    "ok": True,
                    "status": {
                        "source_count": 1,
                        "sources": [{"id": "docs-only", "path": str(docs)}],
                    },
                },
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            self.assertFalse(report["ok"])
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(gbrain["ok"])
            self.assertIn("none match this repo", gbrain["detail"])

    def test_gbrain_status_does_not_crash_without_target_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={
                    "ok": True,
                    "status": {
                        "source_count": 1,
                        "sources": [{"id": "fixture", "path": str(path)}],
                    },
                },
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(path)
            self.assertFalse(report["ok"])
            target = [item for item in report["items"] if item["name"] == "target repo"][0]
            gbrain = [item for item in report["items"] if item["name"] == "gbrain"][0]
            self.assertFalse(target["ok"])
            self.assertFalse(gbrain["ok"])
            self.assertIn("no target repo", gbrain["detail"])
            self.assertNotIn("None", gbrain["next"])

    def test_stack_command_lane_checks_configured_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                GBRAIN_SEARCH_TEMPLATE,
                'gbrain_search_command = ["definitely-missing-gbrain-wrapper", "{query}"]',
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"])
            self.assertIn("gbrain_search_command", lane["detail"])

    def test_gitnexus_readiness_probes_required_subcommands_not_only_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gitnexus_log = root / "gitnexus.log"
            gbrain.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gitnexus.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {gitnexus_log}\n"
                "if [ \"$1\" = \"--version\" ]; then exit 0; fi\n"
                "if [ \"$1\" = \"analyze\" ] "
                "&& [ -d \"$2\" ] "
                "&& [ \"$(pwd)\" = \"$2\" ] "
                "&& [ \"$3\" = \"--skip-agents-md\" ] "
                "&& [ \"$4\" = \"--skip-skills\" ]; then exit 0; fi\n"
                "if [ \"$1\" = \"analyze\" ]; then exit 7; fi\n"
                "if [ \"$1\" = \"status\" ]; then exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            lane = [item for item in report["items"] if item["name"] == "gitnexus command lane"][0]
            self.assertTrue(lane["ok"], lane)
            log_text = gitnexus_log.read_text(encoding="utf-8")
            self.assertIn("analyze ", log_text)
            self.assertIn(".manageroo/cache/readiness-probes/gitnexus-workspace", log_text)
            self.assertIn("--skip-agents-md --skip-skills", log_text)
            self.assertNotIn("analyze --help", log_text)
            self.assertIn("status", log_text)
            self.assertNotIn("--version", log_text)
            self.assertTrue(
                (repo / ".manageroo" / "cache" / "readiness-probes" / "gitnexus-workspace" / ".git").is_dir()
            )

    def test_readiness_rejects_repo_local_path_shims_for_default_stack_probes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            tools = repo / "tools"
            tools.mkdir()
            marker = repo / "repo-local-probe-ran.txt"
            for name in ("gbrain", "gitnexus"):
                shim = tools / name
                shim.write_text(
                    "#!/bin/sh\n"
                    f"printf '%s\\n' \"$0 $*\" >> {marker}\n"
                    "exit 0\n",
                    encoding="utf-8",
                )
                shim.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(tools / "gbrain")
                if name == "gitnexus":
                    return str(tools / "gitnexus")
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{tools}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            gitnexus_lane = [item for item in report["items"] if item["name"] == "gitnexus command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertFalse(gitnexus_lane["ok"], gitnexus_lane)
            self.assertIn("operator-owned outside the target repo", gbrain_lane["detail"])
            self.assertIn("operator-owned outside the target repo", gitnexus_lane["detail"])
            self.assertFalse(marker.exists())

    def test_gbrain_readiness_probes_configured_search_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
                    'gbrain_search_command = ["gbrain", "bogus-subcommand"]',
                )
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gbrain_log = root / "gbrain.log"
            gbrain.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {gbrain_log}\n"
                "if [ \"$1\" = \"bogus-subcommand\" ]; then exit 7; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"], lane)
            self.assertIn("gbrain_search_command", lane["detail"])
            self.assertNotIn(
                "bogus-subcommand",
                gbrain_log.read_text(encoding="utf-8") if gbrain_log.exists() else "",
            )

    def test_gbrain_readiness_does_not_probe_search_without_exact_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gbrain_log = root / "gbrain.log"
            gbrain.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {gbrain_log}\n"
                "printf '%s\\n' '[]'\n",
                encoding="utf-8",
            )
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                if name == "codex":
                    return "/usr/bin/codex"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_without_repo_source(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"], lane)
            self.assertIn("did not execute the search probe", lane["detail"])
            self.assertFalse(gbrain_log.exists())

    def test_gbrain_readiness_rejects_plain_text_default_search_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gbrain.write_text("#!/bin/sh\nprintf '%s\\n' 'plain gbrain output'\n", encoding="utf-8")
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"], lane)
            self.assertIn("GBrain search output must be JSON", lane["detail"])
            self.assertNotIn("plain gbrain output", json.dumps(report))

    def test_gbrain_readiness_accepts_empty_scoped_json_search_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gbrain.write_text("#!/bin/sh\nprintf '%s\\n' '{\"results\":[]}'\n", encoding="utf-8")
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertTrue(lane["ok"], lane)

    def test_readiness_probe_does_not_persist_or_surface_external_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nMake it work.\n",
                encoding="utf-8",
            )
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8")
                + "\n[[verification.gates]]\n"
                + 'id = "smoke"\n'
                + 'kind = "test"\n'
                + "required = true\n"
                + "timeout_seconds = 60\n"
                + 'argv = ["python3", "-m", "compileall", "."]\n',
                encoding="utf-8",
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            private_text = "PRIVATE_BRAIN_SNIPPET_SHOULD_NOT_ESCAPE"
            gbrain = bin_dir / "gbrain"
            gitnexus = bin_dir / "gitnexus"
            gbrain.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' {private_text}\n"
                "exit 7\n",
                encoding="utf-8",
            )
            gitnexus.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            gbrain.chmod(0o755)
            gitnexus.chmod(0o755)

            def which(name: str) -> str | None:
                if name == "gbrain":
                    return str(gbrain)
                if name == "gitnexus":
                    return str(gitnexus)
                if name == "git":
                    return "/usr/bin/git"
                return None

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=which,
            ), patch.dict(
                os.environ,
                {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
            ):
                report = readiness(repo)

            self.assertFalse(report["ok"])
            self.assertNotIn(private_text, json.dumps(report))
            self.assertFalse(
                (repo / ".manageroo" / "cache" / "readiness-command-logs").exists()
            )

    def test_stack_command_lane_blocks_absolute_configured_wrappers_without_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            tools = repo / "tools"
            absolute_gbrain = tools / "absolute-gbrain"
            absolute_gitnexus = tools / "absolute-gitnexus"
            absolute_gbrain.write_text("#!/bin/sh\nprintf '%s\\n' gbrain\n", encoding="utf-8")
            absolute_gitnexus.write_text("#!/bin/sh\nprintf '%s\\n' gitnexus\n", encoding="utf-8")
            absolute_gbrain.chmod(0o755)
            absolute_gitnexus.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            replacements = {
                GBRAIN_SEARCH_TEMPLATE:
                    "gbrain_search_command = " + _toml_array([str(absolute_gbrain), "search", "{query}"]),
                GBRAIN_CAPTURE_TEMPLATE:
                    "gbrain_capture_command = " + _toml_array([str(absolute_gbrain), "capture", "{report_file}"]),
                GITNEXUS_ANALYZE_TEMPLATE:
                    "gitnexus_analyze_command = " + _toml_array([str(absolute_gitnexus), "analyze", "{repo}"]),
                GITNEXUS_STATUS_TEMPLATE:
                    "gitnexus_status_command = " + _toml_array([str(absolute_gitnexus), "status"]),
            }
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            gitnexus_lane = [item for item in report["items"] if item["name"] == "gitnexus command lane"][0]
            self.assertFalse(gbrain_lane["ok"])
            self.assertEqual(gbrain_lane["severity"], "required")
            self.assertIn("operator-owned outside the target repo", gbrain_lane["detail"])
            self.assertFalse(gitnexus_lane["ok"])
            self.assertEqual(gitnexus_lane["severity"], "required")
            self.assertIn("operator-owned outside the target repo", gitnexus_lane["detail"])

    def test_stack_command_lane_accepts_custom_wrappers_with_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            gbrain_probe = operator_bin / "gbrain-readiness-probe"
            gitnexus_probe = operator_bin / "gitnexus-readiness-probe"
            for probe in (gbrain_probe, gitnexus_probe):
                probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                probe.chmod(0o755)
            gbrain_command = operator_bin / "gbrain-command"
            gitnexus_command = operator_bin / "gitnexus-command"
            for command in (gbrain_command, gitnexus_command):
                command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                command.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            replacements = {
                GBRAIN_SEARCH_TEMPLATE:
                    "gbrain_search_command = " + _toml_array([str(gbrain_command), "search", "{query}"]),
                GBRAIN_CAPTURE_TEMPLATE:
                    "gbrain_capture_command = " + _toml_array([str(gbrain_command), "capture", "{report_file}"]),
                GITNEXUS_ANALYZE_TEMPLATE:
                    "gitnexus_analyze_command = " + _toml_array([str(gitnexus_command), "analyze", "{workspace}"]),
                GITNEXUS_STATUS_TEMPLATE:
                    "gitnexus_status_command = " + _toml_array([str(gitnexus_command), "status"]),
            }
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(gbrain_probe), "probe"]),
            )
            text = text.replace(
                "gitnexus_readiness_probe_command = []",
                "gitnexus_readiness_probe_command = "
                + _toml_array([str(gitnexus_probe), "probe"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            gitnexus_lane = [item for item in report["items"] if item["name"] == "gitnexus command lane"][0]
            self.assertTrue(gbrain_lane["ok"], gbrain_lane)
            self.assertTrue(gitnexus_lane["ok"], gitnexus_lane)
            self.assertIn("trusted readiness probe passed", gbrain_lane["detail"])
            self.assertIn("trusted readiness probe passed", gitnexus_lane["detail"])

    def test_stack_command_lane_rejects_repo_controlled_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                'gbrain_readiness_probe_command = ["tools/gbrain-wrapper", "probe", "{source_repo}"]',
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn(
                "must be operator-owned outside the target repo",
                gbrain_lane["detail"],
            )

    def test_stack_command_lane_rejects_repo_symlink_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            probe = repo / "tools" / "symlink-probe"
            marker = repo / "symlink-probe-ran.txt"
            os.symlink("/bin/sh", probe)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(probe), "-c", f"printf ran > {marker}"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("operator-owned outside the target repo", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_shell_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            marker = repo / "shell-probe-ran.txt"
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            shell_probe = operator_bin / "sh"
            shell_probe.write_text("#!/bin/sh\nprintf ran > \"$3\"\n", encoding="utf-8")
            shell_probe.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(shell_probe), "-c", "write", str(marker)]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("shell or interpreter launcher", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_windows_shell_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            marker = repo / "windows-shell-probe-ran.txt"
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            shell_probe = operator_bin / "cmd.exe"
            shell_probe.write_text("#!/bin/sh\nprintf ran > \"$3\"\n", encoding="utf-8")
            shell_probe.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(shell_probe), "/c", "write", str(marker)]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("shell or interpreter launcher", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_shell_required_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            marker = repo / "shell-required-template-ran.txt"
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8").replace(
                GBRAIN_SEARCH_TEMPLATE,
                "gbrain_search_command = "
                + _toml_array(["/bin/sh", "-c", f"printf ran > {marker}"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("shell or interpreter launcher", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_windows_shell_required_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            marker = repo / "windows-shell-required-template-ran.txt"
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            shell_command = operator_bin / "powershell.exe"
            shell_command.write_text("#!/bin/sh\nprintf ran > \"$3\"\n", encoding="utf-8")
            shell_command.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            safe_search = "gbrain_search_command = " + _toml_array(
                [str(operator_bin / "gbrain-command"), "search", "{query}"]
            )
            text = text.replace(
                safe_search,
                "gbrain_search_command = "
                + _toml_array([str(shell_command), "-Command", "write", str(marker)]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("shell or interpreter launcher", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_versioned_python_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            python_probe = operator_bin / "python3.11"
            python_probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python_probe.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(python_probe), "-c", "print('ran')"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("shell or interpreter launcher", gbrain_lane["detail"])

    def test_stack_command_lane_rejects_repo_file_argument_to_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            probe = operator_bin / "gbrain-readiness-probe"
            probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            probe.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(probe), "tools/gbrain-wrapper"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("repo-controlled paths", gbrain_lane["detail"])

    def test_stack_command_lane_rejects_repo_directory_argument_to_trusted_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            marker = repo / "directory-probe-ran.txt"
            probe = operator_bin / "gbrain-readiness-probe"
            probe.write_text("#!/bin/sh\nprintf ran > \"$3\"\n", encoding="utf-8")
            probe.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            text = text.replace(
                "gbrain_readiness_probe_command = []",
                "gbrain_readiness_probe_command = "
                + _toml_array([str(probe), "probe", "{source_repo}"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("repo-controlled paths", gbrain_lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_rejects_repo_file_argument_to_required_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            gbrain_command = operator_bin / "gbrain-command"
            text = text.replace(
                "gbrain_search_command = " + _toml_array([str(gbrain_command), "search", "{query}"]),
                "gbrain_search_command = "
                + _toml_array([str(gbrain_command), "tools/gbrain-wrapper"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("repo-controlled paths", gbrain_lane["detail"])

    def test_stack_command_lane_rejects_repo_directory_argument_to_required_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            repo = self._ready_repo(repo, "# Product brief\n\nMake it work.\n")
            operator_bin = root / "operator-bin"
            operator_bin.mkdir()
            config = repo / ".manageroo" / "config.toml"
            text = self._with_operator_stack_commands(
                config.read_text(encoding="utf-8"),
                operator_bin,
            )
            gbrain_command = operator_bin / "gbrain-command"
            text = text.replace(
                "gbrain_search_command = " + _toml_array([str(gbrain_command), "search", "{query}"]),
                "gbrain_search_command = "
                + _toml_array([str(gbrain_command), "{source_repo}"]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertIn("repo-controlled paths", gbrain_lane["detail"])

    def test_readiness_does_not_execute_gbrain_capture_template(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            marker = repo / "capture-probe-ran.txt"
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                GBRAIN_CAPTURE_TEMPLATE,
                "gbrain_capture_command = "
                + _toml_array([
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran'); sys.exit(13)",
                    str(marker),
                ]),
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"])
            self.assertEqual(lane["severity"], "required")
            self.assertIn("operator-owned outside the target repo", lane["detail"])
            self.assertFalse(marker.exists())

    def test_stack_command_lane_resolves_relative_wrappers_from_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            tools = repo / "tools"
            tools.mkdir(exist_ok=True)
            for name in ("gbrain-wrapper", "gitnexus-wrapper"):
                wrapper = tools / f"alt-{name}"
                wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                wrapper.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            replacements = {
                GBRAIN_SEARCH_TEMPLATE:
                    'gbrain_search_command = ["tools/alt-gbrain-wrapper", "{query}"]',
                GBRAIN_CAPTURE_TEMPLATE:
                    'gbrain_capture_command = ["tools/alt-gbrain-wrapper", "capture", "{report_file}"]',
                GITNEXUS_ANALYZE_TEMPLATE:
                    'gitnexus_analyze_command = ["tools/alt-gitnexus-wrapper", "{repo}"]',
                GITNEXUS_STATUS_TEMPLATE:
                    'gitnexus_status_command = ["tools/alt-gitnexus-wrapper", "status"]',
            }
            for original, replacement in replacements.items():
                text = text.replace(original, replacement)
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value=None,
            ):
                report = readiness(repo)
            gbrain_lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            gitnexus_lane = [item for item in report["items"] if item["name"] == "gitnexus command lane"][0]
            self.assertFalse(gbrain_lane["ok"], gbrain_lane)
            self.assertEqual(gbrain_lane["severity"], "required")
            self.assertFalse(gitnexus_lane["ok"], gitnexus_lane)
            self.assertEqual(gitnexus_lane["severity"], "required")

    def test_stack_command_lane_rejects_non_executable_relative_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            tools = repo / "tools"
            tools.mkdir(exist_ok=True)
            wrapper = tools / "gbrain-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wrapper.chmod(0o644)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace(
                GBRAIN_SEARCH_TEMPLATE,
                'gbrain_search_command = ["tools/gbrain-wrapper", "{query}"]',
            )
            config.write_text(text, encoding="utf-8")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"])
            self.assertIn("gbrain_search_command", lane["detail"])

    def test_stack_command_lane_blocks_executable_wrapper_without_running_it(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            wrapper = repo / "tools" / "gbrain-wrapper"
            wrapper.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
            wrapper.chmod(0o755)
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            lane = [item for item in report["items"] if item["name"] == "gbrain command lane"][0]
            self.assertFalse(lane["ok"])
            self.assertEqual(lane["severity"], "required")
            self.assertIn("operator-owned outside the target repo", lane["detail"])

    def test_selected_agent_uses_adapter_doctor_not_only_executable_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = text.replace('adapter = "mock"', 'adapter = "codex"')
            text = text.replace('executable = "mock"', 'executable = "codex"')
            config.write_text(text, encoding="utf-8")

            class BadDoctorAdapter:
                def doctor(self, cwd):
                    return {
                        "ok": False,
                        "adapter": "codex",
                        "error": "missing required exec flags",
                    }

            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                return_value="/usr/bin/codex",
            ), patch(
                "manageroo.readiness.build_adapter",
                return_value=BadDoctorAdapter(),
                create=True,
            ):
                report = readiness(repo)
            selected = [item for item in report["items"] if item["name"] == "selected agent"][0]
            self.assertFalse(selected["ok"])
            self.assertIn("doctor", selected["detail"])
            self.assertIn("missing required exec flags", selected["detail"])

    def test_compile_only_check_is_labeled_weak(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._ready_repo(Path(temp), "# Product brief\n\nMake it work.\n")
            with patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value={"ok": False, "status": {"source_count": 0}},
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ):
                report = readiness(repo)
            weak = [item for item in report["items"] if item["name"] == "check strength"][0]
            self.assertFalse(weak["ok"])
            self.assertFalse(weak["required"])
            self.assertEqual(weak["severity"], "warning")
            self.assertIn("compile-only", weak["detail"])


if __name__ == "__main__":
    unittest.main()
