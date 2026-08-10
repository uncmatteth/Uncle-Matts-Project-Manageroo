from __future__ import annotations

import json
import subprocess
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
    def _shell_decision(self, root: Path, repo: Path, prompt: str, command: str):
        process_codex_continuity_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": prompt,
            },
            state_root=root / "state",
        )
        return process_codex_continuity_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "tool_name": "exec_command",
                "tool_input": {"cmd": command},
            },
            state_root=root / "state",
        )

    def test_only_file_rejects_a_different_file_inside_the_current_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root,
                repo,
                f"Edit only {repo / 'allowed.txt'}.",
                f"touch {repo / 'different.txt'}",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_only_repo_relative_file_rejects_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root,
                repo,
                "Edit only src/allowed.py.",
                f"touch {repo / 'src' / 'different.py'}",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_only_file_rejects_rm_of_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root,
                repo,
                f"Edit only {repo / 'allowed.txt'}.",
                f"rm {repo / 'different.txt'}",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_only_file_rejects_python_write_of_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root,
                repo,
                f"Edit only {repo / 'allowed.txt'}.",
                (
                    "python3 -c \"from pathlib import Path; "
                    f"Path('{repo / 'different.txt'}').write_text('drift')\""
                ),
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_compound_command_does_not_reclassify_read_only_input_as_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "allowed.txt"
            source = repo / "source.txt"
            result = self._shell_decision(
                root,
                repo,
                f"Edit only {allowed}.",
                f"cat {source} && touch {allowed}",
            )
            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_python_read_input_is_not_reclassified_as_a_write_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "contact sheet.png"
            source = repo / "source image.png"
            result = self._shell_decision(
                root,
                repo,
                f'Edit only "{allowed}".',
                (
                    "python3 -c \"from pathlib import Path; "
                    f"data = Path('{source}').read_bytes(); "
                    f"Path('{allowed}').write_bytes(data)\""
                ),
            )
            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_quoted_path_with_spaces_is_exact_and_does_not_authorize_its_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "Folder With Spaces" / "allowed.txt"
            sibling = repo / "Folder With Spaces" / "different.txt"
            allowed_case = root / "allowed-case"
            denied_case = root / "denied-case"
            allowed_case.mkdir()
            denied_case.mkdir()
            prompt = f'Edit only "{allowed}".'
            allowed_result = self._shell_decision(
                allowed_case,
                repo,
                prompt,
                f'touch "{allowed}"',
            )
            denied_result = self._shell_decision(
                denied_case,
                repo,
                prompt,
                f'touch "{sibling}"',
            )
            self.assertNotEqual(
                allowed_result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )
            self.assertEqual(
                denied_result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_unrequested_clawpatch_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root,
                repo,
                "Repair scope control only. Do not run ClawPatch or release commands.",
                "clawpatch review",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_unrequested_release_command_is_rejected_but_direct_request_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            denied_root = root / "denied"
            allowed_root = root / "allowed"
            denied_root.mkdir()
            allowed_root.mkdir()
            denied = self._shell_decision(
                denied_root,
                repo,
                "Repair scope control. Do not run release commands.",
                "manageroo release-ready",
            )
            allowed = self._shell_decision(
                allowed_root,
                repo,
                "Run the release workflow.",
                "manageroo release-ready",
            )
            self.assertEqual(
                denied["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )
            self.assertNotEqual(
                allowed.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_release_named_evidence_path_is_not_a_release_workstream(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            staged = self._shell_decision(
                root / "staged",
                repo,
                "Repair the current repository only. Do not run release commands.",
                "git add scripts/package_release.py scripts/verify_release.py",
            )
            executed = self._shell_decision(
                root / "executed",
                repo,
                "Repair the current repository only. Do not run release commands.",
                "python3 scripts/package_release.py",
            )
            self.assertNotEqual(
                staged.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )
            self.assertEqual(
                executed["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

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

    def test_natural_correction_replaces_stale_scope_immediately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Edit only /opt/old-project.",
                },
                state_root=root,
            )
            corrected = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "No, use /opt/new-project. That is the repository.",
                },
                state_root=root,
            )
            context = corrected["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("/opt/old-project", context)
            self.assertIn("/opt/new-project", context)

            stale_write = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "touch /opt/old-project/STALE.txt"},
                },
                state_root=root,
            )
            self.assertEqual(
                stale_write["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_natural_file_correction_replaces_old_file_inside_same_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            old = repo / "old.txt"
            new = repo / "new.txt"
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": f"Edit only {old}.",
                },
                state_root=root / "state",
            )
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "prompt": f"No, use {new} instead.",
                },
                state_root=root / "state",
            )
            stale = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": f"touch {old}"},
                },
                state_root=root / "state",
            )
            current = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": f"touch {new}"},
                },
                state_root=root / "state",
            )
            self.assertEqual(stale["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertNotEqual(
                current.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_question_path_does_not_authorize_an_external_write(self):
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
                    "prompt": "Repair scope control in this repository only.",
                },
                state_root=root / "state",
            )
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "prompt": "Are you going to edit /opt/question-only-project?",
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "touch /opt/question-only-project/UNASKED.txt"
                    },
                },
                state_root=root / "state",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_quoted_path_does_not_authorize_an_external_write(self):
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
                    "prompt": "Repair scope control in this repository only.",
                },
                state_root=root / "state",
            )
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "prompt": (
                        'The last agent said "edit /opt/quoted-history-repo". '
                        "Why did it say that?"
                    ),
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "touch /opt/quoted-history-repo/UNASKED.txt"
                    },
                },
                state_root=root / "state",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_historical_path_does_not_authorize_an_external_write(self):
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
                    "prompt": "Repair scope control in this repository only.",
                },
                state_root=root / "state",
            )
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "prompt": (
                        "The prior agent edited /opt/historical-project during "
                        "the earlier session."
                    ),
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "touch /opt/historical-project/UNASKED.txt"
                    },
                },
                state_root=root / "state",
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

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
            faked = process_codex_continuity_hook(
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
            self.assertEqual(faked["decision"], "block")
            self.assertIn("independent completion evidence", faked["reason"])
            process_codex_continuity_hook(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "python3 -m unittest"},
                    "tool_output": {"exit_code": 0, "output": "OK"},
                },
                state_root=root,
            )
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

    def test_stop_hook_rejects_completion_with_dirty_required_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            for argv in (
                ["git", "init", "-q", "-b", "main"],
                ["git", "config", "user.name", "Manageroo Tests"],
                ["git", "config", "user.email", "tests@local.invalid"],
            ):
                subprocess.run(argv, cwd=repo, check=True)
            target = repo / "target.txt"
            target.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
            response = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Fix, commit, and push this change.",
                },
                state_root=root / "state",
            )
            marker = next(
                line
                for line in response["hookSpecificOutput"]["additionalContext"].splitlines()
                if line.startswith("<!-- manageroo-continuity:")
                and line.endswith(":complete -->")
            )
            target.write_text("after\n", encoding="utf-8")
            process_codex_continuity_hook(
                {
                    "hook_event_name": "PostToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "python3 -m unittest"},
                    "tool_output": {"exit_code": 0},
                },
                state_root=root / "state",
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "last_assistant_message": f"Done.\n{marker}",
                },
                state_root=root / "state",
            )
            self.assertEqual(result["decision"], "block")
            self.assertIn("Git worktree is not clean", result["reason"])

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
            self.assertIn(
                "explicit file or path",
                result["hookSpecificOutput"]["permissionDecisionReason"],
            )

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
            self.assertIn("PostToolUse", written["hooks"])
            stop_handler = written["hooks"]["Stop"][0]["hooks"][0]
            self.assertNotIn("additionalContextLimit", stop_handler)


if __name__ == "__main__":
    unittest.main()
