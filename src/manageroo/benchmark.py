from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path
from typing import Any

from .agent_continuity import process_codex_continuity_hook


def _text_characters(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_text_characters(item) for item in value.values())
    if isinstance(value, list):
        return sum(_text_characters(item) for item in value)
    return 0


def _estimated_tokens(characters: int) -> int:
    return math.ceil(characters / 4)


def _event(name: str, *, session: str, turn: str, cwd: Path | str, **values: Any) -> dict[str, Any]:
    return {
        "hook_event_name": name,
        "session_id": session,
        "turn_id": turn,
        "cwd": str(cwd),
        **values,
    }


def run_continuity_benchmark() -> dict[str, Any]:
    """Exercise controller behavior and prompt overhead without calling a model."""
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="manageroo-benchmark-") as temp:
        base = Path(temp)
        repo = base / "repo"
        other = base / "other"
        repo.mkdir()
        other.mkdir()
        (repo / ".git").mkdir()
        (other / ".git").mkdir()
        state_root = base / "state"

        first = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="continuity",
                turn="1",
                cwd=repo,
                prompt="Audit install behavior.",
            ),
            state_root=state_root,
        )
        addition = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="continuity",
                turn="2",
                cwd=repo,
                prompt="Also add guided uninstall.",
            ),
            state_root=state_root,
        )
        question = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="continuity",
                turn="3",
                cwd=repo,
                prompt="Why was the status output noisy?",
            ),
            state_root=state_root,
        )
        recovery_outputs = {
            event_name: str(
                process_codex_continuity_hook(
                    _event(event_name, session="continuity", turn="4", cwd=repo),
                    state_root=state_root,
                )
                .get("hookSpecificOutput", {})
                .get("additionalContext", "")
            )
            for event_name in ("SessionStart", "SubagentStart", "PostCompact")
        }
        recovery_text = recovery_outputs["PostCompact"]

        process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="scope",
                turn="1",
                cwd=repo,
                prompt="Work only in this repository. Fix and verify it.",
            ),
            state_root=state_root,
        )
        denied = process_codex_continuity_hook(
            _event(
                "PreToolUse",
                session="scope",
                turn="1",
                cwd=repo,
                tool_name="exec_command",
                tool_input={"cmd": f"touch {other / 'drift.txt'}"},
            ),
            state_root=state_root,
        )

        pause_root = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="pause",
                turn="1",
                cwd=repo,
                prompt="Investigate the local pipeline.",
            ),
            state_root=state_root,
        )
        paused = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="pause",
                turn="2",
                cwd=repo,
                prompt="stop",
            ),
            state_root=state_root,
        )
        paused_tool = process_codex_continuity_hook(
            _event(
                "PreToolUse",
                session="pause",
                turn="2",
                cwd=repo,
                tool_name="exec_command",
                tool_input={"cmd": "pwd"},
            ),
            state_root=state_root,
        )

        finish_root = process_codex_continuity_hook(
            _event(
                "UserPromptSubmit",
                session="finish",
                turn="1",
                cwd=repo,
                prompt="Finish and verify the job.",
            ),
            state_root=state_root,
        )
        ordinary_stop = process_codex_continuity_hook(
            _event(
                "Stop",
                session="finish",
                turn="1",
                cwd=repo,
                last_assistant_message="Work is probably fine.",
            ),
            state_root=state_root,
        )

    routine_events = (
        first,
        addition,
        question,
        pause_root,
        paused,
        finish_root,
    )
    routine_characters = sum(_text_characters(item) for item in routine_events)
    recovery_character_counts = {
        event_name: len(text) for event_name, text in recovery_outputs.items()
    }
    recovery_characters = max(recovery_character_counts.values())
    controls = {
        "routine_hooks_silent": routine_characters == 0,
        "active_requests_recovered": (
            "Audit install behavior." in recovery_text
            and "Also add guided uninstall." in recovery_text
        ),
        "side_question_not_added": "Why was the status output noisy?" not in recovery_text,
        "excluded_mutation_blocked": (
            denied.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        ),
        "paused_tools_blocked": (
            paused_tool.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        ),
        "unproved_completion_blocked": (
            ordinary_stop.get("decision") == "block"
            and "COMPLETE" in str(ordinary_stop.get("reason") or "")
        ),
    }
    recovery_tokens = _estimated_tokens(recovery_characters)
    ok = all(controls.values()) and routine_characters == 0 and recovery_tokens <= 200
    return {
        "ok": ok,
        "kind": "deterministic-controller",
        "model_calls": 0,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "routine": {
            "events": len(routine_events),
            "emitted_characters": routine_characters,
            "estimated_tokens": _estimated_tokens(routine_characters),
        },
        "recovery": {
            "event_characters": recovery_character_counts,
            "emitted_characters": recovery_characters,
            "estimated_tokens": recovery_tokens,
            "token_budget": 200,
        },
        "controls": controls,
        "limits": (
            "This deterministic benchmark measures hook overhead and controller guardrails; "
            "it does not measure model code quality. A live A/B requires repeated matched "
            "agent runs and spends model tokens."
        ),
    }


def format_continuity_benchmark(report: dict[str, Any]) -> str:
    label = "PASS" if report.get("ok") else "FAIL"
    controls = report.get("controls", {})
    passed = sum(bool(value) for value in controls.values())
    total = len(controls)
    return "\n".join(
        [
            f"MANAGEROO CONTINUITY BENCHMARK: {label}",
            f"Routine prompts: {report['routine']['estimated_tokens']} estimated tokens added",
            (
                "Recovery only: "
                f"{report['recovery']['estimated_tokens']} estimated tokens "
                f"(budget {report['recovery']['token_budget']})"
            ),
            f"Continuity controls: {passed}/{total} passed",
            "Model calls: 0",
            f"Limit: {report['limits']}",
        ]
    ) + "\n"
