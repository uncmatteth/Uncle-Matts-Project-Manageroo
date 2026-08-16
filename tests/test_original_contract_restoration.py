from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.agent_continuity import (
    capture_current_request,
    install_codex_continuity_hooks,
    process_codex_continuity_hook,
)
from manageroo.config import DEFAULT_CONFIG, config_template
from manageroo.errors import ConfigurationError
from manageroo.gbrain_scope import gbrain_query_payload, scope_gbrain_search_record
from manageroo.integration_config import GBRAIN_SEARCH_COMMAND
from manageroo.readiness import requested_intelligence_lanes


ROOT = Path(__file__).resolve().parents[1]


class OriginalContractRestorationTests(unittest.TestCase):
    def test_restore_audit_and_finish_requests_are_automatically_managed(self):
        for prompt in (
            "Restore the original Manageroo contract.",
            "Audit everything missing from the original scope.",
            "Finish and verify the job.",
        ):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temp:
                repo = Path(temp) / "repo"
                repo.mkdir()
                (repo / ".git").mkdir()
                root = Path(temp) / "state"
                process_codex_continuity_hook(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "session",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "prompt": prompt,
                    },
                    state_root=root,
                )
                result = process_codex_continuity_hook(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "session",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "tool_name": "exec_command",
                        "tool_input": {"cmd": "pwd"},
                    },
                    state_root=root,
                )
                self.assertEqual(
                    result["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def _repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        return repo

    def test_gbrain_query_is_exact_source_scoped_and_json_filtered(self):
        source = {
            "matched_sources": [
                {"source_id": "product", "path": "/tmp/product"},
            ]
        }
        payload = json.loads(gbrain_query_payload("repair login", source))
        self.assertEqual(payload["source_id"], "product")

        record = scope_gbrain_search_record(
            {
                "name": "gbrain-search",
                "enabled": True,
                "ok": True,
                "stdout": json.dumps(
                    [
                        {"source_id": "product", "slug": "keep", "text": "right"},
                        {"source_id": "another", "slug": "drop", "text": "wrong"},
                    ]
                ),
                "stderr": "provider noise",
            },
            source,
        )
        self.assertTrue(record["ok"])
        self.assertEqual([item["slug"] for item in json.loads(record["stdout"])], ["keep"])
        self.assertEqual(record["stderr"], "")

    def test_default_gbrain_command_matches_live_structured_cli(self):
        self.assertEqual(
            GBRAIN_SEARCH_COMMAND,
            ["gbrain", "call", "query", "{gbrain_query_payload}"],
        )

    def test_every_controlled_run_requires_gbrain(self):
        self.assertTrue(requested_intelligence_lanes("Fix login.")["gbrain-search"])

    def test_worker_parallelism_is_bounded_to_two(self):
        self.assertEqual(DEFAULT_CONFIG["orchestration"]["max_parallel_agent_calls"], 2)
        self.assertIn("max_parallel_agent_calls = 2", config_template("mock", []))

    def test_actionable_repo_request_automatically_requires_managed_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            state = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix login, do not change payments, and prove login works.",
                cwd=str(repo),
                state_root=state_root,
            )
            self.assertTrue(state["managed_run_required"])

            denied = process_codex_continuity_hook(
                {
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "hook_event_name": "PreToolUse",
                    "cwd": str(repo),
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"
                    },
                },
                state_root=state_root,
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertIn(
                "controlled Manageroo run",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

            stopped = process_codex_continuity_hook(
                {
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "hook_event_name": "Stop",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(stopped["decision"], "block")

            allowed = process_codex_continuity_hook(
                {
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "hook_event_name": "PreToolUse",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "manageroo run --repo . --apply"},
                },
                state_root=state_root,
            )
            decision = allowed["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "allow")
            updated = decision["updatedInput"]["cmd"]
            self.assertIn("--brief", updated)
            self.assertIn("--apply", updated)

    def test_signed_continuity_state_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix and verify this repository.",
                cwd=str(repo),
                state_root=state_root,
            )
            state_path = next(
                path for path in state_root.glob("*.json") if path.is_file()
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            payload["managed_run_required"] = False
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "signature is invalid"):
                process_codex_continuity_hook(
                    {
                        "session_id": "session",
                        "turn_id": "turn-1",
                        "hook_event_name": "PreToolUse",
                        "cwd": str(repo),
                        "tool_name": "exec_command",
                        "tool_input": {"cmd": "pwd"},
                    },
                    state_root=state_root,
                )

    def test_stop_rejects_result_files_without_a_signed_exact_run_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            state = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix and verify this repository.",
                cwd=str(repo),
                state_root=state_root,
            )
            run_root = repo / ".manageroo" / "runs" / "proved"
            brief = run_root / "artifacts" / "intake" / "product-brief.md"
            conformance = (
                run_root / "artifacts" / "verification" / "intent-conformance.json"
            )
            result = run_root / "delivery" / "final-result.json"
            brief.parent.mkdir(parents=True)
            conformance.parent.mkdir(parents=True)
            result.parent.mkdir(parents=True)
            request = Path(state["managed_request_path"]).read_text(encoding="utf-8")
            brief.write_text(request.rstrip(), encoding="utf-8")
            conformance.write_text('{"status":"passed"}\n', encoding="utf-8")
            result.write_text(
                '{"status":"COMPLETE","applied_to_source":true}\n',
                encoding="utf-8",
            )
            stopped = process_codex_continuity_hook(
                {
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "hook_event_name": "Stop",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(stopped["decision"], "block")

    def test_read_only_question_does_not_force_a_managed_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            state = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="What does this repository do?",
                cwd=str(repo),
                state_root=Path(temp) / "state",
            )
            self.assertFalse(state["managed_run_required"])

    def test_whole_point_followup_resumes_a_paused_request(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            state_root = Path(temp) / "state"
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix Manageroo and verify it.",
                cwd=str(repo),
                state_root=state_root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop and wait.",
                cwd=str(repo),
                state_root=state_root,
            )
            resumed = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="The whole point of Manageroo was to prevent this from happening.",
                cwd=str(repo),
                state_root=state_root,
            )
            self.assertEqual(resumed["status"], "active")
            self.assertTrue(resumed["managed_run_required"])

    def test_installed_hooks_include_completion_stop_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = install_codex_continuity_hooks(
                codex_home=root / ".codex",
                manageroo_command=root / "bin" / "manageroo",
            )
            hooks = json.loads(Path(report["path"]).read_text(encoding="utf-8"))["hooks"]
            self.assertIn("Stop", hooks)

    def test_public_contract_does_not_relabel_original_stack_optional(self):
        dependency = (ROOT / "docs" / "DEPENDENCY_POLICY.md").read_text(encoding="utf-8")
        integrations = (ROOT / "docs" / "EXTERNAL_INTEGRATIONS.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("required local stack", dependency.lower())
        self.assertIn("exact source mapping", integrations.lower())
        self.assertIn("automatic managed execution", architecture.lower())


if __name__ == "__main__":
    unittest.main()
