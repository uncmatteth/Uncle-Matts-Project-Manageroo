from __future__ import annotations

import io
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import manageroo.agent_continuity as continuity

from manageroo.managed_contract_policy import (
    EXECUTION_INTENT_MUTATING,
    EXECUTION_INTENT_READ_ONLY,
    _load_request_metadata,
    _resolve_repository_binding,
    _write_completion_receipt,
    install_managed_contract_policy,
    reset_continuity_state,
)
from manageroo.release_proof_policy import source_tree_digest
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json, sha256_file


class ManagedContractPolicyTests(unittest.TestCase):
    def _repo(self, root: Path, name: str = "product") -> Path:
        repo = root / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Manageroo Test"], cwd=repo, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "manageroo@example.invalid"],
            cwd=repo,
            check=True,
        )
        (repo / ".gitignore").write_text(".manageroo/runs/\n", encoding="utf-8")
        (repo / "README.md").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True)
        return repo

    def _capture(
        self,
        *,
        state_root: Path,
        repo: Path,
        prompt: str,
        turn_id: str = "turn-1",
    ) -> dict:
        return continuity.capture_current_request(
            session_id="session",
            turn_id=turn_id,
            prompt=prompt,
            cwd=str(repo),
            state_root=state_root,
        )

    def test_acknowledgment_does_not_change_request_generation_or_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            first = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix the login flow and verify it.",
            )
            second = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Thanks.",
                turn_id="turn-2",
            )

            self.assertEqual(second["messages"], first["messages"])
            self.assertEqual(second["generation"], first["generation"])
            self.assertEqual(
                second["managed_request_sha256"], first["managed_request_sha256"]
            )

    def test_acknowledgment_after_completion_does_not_open_a_new_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            first = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix the login flow and verify it.",
            )
            completed = continuity._read_state(state_root, "session")
            self.assertIsNotNone(completed)
            completed["status"] = "complete"
            continuity._save_state(state_root, completed)

            second = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Thank you.",
                turn_id="turn-2",
            )

            self.assertEqual(second["status"], "complete")
            self.assertEqual(second["messages"], first["messages"])
            self.assertEqual(second["generation"], first["generation"])

    def test_additional_requirement_creates_new_generation_and_invalidates_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            first = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix the login flow and verify it.",
            )
            first_request_path = Path(first["managed_request_path"])
            first_request_bytes = first_request_path.read_bytes()
            state = continuity._read_state(state_root, "session")
            self.assertIsNotNone(state)
            state.update(
                {
                    "authorized_run_id": "old-run",
                    "completion_receipt_path": "/tmp/old-receipt",
                    "completion_receipt_sha256": "old",
                    "completed_run_root": "/tmp/old-run",
                }
            )
            continuity._save_state(state_root, state)

            second = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Also prove logout works.",
                turn_id="turn-2",
            )

            self.assertEqual(second["generation"], first["generation"] + 1)
            self.assertNotEqual(
                Path(second["managed_request_path"]), first_request_path
            )
            self.assertEqual(first_request_path.read_bytes(), first_request_bytes)
            self.assertEqual(
                [item["relation"] for item in second["messages"]],
                ["root", "addition"],
            )
            for field in (
                "authorized_run_id",
                "completion_receipt_path",
                "completion_receipt_sha256",
                "completed_run_root",
            ):
                self.assertNotIn(field, second)

    def test_read_only_request_never_receives_apply_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            state = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Review this repository and tell me what is wrong. Do not change anything.",
            )
            self.assertEqual(state["execution_intent"], EXECUTION_INTENT_READ_ONLY)

            for command in (
                "manageroo run --repo .",
                "manageroo run --repo . --apply",
                "manageroo run --repo . --no-apply --apply",
                "manageroo run --repo . --apply --no-apply",
            ):
                with self.subTest(command=command):
                    decision = continuity.process_codex_continuity_hook(
                        {
                            "hook_event_name": "PreToolUse",
                            "session_id": "session",
                            "turn_id": "turn-1",
                            "cwd": str(repo),
                            "tool_name": "exec_command",
                            "tool_input": {"cmd": command},
                        },
                        state_root=state_root,
                    )["hookSpecificOutput"]
                    tokens = shlex.split(decision["updatedInput"]["cmd"])
                    self.assertEqual(decision["permissionDecision"], "allow")
                    self.assertEqual(tokens.count("--no-apply"), 1)
                    self.assertNotIn("--apply", tokens)

    def test_mutating_request_receives_apply_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix the login flow and verify it.",
            )
            decision = continuity.process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "manageroo run --repo ."},
                },
                state_root=state_root,
            )["hookSpecificOutput"]
            self.assertIn("--apply", shlex.split(decision["updatedInput"]["cmd"]))

    def test_named_exclusion_does_not_turn_mutating_work_into_read_only_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state = self._capture(
                state_root=root / "state",
                repo=repo,
                prompt="Fix login, do not change payments, and prove login works.",
            )
            self.assertEqual(state["execution_intent"], EXECUTION_INTENT_MUTATING)

    def test_explicit_unknown_repository_is_not_replaced_by_sole_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_a = self._repo(root, "repo-a")
            resolution = _resolve_repository_binding(
                prompt="Fix repository repo-b.",
                cwd=str(root),
                projects=[{"name": "repo-a", "path": str(repo_a)}],
                continuity_module=continuity,
            )
            self.assertEqual(resolution["status"], "missing")
            self.assertEqual(resolution["repo"], "")

    def test_current_git_root_binds_before_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            unrelated = self._repo(root, "fix-login-helper")
            resolution = _resolve_repository_binding(
                prompt="Fix this repository.",
                cwd=str(repo / "nested"),
                projects=[{"name": "fix-login-helper", "path": str(unrelated)}],
                continuity_module=continuity,
            )
            # Generic work words are not project identities. The nested path need
            # not exist; binding still walks its lexical parents.
            self.assertEqual(resolution["status"], "bound")
            self.assertEqual(Path(resolution["repo"]), repo)

    def test_forged_result_and_conformance_files_do_not_authorize_stop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            state = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix and verify this repository.",
            )
            run_root = repo / ".manageroo" / "runs" / "forged"
            brief = run_root / "artifacts" / "intake" / "product-brief.md"
            conformance = (
                run_root / "artifacts" / "verification" / "intent-conformance.json"
            )
            result = run_root / "delivery" / "final-result.json"
            brief.parent.mkdir(parents=True)
            conformance.parent.mkdir(parents=True)
            result.parent.mkdir(parents=True)
            brief.write_text(
                Path(state["managed_request_path"]).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            conformance.write_text('{"status":"passed"}\n', encoding="utf-8")
            result.write_text(
                '{"run_id":"forged","status":"COMPLETE","applied_to_source":true}\n',
                encoding="utf-8",
            )

            stopped = continuity.process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(stopped["decision"], "block")

    def test_signed_receipt_binds_exact_run_and_current_source_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            state = self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix and verify this repository.",
            )
            loaded = _load_request_metadata(
                Path(state["managed_request_path"]), continuity
            )
            self.assertIsNotNone(loaded)
            metadata, metadata_root = loaded
            runner = CommandRunner()
            start_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            start_tree = source_tree_digest(repo, runner)

            (repo / "README.md").write_text("after\n", encoding="utf-8")
            run_root = repo / ".manageroo" / "runs" / "proved"
            verification = run_root / "artifacts" / "verification"
            review = run_root / "artifacts" / "review"
            delivery = run_root / "delivery"
            verification.mkdir(parents=True)
            review.mkdir(parents=True)
            delivery.mkdir(parents=True)
            patch_text = subprocess.run(
                ["git", "diff", "--binary", "HEAD", "--"],
                cwd=repo,
                check=True,
                text=True,
                capture_output=True,
            ).stdout
            patch_path = delivery / "final.patch"
            patch_path.write_text(patch_text, encoding="utf-8")
            current_tree = source_tree_digest(repo, runner)
            result = {
                "run_id": "proved",
                "status": "COMPLETE",
                "applied_to_source": True,
                "verified_source_tree_sha256": current_tree,
                "verified_git_head": start_head,
                "final_patch_sha256": sha256_file(patch_path),
            }
            atomic_write_json(delivery / "final-result.json", result)
            atomic_write_json(
                verification / "intent-conformance.json", {"status": "passed"}
            )
            atomic_write_json(verification / "gates.json", [])
            atomic_write_json(verification / "acceptance-evidence.json", [])
            atomic_write_json(review / "review.json", {"status": "approved"})
            orchestrator = SimpleNamespace(
                source_repo=repo,
                run_root=run_root,
                runner=runner,
                run_id="proved",
            )
            receipt_path = _write_completion_receipt(
                orchestrator=orchestrator,
                request_metadata=metadata,
                state_root=metadata_root,
                result=result,
                start_git_head=start_head,
                start_source_tree_sha256=start_tree,
                continuity_module=continuity,
            )
            self.assertTrue(receipt_path.is_file())
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes.decode("utf-8"))
            receipt["run_id"] = "forged-run"
            atomic_write_json(receipt_path, receipt)
            tampered = continuity.process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(tampered["decision"], "block")
            receipt_path.write_bytes(receipt_bytes)

            accepted = continuity.process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(accepted, {})

            (repo / "README.md").write_text("tampered\n", encoding="utf-8")
            # Re-open the same active state to test stale proof rather than the completed marker.
            active = continuity._read_state(state_root, "session")
            active["status"] = "active"
            continuity._save_state(state_root, active)
            rejected = continuity.process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "stop_hook_active": False,
                },
                state_root=state_root,
            )
            self.assertEqual(rejected["decision"], "block")

    def test_invalid_state_fails_closed_and_exact_reset_command_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root)
            state_root = root / "state"
            self._capture(
                state_root=state_root,
                repo=repo,
                prompt="Fix and verify this repository.",
            )
            state_path = continuity._state_path(state_root.resolve(), "session")
            state_path.write_text("{broken", encoding="utf-8")
            event = {
                "hook_event_name": "PreToolUse",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "tool_name": "exec_command",
                "tool_input": {"cmd": "pwd"},
            }
            output = io.StringIO()
            with mock.patch.dict(
                continuity.os.environ,
                {"MANAGEROO_CONTINUITY_STATE": str(state_root)},
                clear=False,
            ):
                continuity.run_codex_continuity_hook(
                    input_stream=io.StringIO(json.dumps(event)),
                    output_stream=output,
                )
            result = json.loads(output.getvalue())
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertNotIn(
                "continue normally",
                result["hookSpecificOutput"]["permissionDecisionReason"].casefold(),
            )

            event["tool_input"] = {
                "cmd": "manageroo continuity-reset --session-id session"
            }
            output = io.StringIO()
            with mock.patch.dict(
                continuity.os.environ,
                {"MANAGEROO_CONTINUITY_STATE": str(state_root)},
                clear=False,
            ):
                continuity.run_codex_continuity_hook(
                    input_stream=io.StringIO(json.dumps(event)),
                    output_stream=output,
                )
            allowed = json.loads(output.getvalue())
            self.assertEqual(
                allowed["hookSpecificOutput"]["permissionDecision"], "allow"
            )

            reset_command = "manageroo continuity-reset --session-id session"
            marker = root / "injected"
            hostile_commands = (
                f"{reset_command} ; touch {marker}",
                f"{reset_command} && touch {marker}",
                f"{reset_command} || touch {marker}",
                f"{reset_command}\ntouch {marker}",
                f"{reset_command} > {marker}",
                f"{reset_command} $(touch {marker})",
                f"touch {marker} ; {reset_command}",
                f"{reset_command} extra-command",
            )
            for command in hostile_commands:
                with self.subTest(command=command):
                    event["tool_input"] = {"cmd": command}
                    output = io.StringIO()
                    with mock.patch.dict(
                        continuity.os.environ,
                        {"MANAGEROO_CONTINUITY_STATE": str(state_root)},
                        clear=False,
                    ):
                        continuity.run_codex_continuity_hook(
                            input_stream=io.StringIO(json.dumps(event)),
                            output_stream=output,
                        )
                    denied = json.loads(output.getvalue())
                    self.assertEqual(
                        denied["hookSpecificOutput"]["permissionDecision"], "deny"
                    )
                    self.assertFalse(marker.exists())

            report = reset_continuity_state(
                session_id="session",
                state_root=state_root,
                continuity_module=continuity,
            )
            self.assertTrue(report["ok"])
            self.assertFalse(state_path.exists())
            self.assertTrue(report["quarantined"])

    def test_delivery_recovery_wraps_run_before_normal_preflight(self):
        calls: list[str] = []

        class FakeOrchestrator:
            def _recover_incomplete_delivery(self):
                calls.append("recover")

            def run(self, *args, **kwargs):
                calls.append("run")
                return {"status": "BLOCKED"}

        fake_orchestrator_module = SimpleNamespace(Orchestrator=FakeOrchestrator)
        fake_continuity_module = SimpleNamespace(
            _manageroo_managed_contract_policy_installed=True,
            _persist_managed_request=lambda *args, **kwargs: None,
            _capture_current_request_locked=lambda **kwargs: {},
        )
        install_managed_contract_policy(
            fake_orchestrator_module, fake_continuity_module
        )
        instance = FakeOrchestrator()
        instance.run(brief_path=Path("/nonexistent/brief.md"))
        self.assertEqual(calls, ["recover", "run"])


if __name__ == "__main__":
    unittest.main()
