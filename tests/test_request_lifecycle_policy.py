from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from manageroo.agent_continuity import (
    capture_current_request,
    process_codex_continuity_hook,
)


class RequestLifecyclePolicyTests(unittest.TestCase):
    def _repo(self, root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir()
        (repo / ".git").mkdir()
        return repo.resolve()

    def test_cancel_invalidates_completion_and_new_work_starts_fresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root, "repo")
            state_root = root / "state"
            first = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix this repository and verify it.",
                cwd=str(repo),
                state_root=state_root,
            )
            first["authorized_run_id"] = "old-run"
            first["completion_receipt_path"] = "/tmp/old-receipt"
            first["completion_receipt_sha256"] = "old"
            first["completed_run_root"] = "/tmp/old-run"
            from manageroo import agent_continuity as continuity

            continuity._save_state(state_root.resolve(), first)

            cancelled = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Cancel this request.",
                cwd=str(repo),
                state_root=state_root,
            )
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(cancelled["managed_run_required"])
            self.assertNotIn("authorized_run_id", cancelled)

            fresh = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="Audit this repository. Do not change anything.",
                cwd=str(repo),
                state_root=state_root,
            )
            self.assertEqual(fresh["status"], "active")
            self.assertEqual(fresh["generation"], cancelled["generation"] + 1)
            self.assertEqual(len(fresh["messages"]), 1)
            self.assertEqual(fresh["messages"][0]["relation"], "root")

    def test_repository_conflict_does_not_change_active_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_a = self._repo(root, "repo-a")
            repo_b = self._repo(root, "repo-b")
            state_root = root / "state"
            first = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt=f"Fix repository {repo_a} and verify it.",
                cwd=str(root),
                state_root=state_root,
            )
            second = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt=f"Also edit repository {repo_b}.",
                cwd=str(root),
                state_root=state_root,
            )
            self.assertEqual(second["messages"], first["messages"])
            self.assertEqual(second["generation"], first["generation"])
            self.assertEqual(second["managed_request_sha256"], first["managed_request_sha256"])
            self.assertIn("last_rejected_request", second)

    def test_explicit_replacement_can_change_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_a = self._repo(root, "repo-a")
            repo_b = self._repo(root, "repo-b")
            state_root = root / "state"
            first = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt=f"Fix repository {repo_a}.",
                cwd=str(root),
                state_root=state_root,
            )
            replaced = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt=f"Replace the previous request. Fix repository {repo_b} instead.",
                cwd=str(root),
                state_root=state_root,
            )
            self.assertNotEqual(replaced["bound_repo"], first["bound_repo"])
            self.assertEqual(Path(replaced["bound_repo"]), repo_b)
            self.assertEqual(replaced["messages"][0]["relation"], "replacement")

    def test_paused_request_denies_run_until_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root, "repo")
            state_root = root / "state"
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Fix this repository.",
                cwd=str(repo),
                state_root=state_root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Pause and wait.",
                cwd=str(repo),
                state_root=state_root,
            )
            denied = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "manageroo run --repo ."},
                },
                state_root=state_root,
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="Resume.",
                cwd=str(repo),
                state_root=state_root,
            )
            allowed = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "manageroo run --repo ."},
                },
                state_root=state_root,
            )
            self.assertEqual(
                allowed["hookSpecificOutput"]["permissionDecision"], "allow"
            )


if __name__ == "__main__":
    unittest.main()
