import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.mock import MockAdapter
from manageroo.artifacts import ArtifactStore
from manageroo.chiptune import ThemePlayback
from manageroo.context import ContextCompiler, ContextRequest
from manageroo.detector import detect_gates
from manageroo.entrypoint import _run_root
from manageroo.errors import SafetyError
from manageroo.file_inspection import pdf_text_extract
from manageroo.gbrain_setup import format_gbrain_setup, gbrain_setup_status
from manageroo.install_status import format_stack_status, read_install_lock, stack_status, summarize_external_tools
from manageroo.integrations import ObsidianIntegration
from manageroo.jobs import JobStore, JobStatus
from manageroo.policy import CommandPolicy, ScopePolicy
from manageroo.project import create_project_repo
from manageroo.project_memory import ensure_project_memory
from manageroo.runner import CommandResult, CommandRunner
from manageroo.skill_pack import scan_skill_folder
from manageroo.stack_doctor import _safe_probe_record
from manageroo.workspace import WorkspaceMirror


class ClawpatchRegressionTests(unittest.TestCase):
    def test_artifact_store_rejects_absolute_traversal_and_empty_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            outside = Path(temp) / "outside.txt"
            for value in ("../outside.txt", str(outside.resolve()), ""):
                with self.assertRaises(SafetyError):
                    store.write_text(value, "x")
            self.assertFalse(outside.exists())

    def test_context_packets_are_contained_and_empty_files_compile(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            packets = base / "packets"
            repo.mkdir()
            (repo / "empty.txt").write_text("", encoding="utf-8")
            compiler = ContextCompiler(
                repo,
                packets,
                max_input_tokens=2000,
                reserve_output_tokens=200,
                chars_per_token=4.0,
                max_single_file_tokens=1000,
            )
            with self.assertRaises(SafetyError):
                compiler.compile("../escape", instructions="x", requests=[])
            with self.assertRaises(SafetyError):
                compiler.compile(str((base / "absolute").resolve()), instructions="x", requests=[])
            packet = compiler.compile(
                "empty-packet",
                instructions="Read it.",
                requests=[ContextRequest("empty.txt", "required", required=True)],
            )
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][0]["start_line"], 1)
            self.assertEqual(manifest["entries"][0]["end_line"], 0)
            self.assertTrue(manifest["entries"][0]["source_sha256"])

    def test_command_policy_rejects_path_and_python_prefix_spoofing(self):
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["/tmp/python-backdoor"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("git",)).validate(["./git"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["python-backdoor"])
        CommandPolicy(("python",)).validate(["python3", "-V"])
        CommandPolicy(("python",)).validate(["python3.11", "-V"])

    def test_scope_policy_fails_closed_and_rejects_traversal(self):
        with self.assertRaises(SafetyError):
            ScopePolicy(()).validate_paths(["README.md"])
        with self.assertRaises(SafetyError):
            ScopePolicy(("src/**",)).validate_paths(["src/../docs/secret.md"])

    def test_decision_run_ids_cannot_escape_run_root(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for run_id in ("../outside", "/tmp/outside", "a/b", ""):
                with self.assertRaises(SafetyError):
                    _run_root(repo, run_id)
            path = _run_root(repo, "run-123")
            self.assertEqual(path, repo.resolve() / ".manageroo" / "runs" / "run-123")

    def test_completed_job_rejects_tampered_artifact_with_recorded_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = JobStore(root / "run")
            artifacts = root / "artifacts"
            artifacts.mkdir()
            artifact = artifacts / "result.json"
            artifact.write_text('{"value": 1}\n', encoding="utf-8")
            store.create_or_load_job("job", role="reviewer", schema="x", instructions="x")
            store.complete_job("job", output_artifact="result.json", data={"value": 1}, artifact_path=artifact)
            artifact.write_text('{"value": 2}\n', encoding="utf-8")
            self.assertIsNone(store.completed_data("job", artifacts))
            self.assertEqual(store.load_job("job").status, JobStatus.PENDING.value)
            self.assertEqual(store.load_job("job").failure_type, "StaleArtifact")

    def test_obsidian_export_rejects_absolute_and_parent_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            vault.mkdir()
            integration = ObsidianIntegration(str(vault), "exports")
            with self.assertRaises(SafetyError):
                integration.export("../outside.md", "x")
            with self.assertRaises(SafetyError):
                integration.export(str((Path(temp) / "absolute.md").resolve()), "x")
            destination = integration.export("safe.md", "ok")
            self.assertEqual(destination, (vault / "exports" / "safe.md").resolve())

    def test_pyright_configuration_adds_typecheck_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "pyproject.toml").write_text("[tool.pyright]\ntypeCheckingMode = 'basic'\n", encoding="utf-8")
            gates = detect_gates(repo)
            pyright = next(gate for gate in gates if gate["id"] == "pyright")
            self.assertEqual(pyright["kind"], "typecheck")
            self.assertEqual(pyright["argv"][:2], [sys.executable, "-m"])

    def test_gbrain_failed_add_does_not_run_sync_and_headline_is_action(self):
        calls = []

        def fake_probe(argv, timeout_seconds=60):
            calls.append(argv)
            if "sources" in argv and "add" in argv:
                return {"ok": False, "exit_code": 1, "argv": argv, "output": "add failed"}
            if "config" in argv:
                return {"ok": True, "exit_code": 0, "argv": argv, "output": "  engine: pglite\n"}
            if "status" in argv:
                return {"ok": True, "exit_code": 0, "argv": argv, "output": '{"sync":{"sources":[]}}'}
            return {"ok": True, "exit_code": 0, "argv": argv, "output": ""}

        with tempfile.TemporaryDirectory() as temp, patch("manageroo.gbrain_setup.shutil.which", return_value="gbrain"), patch(
            "manageroo.gbrain_setup.run_probe", side_effect=fake_probe
        ):
            report = gbrain_setup_status(source_id="site", source_path=Path(temp), apply=True, sync=True)
        self.assertFalse(any("sync" in call for call in calls))
        self.assertTrue(format_gbrain_setup(report).startswith("GBRAIN: ACTION"))

    def test_explicitly_unconfigured_installed_tool_requires_action(self):
        summary = summarize_external_tools([{"name": "gitnexus", "installed": True, "configured": False}])
        self.assertTrue(summary["items"][0]["needs_action"])
        text = format_stack_status({
            "ok": True,
            "lock_path": "x",
            "launcher": "manageroo",
            "stack_summary": summary,
        })
        self.assertIn("ACTION gitnexus", text)

    def test_malformed_install_lock_returns_structured_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "install-lock.json"
            path.write_text("{", encoding="utf-8")
            result = read_install_lock(path)
            self.assertFalse(result["ok"])
            self.assertIn("malformed", result["error"])
            self.assertTrue(result["next_commands"])

    def test_project_memory_invalid_utf8_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            path = repo / ".manageroo" / "PROJECT-MEMORY.md"
            path.parent.mkdir(parents=True)
            original = b"prefix\xffsuffix"
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                ensure_project_memory(repo, notes=["new note"])
            self.assertEqual(path.read_bytes(), original)

    def test_existing_empty_git_repo_can_receive_requested_starter(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            result = create_project_repo(repo, starter="static-site", title="Demo")
            self.assertEqual(result["status"], "scaffolded-existing-git")
            self.assertTrue((repo / "index.html").is_file())
            self.assertTrue((repo / "styles.css").is_file())

    def test_skill_scan_refuses_symlinked_target_root(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "demo").mkdir(parents=True)
            (source / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
            real_target = root / "real-skills"
            real_target.mkdir()
            linked_target = root / "skills"
            try:
                os.symlink(real_target, linked_target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaises(ValueError):
                scan_skill_folder(source, skills_dir=linked_target)
            self.assertFalse((real_target / "demo" / "SKILL.md").exists())

    def test_workspace_detects_mode_only_source_drift(self):
        if os.name == "nt":
            self.skipTest("POSIX mode-bit regression")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            source = repo / "tool.sh"
            source.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            source.chmod(0o644)
            subprocess.run(["git", "add", "tool.sh"], cwd=repo, check=True)
            mirror = WorkspaceMirror(repo, root / "run", CommandRunner())
            mirror.create()
            source.chmod(0o755)
            with self.assertRaises(SafetyError):
                mirror.assert_source_unchanged()

    def test_failed_stack_doctor_probe_redacts_secrets(self):
        record = _safe_probe_record(
            {
                "ok": False,
                "exit_code": 1,
                "argv": ["tool", "api_key=abc123"],
                "output": "token=secret-value Bearer deadbeef password=hunter2",
            }
        )
        serialized = json.dumps(record)
        for secret in ("abc123", "secret-value", "deadbeef", "hunter2"):
            self.assertNotIn(secret, serialized)
        self.assertIn("<REDACTED>", serialized)

    def test_mock_adapter_rejects_target_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            schema = root / "schema.json"
            schema.write_text('{"type":"object"}', encoding="utf-8")
            output = root / "output.json"
            request = AgentRequest(
                role="implementer",
                prompt_path=root / "prompt.md",
                schema_path=schema,
                output_path=output,
                cwd=root,
                sandbox="workspace-write",
                timeout_seconds=60,
                metadata={"task": {"allowed_paths": ["../outside.txt"]}},
            )
            request.prompt_path.write_text("x", encoding="utf-8")
            with self.assertRaises(SafetyError):
                MockAdapter().run(request)
            self.assertFalse((root.parent / "outside.txt").exists())

    def test_theme_playback_cleans_temp_directory_without_player(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp) / "manageroo-music-test"
            playback = ThemePlayback()
            with patch("manageroo.chiptune.sys.stdout.isatty", return_value=True), patch(
                "manageroo.chiptune.tempfile.mkdtemp", return_value=str(temp_root)
            ), patch("manageroo.chiptune._player_command", return_value=None), patch.dict(
                os.environ, {"MANAGEROO_MUSIC": "1"}, clear=False
            ):
                os.environ.pop("CI", None)
                self.assertFalse(playback.start())
            self.assertFalse(temp_root.exists())
            self.assertIsNone(playback.path)

    def test_stack_status_finds_helper_skill_in_configured_skill_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skills = root / "skills"
            skill = skills / "pimp-my-prompt" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# skill\n", encoding="utf-8")
            lock = root / "install-lock.json"
            lock.write_text(json.dumps({"external_tools": []}) + "\n", encoding="utf-8")
            with patch.dict(os.environ, {"MANAGEROO_SKILLS_DIR": str(skills)}):
                report = stack_status(lock)
            self.assertEqual(report["current_tool_paths"]["pimp-my-prompt"], str(skill))

    def test_relative_nested_pdf_path_is_resolved_once_for_extractor(self):
        class FakeRunner:
            def run(self, argv, *, cwd, timeout_seconds=45, **kwargs):
                target = Path(argv[2])
                self.assert_target = target
                self.assert_cwd = Path(cwd)
                return CommandResult(
                    argv=list(argv),
                    cwd=str(cwd),
                    started_at="start",
                    finished_at="finish",
                    exit_code=0,
                    stdout="text",
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            pdf = docs / "book.pdf"
            pdf.write_bytes(b"%PDF-1.7\n")
            runner = FakeRunner()
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch("manageroo.file_inspection.shutil.which", return_value="/usr/bin/pdftotext"):
                    self.assertEqual(pdf_text_extract(Path("docs/book.pdf"), runner), "text")
            finally:
                os.chdir(previous)
            self.assertEqual(runner.assert_target, pdf.resolve())
            self.assertEqual(runner.assert_cwd, docs.resolve())

    def test_truth_claim_negation_is_sentence_local(self):
        phrase = "full vision support"

        def offenders(text: str) -> list[str]:
            found = []
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.lower()):
                if phrase not in sentence:
                    continue
                before = sentence.split(phrase, 1)[0]
                denied = bool(re.search(r"(?:\bdoes not\b|\bcannot\b|\bnever\b|\bmust not\b|\bnot\b|\bwithout\b)", before))
                if not denied:
                    found.append(sentence)
            return found

        self.assertEqual(
            offenders("This is not experimental. Manageroo has full vision support."),
            ["manageroo has full vision support."],
        )
        self.assertEqual(offenders("Manageroo does not provide full vision support."), [])


if __name__ == "__main__":
    unittest.main()
