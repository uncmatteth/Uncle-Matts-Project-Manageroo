from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, TextIO

from .config_lock import config_mutation_lock
from .errors import ConfigurationError, SafetyError
from .managed_contract_common import (
    EXECUTION_INTENT_MUTATING,
    EXECUTION_INTENT_READ_ONLY,
    _COMPLETION_BINDING_FIELDS,
    _clear_completion_binding,
    _load_request_metadata,
    _persist_request_metadata,
)
from .managed_request_binding import (
    _effective_request_text,
    _execution_intent,
    _is_acknowledgment,
    _requires_managed_run,
    _resolve_repository_binding,
)
from .util import sha256_file, utc_now


def _capture_current_request_locked(
    original: Any,
    *,
    session_id: str,
    turn_id: str,
    prompt: str,
    cwd: str,
    root: Path,
    continuity_module: Any,
) -> dict[str, Any]:
    prompt = prompt.strip()
    existing = continuity_module._read_state(
        root, session_id, allow_legacy_unsigned=True
    )
    if (
        isinstance(existing, dict)
        and existing.get("status") in {"active", "waiting", "complete"}
        and _is_acknowledgment(prompt)
    ):
        state = dict(existing)
        state.pop("legacy_unsigned_migration", None)
        state.update({"cwd": cwd, "updated_at": utc_now()})
        continuity_module._save_state_locked(root, state)
        return state

    before = existing if isinstance(existing, dict) else None
    state = original(
        session_id=session_id,
        turn_id=turn_id,
        prompt=prompt,
        cwd=cwd,
        root=root,
    )
    if not isinstance(state, dict):
        return state

    unchanged_objective = bool(
        before
        and str(state.get("objective_sha256") or "")
        == str(before.get("objective_sha256") or "")
        and len(state.get("messages", [])) == len(before.get("messages", []))
    )
    if unchanged_objective:
        for field in (
            "execution_intent",
            "repository_resolution",
            "bound_repo",
            "managed_request_metadata_path",
            "managed_request_metadata_sha256",
            *_COMPLETION_BINDING_FIELDS,
        ):
            if field in before:
                state[field] = before[field]
        continuity_module._save_state_locked(root, state)
        return state

    effective_text = _effective_request_text(state)
    state["execution_intent"] = _execution_intent(effective_text or prompt)
    previous_bound = str(before.get("bound_repo") or "") if before else ""
    resolution = _resolve_repository_binding(
        prompt=prompt,
        cwd=cwd,
        previous_bound_repo=previous_bound,
        continuity_module=continuity_module,
    )
    state["repository_resolution"] = resolution
    state["bound_repo"] = str(resolution.get("repo") or "")
    if state.get("status") == "active" and state.get("managed_run_required"):
        continuity_module._finalize_state(root, state)
    else:
        continuity_module._save_state_locked(root, state)
    return state


