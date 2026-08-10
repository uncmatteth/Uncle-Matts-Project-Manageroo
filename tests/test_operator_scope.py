from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manageroo.operator_scope import (
    install_codex_operator_hooks,
    process_codex_hook,
    run_codex_operator_scope_hook,
)


class OperatorScopeHookTests(unittest.TestCase):
    def test_current_manageroo_request_denies_swipebot_command_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manageroo = root / "Uncle-Matts-Project-Manageroo"
            swipebot = root / "Swipebot-303-spl-unclematt"
            state = root / "state"
            (manageroo / ".git").mkdir(parents=True)
            (swipebot / ".git").mkdir(parents=True)

            captured = process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(manageroo),
                    "prompt": (
                        "Use $uncle-matts-project-manageroo and permanently fix "
                        "the operator scope lock in this repository."
                    ),
                },
                state_root=state,
            )
            self.assertEqual(captured, {})

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(manageroo),
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"git -C {swipebot} status",
                    },
                },
                state_root=state,
            )

            decision = denied["hookSpecificOutput"]
            self.assertEqual(decision["hookEventName"], "PreToolUse")
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertIn("outside locked repository", decision["permissionDecisionReason"])

    def test_tampered_receipt_cannot_redirect_scope_to_another_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manageroo = root / "Uncle-Matts-Project-Manageroo"
            swipebot = root / "Swipebot-303-spl-unclematt"
            state = root / "state"
            (manageroo / ".git").mkdir(parents=True)
            (swipebot / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(manageroo),
                    "prompt": "Fix only Manageroo.",
                },
                state_root=state,
            )

            receipt_path = next((state / "receipts").glob("*.json"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["repo_root"] = str(swipebot)
            receipt["allowed_paths"] = [str(swipebot)]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(swipebot),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "valid current-turn scope receipt",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_review_only_request_denies_apply_patch_inside_locked_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo and explain what it is supposed to do.",
                },
                state_root=state,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch",
                    },
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "does not authorize mutation",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_fix_request_does_not_silently_authorize_git_push(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Fix the operator scope lock in Manageroo.",
                },
                state_root=state,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push origin main"},
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "does not authorize push",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_finish_authorizes_commit_and_push_but_not_deploy(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Finish Manageroo.",
                },
                state_root=state,
            )

            decisions = {}
            for name, command in {
                "commit": "git commit -m scoped",
                "push": "git push origin main",
                "deploy": "vercel deploy --prod",
            }.items():
                decisions[name] = process_codex_hook(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    state_root=state,
                )

            self.assertEqual(decisions["commit"], {})
            self.assertEqual(decisions["push"], {})
            self.assertEqual(
                decisions["deploy"]["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_explicit_deploy_authority_allows_deploy_inside_locked_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Deploy Manageroo.",
                },
                state_root=state,
            )
            allowed = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "vercel deploy --prod"},
                },
                state_root=state,
            )
            self.assertEqual(allowed, {})

    def test_expired_receipt_denies_action(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            issued = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review this repository.",
                },
                state_root=state,
                now=issued,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                },
                state_root=state,
                now=issued + timedelta(hours=25),
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "valid current-turn scope receipt",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_apply_patch_cannot_escape_locked_repo_through_relative_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            outside = root / "Swipebot-303-spl-unclematt" / "README.md"
            (repo / ".git").mkdir(parents=True)
            outside.parent.mkdir(parents=True)
            outside.write_text("outside\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Fix Manageroo only.",
                },
                state_root=state,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            "*** Update File: ../Swipebot-303-spl-unclematt/README.md\n"
                            "@@\n-outside\n+changed\n"
                            "*** End Patch"
                        ),
                    },
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "outside locked repository",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_relative_git_c_directory_cannot_select_another_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            swipebot = root / "Swipebot-303-spl-unclematt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            (swipebot / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "git -C ../Swipebot-303-spl-unclematt status",
                    },
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "outside locked repository",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_parent_directory_alias_cannot_escape_locked_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git -C .. status"},
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_repo_replacement_at_same_path_invalidates_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            displaced = root / "manageroo-original"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )
            repo.rename(displaced)
            (repo / ".git").mkdir(parents=True)

            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                },
                state_root=state,
            )

            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertIn(
                "repository identity changed",
                denied["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_second_worktree_with_same_git_common_directory_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            worktree = root / "manageroo-other-worktree"
            state = root / "state"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "manageroo@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Manageroo Test"], cwd=repo, check=True
            )
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "other", str(worktree)],
                cwd=repo,
                check=True,
            )
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": f"git -C {worktree} status"},
                },
                state_root=state,
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_missing_or_wrong_turn_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            base = {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "tool_name": "Bash",
                "tool_input": {"command": "git status"},
            }
            missing = process_codex_hook(base, state_root=state)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo.",
                },
                state_root=state,
            )
            wrong_turn = process_codex_hook(base, state_root=state)
            for denied in (missing, wrong_turn):
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_named_external_handoff_is_read_only_and_does_not_unlock_siblings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            handoff = root / "operator-scope-handoff.md"
            sibling = root / "other-repo.md"
            (repo / ".git").mkdir(parents=True)
            handoff.write_text("evidence\n", encoding="utf-8")
            sibling.write_text("not named\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": f"Review this Manageroo failure handoff: {handoff}",
                },
                state_root=state,
            )

            allowed = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": f"sed -n '1,20p' {handoff}"},
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": f"sed -n '1,20p' {sibling}"},
                },
                state_root=state,
            )

            self.assertEqual(allowed, {})
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_named_external_source_cannot_be_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            source = root / "handoff.py"
            (repo / ".git").mkdir(parents=True)
            source.write_text("raise SystemExit('must not run')\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": f"Review the Manageroo handoff at {source}",
                },
                state_root=state,
            )

            for tool_name, tool_input in (
                ("Bash", {"command": f"python3 {source}"}),
                ("Bash", {"command": f"cat {source} | python3"}),
                ("mcp__filesystem__execute_file", {"path": str(source)}),
                ("mcp__filesystem__read_and_execute_file", {"path": str(source)}),
            ):
                denied = process_codex_hook(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    },
                    state_root=state,
                )
                self.assertEqual(
                    denied["hookSpecificOutput"]["permissionDecision"], "deny"
                )
                self.assertIn(
                    "read-only", denied["hookSpecificOutput"]["permissionDecisionReason"]
                )

    def test_mcp_file_tools_cannot_bypass_scope_or_action_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            outside = root / "Swipebot-303-spl-unclematt" / "README.md"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            outside.parent.mkdir()
            outside.write_text("outside\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )

            outside_read = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "mcp__filesystem__read_text_file",
                    "tool_input": {"path": str(outside)},
                },
                state_root=state,
            )
            inside_write = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "mcp__filesystem__write_file",
                    "tool_input": {
                        "path": str(repo / "README.md"),
                        "content": "changed",
                    },
                },
                state_root=state,
            )

            self.assertEqual(
                outside_read["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertEqual(
                inside_write["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertIn(
                "does not authorize mutation",
                inside_write["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_unified_exec_and_shell_writes_obey_the_same_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            outside = root / "other" / "README.md"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            outside.parent.mkdir()
            outside.write_text("outside\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )

            outside_exec = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": f"sed -n 1p {outside}"},
                },
                state_root=state,
            )
            inside_touch = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "touch unauthorized.txt"},
                },
                state_root=state,
            )

            self.assertEqual(
                outside_exec["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertEqual(
                inside_touch["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertIn(
                "does not authorize mutation",
                inside_touch["hookSpecificOutput"]["permissionDecisionReason"],
            )

    def test_symlinked_state_root_and_hardlinked_receipt_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            actual_state = root / "actual-state"
            linked_state = root / "linked-state"
            (repo / ".git").mkdir(parents=True)
            actual_state.mkdir(mode=0o700)
            linked_state.symlink_to(actual_state, target_is_directory=True)
            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": "Review Manageroo only.",
            }

            with self.assertRaises(ValueError):
                process_codex_hook(event, state_root=linked_state)

            process_codex_hook(event, state_root=actual_state)
            receipt = next((actual_state / "receipts").glob("*.json"))
            alias = root / "receipt-alias.json"
            os.link(receipt, alias)
            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                },
                state_root=actual_state,
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_non_repo_prompt_does_not_break_general_tools_or_unlock_an_unnamed_repo(self):
        with tempfile.TemporaryDirectory(dir=str(Path.home())) as temp:
            root = Path(temp)
            general = root / "general"
            repo = root / "manageroo"
            state = root / "state"
            general.mkdir()
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(general),
                    "prompt": "What time is it?",
                },
                state_root=state,
            )

            ordinary = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(general),
                    "tool_name": "Bash",
                    "tool_input": {"command": "pwd"},
                },
                state_root=state,
            )
            unnamed_repo = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(general),
                    "tool_name": "Bash",
                    "tool_input": {"command": f"git -C {repo} status"},
                },
                state_root=state,
            )

            self.assertEqual(ordinary, {})
            self.assertEqual(
                unnamed_repo["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_hook_installer_preserves_existing_hooks_and_adds_pre_action_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            codex_home = Path(temp) / ".codex"
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            existing = {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 existing.py",
                                }
                            ]
                        }
                    ]
                }
            }
            hooks_path.write_text(json.dumps(existing), encoding="utf-8")

            report = install_codex_operator_hooks(
                codex_home=codex_home,
                manageroo_command=Path("/opt/manageroo/bin/manageroo"),
            )

            installed = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(
                installed["hooks"]["UserPromptSubmit"][0],
                existing["hooks"]["UserPromptSubmit"][0],
            )
            manageroo_events = {
                event
                for event, groups in installed["hooks"].items()
                if any(
                    "operator-scope-hook" in handler.get("command", "")
                    for group in groups
                    for handler in group.get("hooks", [])
                )
            }
            self.assertEqual(manageroo_events, {"UserPromptSubmit", "PreToolUse"})
            self.assertTrue(report["trust_required"])

            repeated = install_codex_operator_hooks(
                codex_home=codex_home,
                manageroo_command=Path("/opt/manageroo/bin/manageroo"),
            )
            self.assertFalse(repeated["changed"])
            self.assertFalse(repeated["trust_required"])

    def test_hook_cli_emits_codex_pretool_deny_json(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "manageroo"
            state = Path(temp) / "state"
            (repo / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Review Manageroo only.",
                },
                state_root=state,
            )
            event = {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "tool_name": "Bash",
                "tool_input": {"command": "git -C .. status"},
            }
            output = io.StringIO()
            error = io.StringIO()

            exit_code = run_codex_operator_scope_hook(
                input_stream=io.StringIO(json.dumps(event)),
                output_stream=output,
                error_stream=error,
                state_root=state,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(error.getvalue(), "")
            result = json.loads(output.getvalue())
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_public_manageroo_entrypoint_runs_operator_scope_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            outside = root / "Swipebot-303-spl-unclematt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            (outside / ".git").mkdir(parents=True)
            env = {
                **os.environ,
                "MANAGEROO_OPERATOR_SCOPE_STATE": str(state),
            }
            capture = subprocess.run(
                [sys.executable, "-m", "manageroo", "operator-scope-hook"],
                input=json.dumps(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "prompt": "Review Manageroo only.",
                    }
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(capture.returncode, 0, capture.stderr)
            denied = subprocess.run(
                [sys.executable, "-m", "manageroo", "operator-scope-hook"],
                input=json.dumps(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "session-1",
                        "turn_id": "turn-1",
                        "cwd": str(repo),
                        "tool_name": "Bash",
                        "tool_input": {"command": f"git -C {outside} status"},
                    }
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            self.assertEqual(denied.returncode, 0, denied.stderr)
            self.assertEqual(
                json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )


if __name__ == "__main__":
    unittest.main()
