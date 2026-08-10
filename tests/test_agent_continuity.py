from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from manageroo.agent_continuity import (
    INTERNAL_CONTINUATION_PREFIX,
    capture_current_request,
    install_codex_continuity_hooks,
    process_codex_continuity_hook,
)


class AgentContinuityTests(unittest.TestCase):
    def test_new_messages_are_additive_while_work_is_unfinished(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Edit the named TXT and verify every prompt.",
                cwd="/project",
                state_root=root,
            )
            second = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Also make every location self-contained.",
                cwd="/project",
                state_root=root,
            )
            self.assertNotEqual(first["objective_sha256"], second["objective_sha256"])
            self.assertEqual(
                [item["relation"] for item in second["messages"]],
                ["root", "addition"],
            )
            self.assertIn("Edit the named TXT", second["messages"][0]["text"])

    def test_only_explicit_replacement_discards_unfinished_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Finish the Android animations.",
                cwd="/project",
                state_root=root,
            )
            state = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop what you are doing. Do only this now: review Manageroo.",
                cwd="/project",
                state_root=root,
            )
            self.assertEqual(len(state["messages"]), 1)
            self.assertEqual(state["messages"][0]["relation"], "replacement")
            self.assertEqual(state["generation"], 2)

    def test_bare_stop_is_an_explicit_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Keep working on the old task.",
                cwd="/project",
                state_root=root,
            )
            state = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="stop",
                cwd="/project",
                state_root=root,
            )
            self.assertEqual([item["text"] for item in state["messages"]], ["stop"])
            self.assertEqual(state["generation"], 2)

    def test_internal_stop_continuation_is_not_added_as_operator_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initial = capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Finish the named work.",
                cwd="/project",
                state_root=root,
            )
            continued = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt=f"{INTERNAL_CONTINUATION_PREFIX} keep working",
                cwd="/project",
                state_root=root,
            )
            self.assertEqual(initial["messages"], continued["messages"])

    def test_prompt_hook_never_blocks_operator_and_injects_full_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Finish the existing job.",
                },
                state_root=root,
            )
            second = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "Answer this side question, then continue.",
                },
                state_root=root,
            )
            self.assertNotIn("decision", first)
            self.assertNotIn("decision", second)
            context = second["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Finish the existing job.", context)
            self.assertIn("Answer this side question, then continue.", context)
            self.assertIn("resume the unfinished work", context)

    def test_stop_hook_continues_agent_until_current_objective_is_marked_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": "/project",
                "prompt": "Finish and verify the job.",
            }
            response = process_codex_continuity_hook(prompt, state_root=root)
            context = response["hookSpecificOutput"]["additionalContext"]
            marker = next(
                line
                for line in context.splitlines()
                if line.startswith("<!-- manageroo-continuity:") and line.endswith(":complete -->")
            )
            stopped = process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "last_assistant_message": "I answered the side question only.",
                    "stop_hook_active": False,
                },
                state_root=root,
            )
            self.assertEqual(stopped["decision"], "block")
            self.assertIn("resume and finish", stopped["reason"])
            completed = process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "last_assistant_message": f"Verified completion.\n{marker}",
                    "stop_hook_active": True,
                },
                state_root=root,
            )
            self.assertEqual(completed, {})

    def test_read_only_tools_are_never_blocked_by_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "prompt": "Edit only /home/Tommy/Desktop/backgroundswap.txt.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "tool_name": "Bash",
                    "tool_input": {"command": "df -h / /home /tmp"},
                },
                state_root=root,
            )
            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_read_only_redirect_does_not_reclassify_input_paths_as_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Inspect this repository without changing it.",
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "diff -qr src /opt/manageroo/app >/dev/null"
                    },
                },
                state_root=root / "state",
            )
            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_redirect_to_unrelated_external_path_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Inspect this repository without changing it.",
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "cat README.md > /opt/manageroo/report.txt"
                    },
                },
                state_root=root / "state",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_exec_command_alias_is_checked_for_cross_repo_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "prompt": "Work only in /repo.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "touch /other-repo/drift.txt"},
                },
                state_root=root,
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_current_git_root_is_scope_without_magic_path_phrase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Fix this without deviating.",
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "touch /different-repository/drift.txt"},
                },
                state_root=root / "state",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"], "deny"
            )

    def test_agent_mutation_of_different_named_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "prompt": "Edit only /home/Tommy/Desktop/backgroundswap.txt.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: /home/Tommy/Documents/GitHub/other/file.txt\n*** End Patch"
                    },
                },
                state_root=root,
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"], "deny"
            )
            self.assertIn("agent's unrelated mutation", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_sentence_punctuation_does_not_change_named_external_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "prompt": "Edit only /home/Tommy/Desktop/backgroundswap.txt.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/repo",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": "*** Begin Patch\n*** Update File: /home/Tommy/Desktop/backgroundswap.txt\n*** End Patch"
                    },
                },
                state_root=root,
            )
            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_installer_preserves_unrelated_hooks_and_replaces_old_manageroo_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "UserPromptSubmit": [
                                {"hooks": [{"command": "gbrain prompt hook"}]},
                                {"hooks": [{"command": "/bin/manageroo operator-" "scope-hook"}]},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = install_codex_continuity_hooks(
                codex_home=codex_home,
                manageroo_command=Path("/bin/manageroo"),
            )
            self.assertTrue(result["changed"])
            self.assertEqual(result["next"], "/hooks")
            written = json.loads(hooks_path.read_text(encoding="utf-8"))
            rendered = json.dumps(written)
            self.assertIn("gbrain prompt hook", rendered)
            self.assertNotIn("operator-" "scope-hook", rendered)
            self.assertIn("agent-continuity-hook", rendered)
            self.assertIn("Stop", written["hooks"])
            self.assertIn("PreToolUse", written["hooks"])
            stop_handler = written["hooks"]["Stop"][0]["hooks"][0]
            self.assertNotIn("additionalContextLimit", stop_handler)


if __name__ == "__main__":
    unittest.main()