def _audit_managed_execution(
    event: dict[str, Any], state: dict[str, Any], root: Path, continuity_module: Any
) -> dict[str, Any]:
    if not state.get("managed_run_required"):
        return {}
    tool_name = str(event.get("tool_name") or "")
    if tool_name in {"wait", "functions.wait"}:
        return {}
    if tool_name in {"write_stdin", "functions.write_stdin"}:
        payload = event.get("tool_input")
        chars = payload.get("chars") if isinstance(payload, dict) else None
        return {} if chars in {None, ""} else continuity_module._managed_denial(
            "A controlled worker cannot be steered with new freehand instructions."
        )
    tokens, command_key = continuity_module._shell_tokens(event)
    if not tokens or Path(tokens[0]).name.casefold() != "manageroo":
        return continuity_module._managed_denial(
            "This actionable repository request is automatically controller-owned."
        )
    subcommand = tokens[1] if len(tokens) > 1 else ""
    if subcommand in {"status", "report", "decisions", "projects"}:
        return {}
    if subcommand != "run":
        return continuity_module._managed_denial(
            "Only the Manageroo run, status, report, project, and decision paths "
            "belong to this request."
        )

    request_path = Path(str(state.get("managed_request_path") or ""))
    expected_hash = str(state.get("managed_request_sha256") or "")
    if not request_path.is_file() or not expected_hash:
        return continuity_module._managed_denial(
            "The controller-owned request artifact is missing."
        )
    try:
        if sha256_file(request_path) != expected_hash:
            return continuity_module._managed_denial(
                "The controller-owned request artifact changed."
            )
        metadata_loaded = _load_request_metadata(request_path, continuity_module)
        if metadata_loaded is None:
            return continuity_module._managed_denial(
                "The controller-owned request metadata is missing."
            )
        metadata, _state_root = metadata_loaded
        expected_metadata_sha256 = str(
            state.get("managed_request_metadata_sha256") or ""
        )
        metadata_path = Path(str(state.get("managed_request_metadata_path") or ""))
        if (
            not expected_metadata_sha256
            or metadata_path != request_path.with_suffix(".request.json")
            or sha256_file(metadata_path) != expected_metadata_sha256
            or str(metadata.get("session_id") or "")
            != str(state.get("session_id") or "")
            or int(metadata.get("generation", 0)) != int(state.get("generation", 0))
            or str(metadata.get("repository_root") or "")
            != str(state.get("bound_repo") or "")
            or str(metadata.get("execution_intent") or "")
            != str(state.get("execution_intent") or "")
        ):
            return continuity_module._managed_denial(
                "The controller-owned request metadata is stale or belongs to another request."
            )
    except (OSError, ConfigurationError):
        return continuity_module._managed_denial(
            "The controller-owned request artifact cannot be authenticated."
        )

    repo_text = str(state.get("bound_repo") or "")
    resolution = state.get("repository_resolution")
    if not repo_text:
        candidates = (
            list(resolution.get("candidates", []))
            if isinstance(resolution, dict)
            else []
        )
        detail = ""
        if candidates:
            detail = " Candidates: " + ", ".join(str(item) for item in candidates[:8])
        return continuity_module._managed_denial(
            "The active request has no unambiguous repository binding." + detail
        )
    repo = Path(repo_text).expanduser().resolve(strict=False)
    if continuity_module._git_root(repo) != repo:
        return continuity_module._managed_denial(
            "The bound repository is no longer a valid Git root."
        )

    apply_flag = (
        "--no-apply"
        if state.get("execution_intent") == EXECUTION_INTENT_READ_ONLY
        else "--apply"
    )
    if "--continue" in tokens:
        index = tokens.index("--continue")
        if index + 1 >= len(tokens):
            return continuity_module._managed_denial("The continuation run id is missing.")
        rewritten = [
            tokens[0],
            "run",
            "--repo",
            str(repo),
            "--brief",
            str(request_path),
            "--continue",
            tokens[index + 1],
            apply_flag,
        ]
    else:
        rewritten = [
            tokens[0],
            "run",
            "--repo",
            str(repo),
            "--brief",
            str(request_path),
            apply_flag,
        ]
    if "--json" in tokens:
        rewritten.append("--json")
    state["managed_run_started"] = True
    state["managed_run_started_at"] = utc_now()
    continuity_module._save_state(root, state)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {command_key: shlex.join(rewritten)},
        }
    }


def _recovery_command_allowed(event: dict[str, Any], session_id: str) -> bool:
    tool_name = str(event.get("tool_name") or "")
    if tool_name not in {"Bash", "exec_command", "shell", "functions.exec"}:
        return False
    payload = event.get("tool_input")
    values = payload if isinstance(payload, dict) else {}
    command = str(values.get("cmd") or values.get("command") or "")
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return False
    if len(tokens) < 4 or Path(tokens[0]).name.casefold() != "manageroo":
        return False
    if tokens[1] != "continuity-reset" or "--session-id" not in tokens:
        return False
    index = tokens.index("--session-id")
    return index + 1 < len(tokens) and tokens[index + 1] == session_id


def _fail_closed_hook_result(event: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    event_name = str(event.get("hook_event_name") or "")
    session_id = str(event.get("session_id") or "")
    recovery = shlex.join(
        ["manageroo", "continuity-reset", "--session-id", session_id]
    )
    detail = f"{type(exc).__name__}: {exc}"
    if event_name == "PreToolUse":
        if session_id and _recovery_command_allowed(event, session_id):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "🛑🦘 Manageroo continuity state is invalid, so repository work is blocked.\n"
                    f"Details: {detail}\n"
                    f"Next: `{recovery}`"
                ),
            }
        }
    if event_name == "Stop":
        return {
            "decision": "block",
            "reason": (
                "Manageroo continuity state is invalid; completion cannot be authorized. "
                f"Run `{recovery}`. Details: {detail}"
            ),
        }
    return {
        "systemMessage": (
            "🦘⚠️ Manageroo continuity state is invalid. No repository authorization was "
            f"granted. Run `{recovery}`. Details: {detail}"
        )
    }


