from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import manageroo.agent_continuity as agent_continuity_module

from manageroo.agent_continuity import (
    INTERNAL_CONTINUATION_PREFIX,
    _git_root,
    capture_current_request,
    install_codex_continuity_hooks,
    process_codex_continuity_hook,
    remove_codex_continuity_hooks,
)
from manageroo.errors import ConfigurationError
from manageroo.execution_mode import EXECUTION_MODE_ENV, STRUCTURED_WORKER_MODE


class AgentContinuityTests(unittest.TestCase):
    def test_session_start_without_saved_work_injects_global_controller_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": "fresh-session",
                    "turn_id": "turn-1",
                    "cwd": str(Path(temp)),
                },
                state_root=Path(temp) / "state",
            )

            context = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Auto-select skills", context)
            self.assertIn("automatically uses", context)
            self.assertIn("never initialize home", context)
            self.assertIn("exact-request Manageroo run proves", context)
            self.assertNotIn("✅ Done", context)

    def test_structured_worker_mode_bypasses_continuity_hooks_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "continuity-state"
            events = (
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "worker-session",
                    "turn_id": "turn-1",
                    "cwd": temp,
                    "prompt": "Return only the schema result.",
                },
                {
                    "hook_event_name": "Stop",
                    "session_id": "worker-session",
                    "turn_id": "turn-1",
                    "cwd": temp,
                    "last_assistant_message": '{"ok": true}',
                },
            )

            with mock.patch.dict(
                agent_continuity_module.os.environ,
                {EXECUTION_MODE_ENV: STRUCTURED_WORKER_MODE},
                clear=False,
            ):
                results = [
                    process_codex_continuity_hook(event, state_root=root)
                    for event in events
                ]

            self.assertEqual(results, [{}, {}])
            self.assertFalse(root.exists())

    def _shell_decision(
        self,
        root: Path,
        repo: Path,
        prompt: str,
        command: str,
        *,
        event_cwd: Path | None = None,
    ):
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
        return process_codex_continuity_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": str(event_cwd or repo),
                "tool_name": "exec_command",
                "tool_input": {"cmd": command},
            },
            state_root=root,
        )

    def test_only_file_rejects_a_different_file_inside_current_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "allowed.txt"
            result = self._shell_decision(
                root / "state",
                repo,
                f"Edit only {allowed}.",
                f"touch {repo / 'different.txt'}",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_only_repo_relative_file_rejects_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root / "state",
                repo,
                "Edit only src/allowed.py.",
                "touch src/different.py",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_only_file_rejects_rm_of_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root / "state",
                repo,
                f"Edit only {repo / 'allowed.txt'}.",
                "rm different.txt",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_only_file_rejects_python_write_of_a_different_repository_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            result = self._shell_decision(
                root / "state",
                repo,
                f"Edit only {repo / 'allowed.txt'}.",
                "python3 -c \"from pathlib import Path; Path('different.txt').write_text('x')\"",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_explicit_exclusion_blocks_supported_mutation_forms(self):
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
                    "prompt": "Fix this repository but do not edit blocked.txt.",
                },
                state_root=root / "state",
            )
            events = (
                {
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": "*** Begin Patch\n*** Update File: blocked.txt\n*** End Patch"
                    },
                },
                {
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "touch blocked.txt"},
                },
                {
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "rm blocked.txt"},
                },
                {
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "python3 -c \"from pathlib import Path; Path('blocked.txt').write_text('x')\""
                    },
                },
            )
            for event in events:
                with self.subTest(event=event):
                    result = process_codex_continuity_hook(
                        {
                            "hook_event_name": "PreToolUse",
                            "session_id": "session",
                            "turn_id": "turn-1",
                            "cwd": str(repo),
                            **event,
                        },
                        state_root=root / "state",
                    )
                    self.assertEqual(
                        result["hookSpecificOutput"]["permissionDecision"],
                        "deny",
                    )

    def test_only_file_shell_mutation_is_routed_through_manageroo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "allowed.txt"
            result = self._shell_decision(
                root / "state",
                repo,
                f"Edit only {allowed}.",
                f"touch {allowed}",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_direct_relative_shell_target_is_routed_through_manageroo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / ".git").mkdir()

            result = self._shell_decision(
                root / "state",
                repo,
                "Edit src/allowed.py and leave the rest alone.",
                "touch src/allowed.py",
            )

            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_exact_target_cannot_hide_an_unrequested_compound_side_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / ".git").mkdir()

            other_repo = root / "other-repo"
            other_repo.mkdir()
            (other_repo / ".git").mkdir()
            result = self._shell_decision(
                root / "state",
                repo,
                "Edit src/allowed.py and leave the rest alone.",
                f"touch src/allowed.py; touch {other_repo / 'drift.py'}",
            )

            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_structured_patch_to_direct_relative_target_is_routed_through_manageroo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / ".git").mkdir()
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "prompt": "Edit src/allowed.py and leave the rest alone.",
                },
                state_root=root / "state",
            )

            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": str(repo),
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": "*** Begin Patch\n*** Update File: src/allowed.py\n*** End Patch"
                    },
                },
                state_root=root / "state",
            )

            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

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

    def test_malformed_state_blocks_capture_without_overwriting_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Preserve this unfinished request.",
                cwd="/project",
                state_root=root,
            )
            state_path = next(root.glob("*.json"))
            malformed = b'{"schema_version": 1, "messages": ['
            state_path.write_bytes(malformed)

            with self.assertRaisesRegex(ConfigurationError, "invalid JSON"):
                capture_current_request(
                    session_id="session",
                    turn_id="turn-2",
                    prompt="Do not replace corrupt state.",
                    cwd="/project",
                    state_root=root,
                )

            self.assertEqual(state_path.read_bytes(), malformed)

    def test_unsupported_state_version_blocks_capture_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Preserve this unfinished request.",
                cwd="/project",
                state_root=root,
            )
            state_path = next(root.glob("*.json"))
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["schema_version"] = 999
            unsupported = json.dumps(state, sort_keys=True).encode("utf-8")
            state_path.write_bytes(unsupported)

            with self.assertRaisesRegex(ConfigurationError, "unsupported schema version"):
                capture_current_request(
                    session_id="session",
                    turn_id="turn-2",
                    prompt="Do not replace unsupported state.",
                    cwd="/project",
                    state_root=root,
                )

            self.assertEqual(state_path.read_bytes(), unsupported)

    def test_concurrent_additions_preserve_both_operator_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Repair the continuity state.",
                cwd="/project",
                state_root=root,
            )
            real_read_state = agent_continuity_module._read_state
            reads_complete = threading.Barrier(2)
            errors: list[BaseException] = []

            def synchronized_read(*args, **kwargs):
                state = real_read_state(*args, **kwargs)
                try:
                    reads_complete.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return state

            def capture(turn_id: str, prompt: str) -> None:
                try:
                    capture_current_request(
                        session_id="session",
                        turn_id=turn_id,
                        prompt=prompt,
                        cwd="/project",
                        state_root=root,
                    )
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                agent_continuity_module,
                "_read_state",
                side_effect=synchronized_read,
            ):
                threads = [
                    threading.Thread(target=capture, args=("turn-2", "Add request two.")),
                    threading.Thread(target=capture, args=("turn-3", "Add request three.")),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            state = real_read_state(root, "session")
            self.assertIsNotNone(state)
            self.assertCountEqual(
                [item["turn_id"] for item in state["messages"]],
                ["turn-1", "turn-2", "turn-3"],
            )

    def test_concurrent_prompt_hooks_preserve_both_operator_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Repair the continuity state.",
                cwd="/project",
                state_root=root,
            )
            real_save_state = agent_continuity_module._save_state
            newer_state_saved = threading.Event()
            errors: list[BaseException] = []

            def ordered_save(state_root, state):
                if len(state["messages"]) == 2:
                    if not newer_state_saved.wait(timeout=5):
                        raise TimeoutError("newer prompt state was not ready")
                    real_save_state(state_root, state)
                    return
                real_save_state(state_root, state)
                newer_state_saved.set()

            def submit(turn_id: str, prompt: str) -> None:
                try:
                    process_codex_continuity_hook(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "session_id": "session",
                            "turn_id": turn_id,
                            "cwd": "/project",
                            "prompt": prompt,
                        },
                        state_root=root,
                    )
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                agent_continuity_module,
                "_save_state",
                side_effect=ordered_save,
            ):
                threads = [
                    threading.Thread(target=submit, args=("turn-2", "Add request two.")),
                    threading.Thread(target=submit, args=("turn-3", "Add request three.")),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            state = agent_continuity_module._read_state(root, "session")
            self.assertIsNotNone(state)
            self.assertCountEqual(
                [item["turn_id"] for item in state["messages"]],
                ["turn-1", "turn-2", "turn-3"],
            )

    def test_stop_hook_does_not_touch_state_or_discard_new_operator_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Repair the continuity state.",
                },
                state_root=root,
            )
            self.assertEqual(
                process_codex_continuity_hook(
                    {
                        "hook_event_name": "Stop",
                        "session_id": "session",
                        "turn_id": "turn-1",
                        "cwd": "/project",
                        "last_assistant_message": "Ordinary response.",
                    },
                    state_root=root,
                ),
                {},
            )
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "Also preserve this operator request.",
                },
                state_root=root,
            )

            state = agent_continuity_module._read_state(root, "session")
            self.assertIsNotNone(state)
            self.assertEqual(
                [item["turn_id"] for item in state["messages"]],
                ["turn-1", "turn-2"],
            )
            self.assertEqual(state["status"], "active")

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
                    "prompt": "No, use only /opt/new-project. That is the repository.",
                },
                state_root=root,
            )
            self.assertEqual(corrected, {})
            state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["text"] for item in state["messages"]],
                ["No, use only /opt/new-project. That is the repository."],
            )

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

    def test_bare_stop_pauses_the_existing_objective(self):
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
            self.assertEqual(
                [item["text"] for item in state["messages"]],
                ["Keep working on the old task."],
            )
            self.assertEqual(state["status"], "paused")
            self.assertEqual(state["generation"], 1)

    def test_natural_stop_and_wait_language_pauses_until_operator_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the release.",
                cwd="/project",
                state_root=root,
            )

            paused = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop and just wait. I will tell you when you can work again.",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(paused["status"], "paused")
            self.assertEqual([item["text"] for item in paused["messages"]], ["Complete the release."])
            stopped = process_codex_continuity_hook(
                {
                    "hook_event_name": "Stop",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "last_assistant_message": "Stopped. I will wait.",
                },
                state_root=root,
            )
            self.assertEqual(stopped, {})

    def test_question_during_pause_does_not_resume_saved_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the release.",
                cwd="/project",
                state_root=root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="I told you to stop.",
                cwd="/project",
                state_root=root,
            )

            paused = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="Why did Manageroo ignore my instruction?",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(paused["status"], "paused")
            self.assertEqual([item["text"] for item in paused["messages"]], ["Complete the release."])

    def test_explicit_resume_reactivates_the_saved_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the release.",
                cwd="/project",
                state_root=root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Pause until I tell you to resume.",
                cwd="/project",
                state_root=root,
            )

            resumed = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="Resume the saved work now.",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(resumed["status"], "active")
            self.assertEqual([item["text"] for item in resumed["messages"]], ["Complete the release."])

    def test_operator_reaffirmation_reactivates_paused_work_without_replacing_it(self):
        prompts = (
            "I have told it to do what I said and it is blocking me.",
            "Jesus Christ, I told you what to do next, don't tell me no.",
            "Do what I said.",
        )
        for prompt in prompts:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                capture_current_request(
                    session_id="session",
                    turn_id="turn-1",
                    prompt="Complete the release.",
                    cwd="/project",
                    state_root=root,
                )
                capture_current_request(
                    session_id="session",
                    turn_id="turn-2",
                    prompt="Stop and wait until I tell you what to do.",
                    cwd="/project",
                    state_root=root,
                )

                resumed = capture_current_request(
                    session_id="session",
                    turn_id="turn-3",
                    prompt=prompt,
                    cwd="/project",
                    state_root=root,
                )

                self.assertEqual(resumed["status"], "active")
                self.assertEqual(
                    [item["text"] for item in resumed["messages"]],
                    ["Complete the release."],
                )

    def test_operator_stop_reaffirmation_remains_paused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the release.",
                cwd="/project",
                state_root=root,
            )

            paused = capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="I told you to stop and wait.",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(paused["status"], "paused")
            self.assertEqual(
                [item["text"] for item in paused["messages"]],
                ["Complete the release."],
            )

    def test_clear_new_work_request_replaces_paused_backlog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the entire release.",
                cwd="/project",
                state_root=root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop and wait until I tell you what to do.",
                cwd="/project",
                state_root=root,
            )

            resumed = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="Please fix only the pause behavior.",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(resumed["status"], "active")
            self.assertEqual(
                [item["text"] for item in resumed["messages"]],
                ["Please fix only the pause behavior."],
            )
            self.assertEqual(resumed["generation"], 2)

    def test_rough_actionable_preamble_replaces_paused_backlog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Complete the old release.",
                cwd="/project",
                state_root=root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop working and pause.",
                cwd="/project",
                state_root=root,
            )

            resumed = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt=(
                    "yes, so like the install process please review that. "
                    "it's supposed to do a specific bunch of stuff but i don't know if it does"
                ),
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(resumed["status"], "active")
            self.assertEqual(
                [item["text"] for item in resumed["messages"]],
                [
                    "yes, so like the install process please review that. "
                    "it's supposed to do a specific bunch of stuff but i don't know if it does"
                ],
            )
            self.assertEqual(resumed["generation"], 2)

    def test_first_clear_now_do_instruction_replaces_paused_backlog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            capture_current_request(
                session_id="session",
                turn_id="turn-1",
                prompt="Use the wrong old scene workflow.",
                cwd="/project",
                state_root=root,
            )
            capture_current_request(
                session_id="session",
                turn_id="turn-2",
                prompt="Stop. Do not run anything else.",
                cwd="/project",
                state_root=root,
            )

            resumed = capture_current_request(
                session_id="session",
                turn_id="turn-3",
                prompt="I know, now do the first fucking chapter.",
                cwd="/project",
                state_root=root,
            )

            self.assertEqual(resumed["status"], "active")
            self.assertEqual(
                [item["text"] for item in resumed["messages"]],
                ["I know, now do the first fucking chapter."],
            )
            self.assertEqual(resumed["generation"], 2)

    def test_paused_state_is_advisory_and_keeps_ordinary_tools_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Complete the release.",
                },
                state_root=root,
            )
            paused = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "I told you to stop and wait.",
                },
                state_root=root,
            )
            self.assertEqual(paused, {})
            recovered = process_codex_continuity_hook(
                {
                    "hook_event_name": "PostCompact",
                    "session_id": "session",
                    "turn_id": "turn-3",
                    "cwd": "/project",
                },
                state_root=root,
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Manageroo continuity: paused", recovered)
            self.assertIn("current operator request wins", recovered)
            self.assertNotIn("Do not resume or use tools", recovered)
            self.assertNotIn("Finish all active requests", recovered)

            allowed = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "pwd"},
                },
                state_root=root,
            )
            self.assertEqual(allowed, {})

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

    def test_prompt_hook_saves_long_request_without_printing_or_injecting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            long_detail = "terminal-output-that-must-not-be-replayed " * 80
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
                    "prompt": f"Also improve the progress messages. {long_detail}",
                },
                state_root=root,
            )
            self.assertEqual(first, {})
            self.assertEqual(second, {})

            state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(
                state["messages"][1]["text"],
                f"Also improve the progress messages. {long_detail}".strip(),
            )

    def test_recovery_context_omits_busy_status_markers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Finish the active request.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "Also make the messages fun.",
                },
                state_root=root,
            )

            self.assertEqual(result, {})
            recovered = process_codex_continuity_hook(
                {
                    "hook_event_name": "PostCompact",
                    "session_id": "session",
                    "turn_id": "turn-3",
                    "cwd": "/project",
                },
                state_root=root,
            )["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Finish the active request.", recovered)
            self.assertIn("Also make the messages fun.", recovered)
            self.assertNotIn("Manageroo update", recovered)
            self.assertNotIn("Manageroo is doing", recovered)
            self.assertNotIn("📍 Status", recovered)

    def test_routine_prompt_capture_is_silent_and_context_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Repair the release and verify it.",
                },
                state_root=root,
            )

            self.assertEqual(result, {})
            state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["text"] for item in state["messages"]],
                ["Repair the release and verify it."],
            )

    def test_side_question_does_not_expand_the_active_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Repair the continuity output and verify it.",
                },
                state_root=root,
            )
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "Why did Manageroo print the whole request again?",
                },
                state_root=root,
            )

            state = json.loads(next(root.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(
                [item["text"] for item in state["messages"]],
                ["Repair the continuity output and verify it."],
            )
            self.assertEqual(result, {})

    def test_recovery_projection_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session",
                "turn_id": "turn-1",
                "cwd": "/project",
                "prompt": "Fix the useful progress summary and verify the output.",
            }
            first = process_codex_continuity_hook(event, state_root=root)
            second = process_codex_continuity_hook(event, state_root=root)
            self.assertEqual(first, {})
            self.assertEqual(second, {})
            recovery_event = {
                "hook_event_name": "PostCompact",
                "session_id": "session",
                "turn_id": "turn-2",
                "cwd": "/project",
            }
            first_recovery = process_codex_continuity_hook(recovery_event, state_root=root)
            second_recovery = process_codex_continuity_hook(recovery_event, state_root=root)
            self.assertEqual(first_recovery, second_recovery)
            self.assertIn(
                "Fix the useful progress summary and verify the output.",
                first_recovery["hookSpecificOutput"]["additionalContext"],
            )

    def test_prompt_with_status_language_is_still_silent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": (
                        "Manageroo is doing: keep the agent in line. That generic line is "
                        "useless; make it say what the current work actually is without "
                        "passing extra tokens."
                    ),
                },
                state_root=root,
            )

            self.assertEqual(result, {})

    def test_operator_hooks_never_advertise_a_completion_password(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            started = process_codex_continuity_hook(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": "session",
                    "turn_id": "turn-0",
                    "cwd": "/project",
                },
                state_root=root,
            )
            first = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Fix the first issue.",
                },
                state_root=root,
            )
            changed = process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-2",
                    "cwd": "/project",
                    "prompt": "Also fix the second issue.",
                },
                state_root=root,
            )

            context = started["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("✅ Done", context)
            self.assertNotIn("completion line", context.casefold())
            self.assertEqual(first, {})
            self.assertEqual(changed, {})

    def test_actionable_request_blocks_freehand_read_only_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process_codex_continuity_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "prompt": "Fix the Manageroo prompt partitioning and publish the release.",
                },
                state_root=root,
            )

            result = process_codex_continuity_hook(
                {
                    "hook_event_name": "PreToolUse",
                    "session_id": "session",
                    "turn_id": "turn-1",
                    "cwd": "/project",
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "pwd"},
                },
                state_root=root,
            )

            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("automatically controller-owned", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_stop_hook_requires_controller_proof_not_operator_chat_claim(self):
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
            self.assertEqual(response, {})
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
            self.assertIn("COMPLETE and applied proof", stopped["reason"])

    def test_read_only_shell_commands_cannot_bypass_an_active_managed_request(self):
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
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_external_copy_source_is_read_only_when_destination_is_in_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            external_input = root / "image-library" / "CONTENT_IMAGE.png"
            external_input.parent.mkdir()
            external_input.write_bytes(b"fixture")

            result = self._shell_decision(
                root / "state",
                repo,
                "Use the supplied content image in this project.",
                f"cp {external_input} input/CONTENT_IMAGE.png",
            )

            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_copy_destination_outside_explicit_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            outside = root / "other-repo"
            outside.mkdir()
            (outside / ".git").mkdir()

            result = self._shell_decision(
                root / "state",
                repo,
                "Work only in this repository. Copy the generated image into it.",
                f"cp generated.png {outside / 'CONTENT_IMAGE.png'}",
            )

            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_python_copy_source_is_read_only_when_destination_is_in_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            external_input = root / "image-library" / "CONTENT_IMAGE.png"
            external_input.parent.mkdir()
            external_input.write_bytes(b"fixture")

            result = self._shell_decision(
                root / "state",
                repo,
                "Use the supplied content image in this project.",
                (
                    "python3 -c \"import shutil; "
                    f"shutil.copy({str(external_input)!r}, 'input/CONTENT_IMAGE.png')\""
                ),
            )

            self.assertNotEqual(
                result.get("hookSpecificOutput", {}).get("permissionDecision"),
                "deny",
            )

    def test_temporary_evidence_is_controller_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            temporary_root = next(
                (
                    candidate
                    for candidate in (Path("/tmp"), Path("/dev/shm"))
                    if candidate.is_dir() and _git_root(candidate) is None
                ),
                None,
            )
            if temporary_root is None:
                self.skipTest("No supported temporary root is outside another Git repository.")
            result = self._shell_decision(
                root / "state",
                repo,
                "Inspect this repository and report the result.",
                f"touch {temporary_root / 'manageroo-bounded-proof.txt'}",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_current_repository_mutation_requires_controlled_executor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()

            result = self._shell_decision(
                root / "state",
                repo,
                "Fix this repository and verify it.",
                "mkdir generated-proof",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_requested_commit_and_push_stay_inside_controlled_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            for command in ("git commit -m scoped-fix", "git push origin main"):
                with self.subTest(command=command):
                    result = self._shell_decision(
                        root / "state",
                        repo,
                        "Commit and push everything in this repository.",
                        command,
                    )
                    self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_tool_cwd_cannot_escape_an_explicit_repository_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            other_repo = root / "other-repo"
            repo.mkdir()
            other_repo.mkdir()
            (repo / ".git").mkdir()
            (other_repo / ".git").mkdir()
            result = self._shell_decision(
                root / "state",
                repo,
                "Work only in this repository. Fix and verify it.",
                "touch drift.py",
                event_cwd=other_repo,
            )
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
            )

    def test_read_only_redirect_cannot_bypass_active_managed_request(self):
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
                    "permission_mode": "read-only",
                    "tool_name": "exec_command",
                    "tool_input": {
                        "cmd": "diff -qr src /opt/manageroo/app >/dev/null"
                    },
                },
                state_root=root / "state",
            )
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_external_target_is_blocked_by_automatic_controller_scope(self):
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
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

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

    def test_current_git_root_is_the_automatic_controller_scope(self):
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
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

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
            reason = result["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("Manageroo stopped freehand work.", reason)
            self.assertIn("Why:", reason)
            self.assertIn("Next:", reason)

    def test_sentence_punctuation_does_not_bypass_automatic_controller(self):
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
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

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
            self.assertIn("PreToolUse", written["hooks"])
            self.assertIn("Stop", written["hooks"])

    def test_uninstall_removes_only_hooks_for_the_selected_manageroo_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            codex_home = Path(temp) / ".codex"
            selected = Path(temp) / "bin" / "manageroo"
            other = Path(temp) / "other" / "manageroo"
            install_codex_continuity_hooks(
                codex_home=codex_home,
                manageroo_command=selected,
            )
            hooks_path = codex_home / "hooks.json"
            payload = json.loads(hooks_path.read_text(encoding="utf-8"))
            payload["hooks"]["UserPromptSubmit"].append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{other} agent-continuity-hook",
                        }
                    ]
                }
            )
            payload["hooks"]["UserPromptSubmit"].append(
                {"hooks": [{"type": "command", "command": "gbrain prompt hook"}]}
            )
            hooks_path.write_text(json.dumps(payload), encoding="utf-8")

            result = remove_codex_continuity_hooks(
                codex_home=codex_home,
                manageroo_command=selected,
            )

            self.assertTrue(result["changed"])
            rendered = hooks_path.read_text(encoding="utf-8")
            self.assertNotIn(str(selected), rendered)
            self.assertIn(str(other), rendered)
            self.assertIn("gbrain prompt hook", rendered)


if __name__ == "__main__":
    unittest.main()
