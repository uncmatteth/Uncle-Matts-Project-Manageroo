from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import shlex
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manageroo.operator_scope import (
    install_codex_operator_hooks,
    load_operator_context,
    process_codex_hook,
    run_codex_operator_scope_hook,
)


class OperatorScopeHookTests(unittest.TestCase):
    def _decision(self, prompt: str, *, command: str = "", tool_name: str = "Bash", tool_input=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = root / "manageroo"
        state = root / "state"
        (repo / ".git").mkdir(parents=True)
        process_codex_hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": prompt,
            },
            state_root=state,
        )
        return process_codex_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "tool_name": tool_name,
                "tool_input": tool_input if tool_input is not None else {"command": command},
            },
            state_root=state,
        )

    def assertDenied(self, result, fragment: str | None = None):
        decision = result["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        if fragment:
            self.assertIn(fragment, decision["permissionDecisionReason"])

    def test_action_mentions_and_questions_do_not_grant_authority(self):
        cases = (
            ("Why did the last agent push?", "git push origin main", "push"),
            ("Did the last agent deploy?", "vercel deploy --prod", "deploy"),
            ("Review the delete behavior.", "rm README.md", "delete"),
            ("Is the install complete?", "npm install", "install"),
        )
        for prompt, command, action in cases:
            with self.subTest(prompt=prompt):
                self.assertDenied(self._decision(prompt, command=command), action)

    def test_nested_dynamic_and_hook_bypass_shells_fail_closed(self):
        commands = (
            "sh -c 'cd .. && git -C other status --short'",
            'git -C "$HOME/Documents/GitHub/Other" status',
            "python3 -c 'from pathlib import Path; Path(\"../outside\").write_text(\"x\")'",
            "codex exec --ignore-user-config --full-auto repair",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertDenied(
                    self._decision("Repair Manageroo.", command=command),
                    "cannot prove",
                )

    def test_opaque_script_requires_native_sandbox_wrapper(self):
        direct = self._decision("Repair Manageroo.", command="python3 scripts/verify_release.py")
        wrapped = self._decision(
            "Repair Manageroo.",
            command="manageroo operator-exec --repo . -- python3 scripts/verify_release.py",
        )
        self.assertDenied(direct, "operator-exec")
        self.assertEqual(wrapped, {})

    def test_explicit_manageroo_invocation_for_repair_blocks_freehand_edits(self):
        patch_result = self._decision(
            "$uncle-matts-project-manageroo repair this correctly.",
            tool_name="apply_patch",
            tool_input={
                "command": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"
            },
        )
        controlled_run = self._decision(
            "$uncle-matts-project-manageroo repair this correctly.",
            command="manageroo run --repo . --brief .manageroo/PRODUCT-BRIEF.md --apply",
        )
        self.assertDenied(patch_result, "controlled Manageroo run")
        decision = controlled_run["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "allow")
        self.assertIn("--operator-receipt", decision["updatedInput"]["command"])

    def test_explicit_manageroo_turn_cannot_stop_before_controlled_run_starts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
            }
            process_codex_hook(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "$uncle-matts-project-manageroo repair this correctly.",
                },
                state_root=state,
            )

            before = process_codex_hook(
                {**event, "hook_event_name": "Stop", "stop_hook_active": False},
                state_root=state,
            )
            repeated = process_codex_hook(
                {**event, "hook_event_name": "Stop", "stop_hook_active": True},
                state_root=state,
            )
            launched = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "manageroo run --repo . --brief brief.md --apply"
                    },
                },
                state_root=state,
            )
            after = process_codex_hook(
                {**event, "hook_event_name": "Stop", "stop_hook_active": False},
                state_root=state,
            )

            self.assertEqual(before["decision"], "block")
            self.assertIn("has not started", before["reason"])
            self.assertEqual(repeated, {})
            self.assertEqual(
                launched["hookSpecificOutput"]["permissionDecision"], "allow"
            )
            self.assertEqual(after, {})

    def test_controlled_run_binds_signed_operator_history_and_denies_receipt_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            transcript = root / "session.jsonl"
            (repo / ".git").mkdir(parents=True)
            transcript.write_text(
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Use the finished renderer from tools/swipebot_motion.py.",
                                }
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "transcript_path": str(transcript),
                "prompt": "$uncle-matts-project-manageroo go do it right.",
            }
            process_codex_hook(event, state_root=state)

            allowed = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "manageroo run --repo . --apply"},
                },
                state_root=state,
            )
            decision = allowed["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "allow")
            rewritten = shlex.split(decision["updatedInput"]["command"])
            receipt = Path(rewritten[rewritten.index("--operator-receipt") + 1])
            context = load_operator_context(receipt, repo=repo, state_root=state)
            self.assertEqual(
                context["messages"],
                [
                    "Use the finished renderer from tools/swipebot_motion.py.",
                    "$uncle-matts-project-manageroo go do it right.",
                ],
            )

            supplied = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "manageroo run --repo . --operator-receipt /tmp/fake --apply"
                    },
                },
                state_root=state,
            )
            escaped = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "manageroo operator-exec --repo . -- python3 rewrite.py"
                    },
                },
                state_root=state,
            )
            self.assertDenied(supplied, "operator receipt")
            self.assertDenied(escaped, "operator-exec")

    def test_controlled_request_denies_freehand_search_and_alternate_read_tools(self):
        prompt = "$uncle-matts-project-manageroo go find exactly what I told you."
        shell_search = self._decision(prompt, command="rg -n voice .")
        gbrain_search = self._decision(
            prompt,
            tool_name="mcp__gbrain__query",
            tool_input={"query": "voice profanity"},
        )
        polling = self._decision(
            prompt,
            tool_name="write_stdin",
            tool_input={"session_id": 123, "chars": ""},
        )
        interruption = self._decision(
            prompt,
            tool_name="write_stdin",
            tool_input={"session_id": 123, "chars": "\u0003"},
        )
        status = self._decision(prompt, command="manageroo status run-1 --repo . --json")

        self.assertDenied(shell_search, "controlled Manageroo run")
        self.assertDenied(gbrain_search, "controlled Manageroo run")
        self.assertEqual(polling, {})
        self.assertDenied(interruption, "interrupt")
        self.assertEqual(status, {})

    def test_controlled_request_can_read_only_its_exact_manageroo_skill_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            state = root / "state"
            skill = repo / "src" / "manageroo" / "assets" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md"
            (repo / ".git").mkdir(parents=True)
            skill.parent.mkdir(parents=True)
            skill.write_text("# Manageroo\n", encoding="utf-8")
            (repo / "README.md").write_text("not the skill\n", encoding="utf-8")
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": "$uncle-matts-project-manageroo repair this correctly.",
            }
            process_codex_hook(
                {**event, "hook_event_name": "UserPromptSubmit"},
                state_root=state,
            )
            skill_read = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"cat {skill}"},
                },
                state_root=state,
            )
            other_read = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "cat README.md"},
                },
                state_root=state,
            )
            self.assertEqual(skill_read, {})
            self.assertDenied(other_read, "controlled Manageroo run")

    def test_manageroo_package_trash_and_deploy_commands_require_specific_authority(self):
        cases = (
            ("Review Manageroo.", "manageroo run --repo . --brief brief.md --apply", "mutation"),
            ("Review Manageroo.", "manageroo solo . --create", "mutation"),
            ("Review Manageroo.", "manageroo memory init .", "mutation"),
            ("Review Manageroo.", "manageroo intent capture . --want x", "mutation"),
            ("Repair Manageroo.", "brew install example-package", "install"),
            ("Repair Manageroo.", "gio trash README.md", "delete"),
            ("Repair Manageroo.", "npm run deploy", "deploy"),
        )
        for prompt, command, action in cases:
            with self.subTest(command=command):
                self.assertDenied(self._decision(prompt, command=command), action)

    def test_non_shell_commit_and_deploy_tools_require_specific_authority(self):
        commit = self._decision(
            "Repair Manageroo.",
            tool_name="mcp__git__commit",
            tool_input={"repo_path": ".", "message": "repair"},
        )
        deploy = self._decision(
            "Repair Manageroo.",
            tool_name="mcp__vercel__deploy",
            tool_input={"root": "."},
        )
        self.assertDenied(commit, "commit")
        self.assertDenied(deploy, "deploy")

    def test_only_named_file_restricts_apply_patch_inside_repo(self):
        denied = self._decision(
            "Fix README.md only. Do not edit any other file.",
            tool_name="apply_patch",
            tool_input={
                "command": (
                    "*** Begin Patch\n"
                    "*** Update File: src/manageroo/operator_scope.py\n"
                    "@@\n-old\n+new\n"
                    "*** End Patch"
                )
            },
        )
        self.assertDenied(denied, "outside the current request's allowed paths")

    def test_explicit_external_output_directory_is_writable_but_other_external_paths_are_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            output = root / "Desktop" / "finished"
            other = root / "other"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            output.mkdir(parents=True)
            other.mkdir()
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": f"Create the finished contact sheets in {output}. Do not write anywhere else.",
            }
            process_codex_hook(
                {**event, "hook_event_name": "UserPromptSubmit"},
                state_root=state,
            )
            allowed = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"touch {output / 'sheet.png'}"},
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"touch {other / 'sheet.png'}"},
                },
                state_root=state,
            )
            self.assertEqual(allowed, {})
            self.assertDenied(denied, "outside locked repository scope")

    def test_edit_instruction_allows_exact_external_file_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            target = root / "Desktop" / "backgroundswap.txt"
            state = root / "state"
            (root / ".git").mkdir()
            (repo / ".git").mkdir(parents=True)
            target.parent.mkdir()
            target.write_text("old\n", encoding="utf-8")
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": (
                    f"> Edit {target} in full now. Make every prompt self-contained. "
                    "Leave narrator 004 unchanged."
                ),
            }
            process_codex_hook(
                {**event, "hook_event_name": "UserPromptSubmit"},
                state_root=state,
            )

            result = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {target}\n"
                            "@@\n-old\n+new\n"
                            "*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            self.assertEqual(result, {})

    def test_referential_followup_inherits_exact_external_file_and_edit_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            target = root / "Desktop" / "backgroundswap.txt"
            other = root / "Desktop" / "other.txt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            target.parent.mkdir()
            target.write_text("old\n", encoding="utf-8")
            other.write_text("old\n", encoding="utf-8")
            base = {"session_id": "session-1", "cwd": str(repo)}
            process_codex_hook(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-1",
                    "prompt": f"Edit {target} correctly and leave narrator 004 alone.",
                },
                state_root=state,
            )
            process_codex_hook(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-2",
                    "prompt": "Make every prompt self-contained in the whole TXT file.",
                },
                state_root=state,
            )
            allowed = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {target}\n"
                            "@@\n-old\n+new\n"
                            "*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {other}\n"
                            "@@\n-old\n+new\n"
                            "*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            self.assertEqual(allowed, {})
            self.assertDenied(denied, "outside locked repository scope")

    def test_descriptive_correction_then_whole_txt_keeps_original_external_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            target = root / "Desktop" / "backgroundswap.txt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            target.parent.mkdir()
            target.write_text("old\n", encoding="utf-8")
            base = {"session_id": "session-1", "cwd": str(repo)}
            prompts = (
                f"Edit {target} correctly. Leave narrator 004 unchanged.",
                "The agent will not know what Cedar Hollow is, so make sure everything is described correctly.",
                "In the whole TXT file.",
            )
            for index, prompt in enumerate(prompts, start=1):
                process_codex_hook(
                    {
                        **base,
                        "hook_event_name": "UserPromptSubmit",
                        "turn_id": f"turn-{index}",
                        "prompt": prompt,
                    },
                    state_root=state,
                )
            result = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-3",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {target}\n"
                            "@@\n-old\n+new\n*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            self.assertEqual(result, {})

    def test_referential_only_that_file_keeps_the_exact_previous_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            target = repo / "wanted.txt"
            other = repo / "other.txt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            target.write_text("old\n", encoding="utf-8")
            other.write_text("old\n", encoding="utf-8")
            base = {"session_id": "session-1", "cwd": str(repo)}
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-1", "prompt": "Edit wanted.txt only."},
                state_root=state,
            )
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-2", "prompt": "Yes, edit only that file and finish it."},
                state_root=state,
            )
            allowed = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": "*** Begin Patch\n*** Update File: wanted.txt\n@@\n-old\n+new\n*** End Patch"},
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": "*** Begin Patch\n*** Update File: other.txt\n@@\n-old\n+new\n*** End Patch"},
                },
                state_root=state,
            )
            self.assertEqual(allowed, {})
            self.assertDenied(denied, "outside the current request's allowed paths")

    def test_referential_prohibition_drops_previous_edit_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            (repo / "wanted.txt").write_text("old\n", encoding="utf-8")
            base = {"session_id": "session-1", "cwd": str(repo)}
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-1", "prompt": "Edit wanted.txt only."},
                state_root=state,
            )
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-2", "prompt": "Do not edit it; just explain what is wrong."},
                state_root=state,
            )
            result = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": "*** Begin Patch\n*** Update File: wanted.txt\n@@\n-old\n+new\n*** End Patch"},
                },
                state_root=state,
            )
            self.assertDenied(result, "does not authorize mutation")

    def test_referential_followup_preserves_manageroo_controlled_run_requirement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            base = {"session_id": "session-1", "cwd": str(repo)}
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-1", "prompt": "$uncle-matts-project-manageroo repair this correctly."},
                state_root=state,
            )
            process_codex_hook(
                {**base, "hook_event_name": "UserPromptSubmit", "turn_id": "turn-2", "prompt": "And do not deviate from that exact repair."},
                state_root=state,
            )
            freehand = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {"command": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"},
                },
                state_root=state,
            )
            stopped = process_codex_hook(
                {**base, "hook_event_name": "Stop", "turn_id": "turn-2", "stop_hook_active": False},
                state_root=state,
            )
            self.assertDenied(freehand, "controlled Manageroo run")
            self.assertEqual(stopped["decision"], "block")

    def test_unrelated_new_prompt_does_not_inherit_previous_external_write_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            target = root / "Desktop" / "backgroundswap.txt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            target.parent.mkdir()
            target.write_text("old\n", encoding="utf-8")
            base = {"session_id": "session-1", "cwd": str(repo)}
            process_codex_hook(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-1",
                    "prompt": f"Edit {target} correctly.",
                },
                state_root=state,
            )
            process_codex_hook(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "turn_id": "turn-2",
                    "prompt": "Review README.md for clarity.",
                },
                state_root=state,
            )
            result = process_codex_hook(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "turn_id": "turn-2",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {target}\n"
                            "@@\n-old\n+new\n"
                            "*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            self.assertDenied(result, "does not authorize mutation")

    def test_private_repo_temporary_workspace_remains_available_under_narrow_output_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            output = root / "Desktop" / "finished"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            output.mkdir(parents=True)
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": f"Write only the final package to {output}.",
            }
            process_codex_hook(
                {**event, "hook_event_name": "UserPromptSubmit"},
                state_root=state,
            )
            temporary = repo / ".manageroo" / "operator-tmp" / "contact-sheets"
            result = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"mkdir -p {temporary}"},
                },
                state_root=state,
            )
            self.assertEqual(result, {})

    def test_read_only_audit_can_create_and_clean_only_private_temporary_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            event = {
                "session_id": "session-1",
                "turn_id": "turn-1",
                "cwd": str(repo),
                "prompt": "Review every image through contact sheets and report the defects.",
            }
            process_codex_hook(
                {**event, "hook_event_name": "UserPromptSubmit"},
                state_root=state,
            )
            evidence = repo / ".manageroo" / "operator-tmp" / "contact-sheets"
            create = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"mkdir -p {evidence}"},
                },
                state_root=state,
            )
            cleanup = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"rmdir {evidence}"},
                },
                state_root=state,
            )
            source_write = process_codex_hook(
                {
                    **event,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"touch {repo / 'README.md'}"},
                },
                state_root=state,
            )
            self.assertEqual(create, {})
            self.assertEqual(cleanup, {})
            self.assertDenied(source_write, "does not authorize mutation")

    def test_natural_make_contact_sheets_request_authorizes_generation(self):
        result = self._decision(
            "Make the contact sheets here and inspect every image.",
            command="mkdir -p .manageroo/operator-tmp/contact-sheets",
        )
        self.assertEqual(result, {})

    def test_explicit_current_prompt_repo_switch_replaces_previous_cwd_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "repo-a"
            second = root / "repo-b"
            state = root / "state"
            (first / ".git").mkdir(parents=True)
            (second / ".git").mkdir(parents=True)
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(first),
                    "prompt": f"Now switch to and work only in {second}. Review it.",
                },
                state_root=state,
            )
            allowed = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(second),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status --short"},
                },
                state_root=state,
            )
            denied = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(first),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status --short"},
                },
                state_root=state,
            )
            self.assertEqual(allowed, {})
            self.assertDenied(denied, "outside locked repository")

    def test_direct_repair_of_exact_repo_switches_but_editing_external_file_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "repo-a"
            second = root / "repo-b"
            external = root / "Desktop" / "notes.txt"
            state = root / "state"
            (root / ".git").mkdir()
            (first / ".git").mkdir(parents=True)
            (second / ".git").mkdir(parents=True)
            external.parent.mkdir()
            external.write_text("old\n", encoding="utf-8")

            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(first),
                    "prompt": f"Repair {second} completely.",
                },
                state_root=state,
            )
            switched = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(second),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status --short"},
                },
                state_root=state,
            )
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-2",
                    "turn_id": "turn-1",
                    "cwd": str(first),
                    "prompt": f"Edit {external} correctly.",
                },
                state_root=state,
            )
            file_edit = process_codex_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session-2",
                    "turn_id": "turn-1",
                    "cwd": str(first),
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "command": (
                            "*** Begin Patch\n"
                            f"*** Update File: {external}\n"
                            "@@\n-old\n+new\n*** End Patch"
                        )
                    },
                },
                state_root=state,
            )
            self.assertEqual(switched, {})
            self.assertEqual(file_edit, {})

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

    def test_prohibited_external_path_is_not_turned_into_a_read_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "manageroo"
            external = root / "secret.txt"
            state = root / "state"
            (repo / ".git").mkdir(parents=True)
            external.write_text("do not read\n", encoding="utf-8")
            process_codex_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session-1",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": f"Review Manageroo. Do not read {external}",
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
                    "tool_input": {"command": f"cat {external}"},
                },
                state_root=state,
            )
            self.assertDenied(denied, "outside locked repository")

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
            self.assertEqual(
                manageroo_events, {"UserPromptSubmit", "PreToolUse", "Stop"}
            )
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