def _run_codex_continuity_hook(
    process: Any,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    event: dict[str, Any] = {}
    try:
        value = json.load(input_stream)
        if not isinstance(value, dict):
            raise ValueError("Codex hook input must be a JSON object")
        event = value
        result = process(event)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        ConfigurationError,
        SafetyError,
    ) as exc:
        result = _fail_closed_hook_result(event, exc)
    if result:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=output_stream)
    return 0


def reset_continuity_state(
    *, session_id: str, state_root: Path, continuity_module: Any
) -> dict[str, Any]:
    root = continuity_module._safe_state_root(state_root)
    state_path = continuity_module._state_path(root, session_id)
    identity = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    quarantine = root / "quarantine"
    moved: list[str] = []
    with config_mutation_lock(state_path):
        candidates = [state_path, *(root / "requests").glob(f"{identity}-g*")]
        existing = [path for path in candidates if path.exists() or path.is_symlink()]
        if existing:
            quarantine.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                os.chmod(quarantine, 0o700)
            stamp = hashlib.sha256(utc_now().encode("utf-8")).hexdigest()[:12]
            for path in existing:
                destination = quarantine / f"{path.name}.{stamp}"
                os.replace(path, destination)
                moved.append(str(destination))
    return {
        "ok": True,
        "session_id_sha256": identity,
        "quarantined": moved,
        "state_root": str(root),
    }


def install_managed_request_policy(continuity_module: Any) -> None:
    if getattr(
        continuity_module, "_manageroo_managed_request_policy_installed", False
    ):
        return

    original_persist = continuity_module._persist_managed_request

    def persist_request(root: Path, state: dict[str, Any]) -> None:
        # The legacy persistence path reused the same generation filename when a
        # follow-up requirement was appended. Preserve every prior generation by
        # advancing before any bytes are replaced. Re-finalizing an unchanged
        # request remains idempotent.
        session_id = str(state.get("session_id") or "")
        generation = int(state.get("generation", 1))
        current_path = continuity_module._managed_request_path(
            root, session_id, generation
        )
        if current_path.is_file():
            messages = [
                str(item.get("text") or "").strip()
                for item in state.get("messages", [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            expected_text = "# Locked operator request\n\n" + "\n\n".join(
                f"## Request {index}\n\n{message}"
                for index, message in enumerate(messages, 1)
            )
            expected_text = expected_text.rstrip() + "\n"
            try:
                existing_text = current_path.read_text(
                    encoding="utf-8", errors="strict"
                )
            except (OSError, UnicodeDecodeError) as exc:
                raise ConfigurationError(
                    f"Managed request generation cannot be read safely: {current_path}"
                ) from exc
            if existing_text != expected_text:
                state["generation"] = generation + 1
                state["managed_run_started"] = False
                _clear_completion_binding(state)
        original_persist(root, state)
        _persist_request_metadata(root, state, continuity_module)

    original_capture = continuity_module._capture_current_request_locked

    def capture_request(**kwargs: Any) -> dict[str, Any]:
        return _capture_current_request_locked(
            original_capture, continuity_module=continuity_module, **kwargs
        )

    continuity_module._persist_managed_request = persist_request
    continuity_module._requires_managed_run = lambda prompt: _requires_managed_run(
        prompt, continuity_module
    )
    continuity_module._capture_current_request_locked = capture_request
    continuity_module._audit_managed_execution = (
        lambda event, state, root: _audit_managed_execution(
            event, state, root, continuity_module
        )
    )
    continuity_module.run_codex_continuity_hook = (
        lambda *, input_stream=sys.stdin, output_stream=sys.stdout: _run_codex_continuity_hook(
            continuity_module.process_codex_continuity_hook,
            input_stream=input_stream,
            output_stream=output_stream,
        )
    )
    continuity_module._manageroo_managed_request_policy_installed = True


def install_managed_contract_entrypoint_policy(
    entrypoint_module: Any, continuity_module: Any
) -> None:
    if getattr(entrypoint_module, "_manageroo_managed_contract_policy_installed", False):
        return
    original_main = entrypoint_module.main

    def main() -> int:
        argv = sys.argv[1:]
        if argv and argv[0] == "continuity-reset":
            parser = argparse.ArgumentParser(
                prog="manageroo continuity-reset",
                description="Quarantine one invalid Manageroo continuity session.",
            )
            parser.add_argument("--session-id", required=True)
            parser.add_argument("--state-root", type=Path)
            args = parser.parse_args(argv[1:])
            report = reset_continuity_state(
                session_id=args.session_id,
                state_root=args.state_root or continuity_module.continuity_state_root(),
                continuity_module=continuity_module,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        return original_main()

    entrypoint_module.main = main
    entrypoint_module._manageroo_managed_contract_policy_installed = True
