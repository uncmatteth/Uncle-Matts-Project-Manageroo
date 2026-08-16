from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .managed_contract_common import _clear_completion_binding
from .managed_request_binding import _execution_intent
from .util import sha256_file, utc_now


_REPLACE_FALLBACK = re.compile(
    r"\b(?:replace|supersede)\s+(?:the\s+)?(?:previous|current|old)\s+"
    r"(?:request|task|work)\b|\bdo\s+only\s+this\s+instead\b|"
    r"\bnew\s+task\s+instead\b",
    re.IGNORECASE,
)
_NATURAL_CORRECTION_FALLBACK = re.compile(
    r"^\s*(?:no|actually|wrong|correction)\b.*"
    r"(?:use|switch\s+to|work\s+(?:in|on)|repo(?:sitory)?|path|file)",
    re.IGNORECASE,
)

_CANCEL_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:cancel|drop|forget)"
    r"(?:\s+(?:this|the|my|current|active))?"
    r"(?:\s+(?:request|task|work|job))?\s*[.!]*\s*$",
    re.IGNORECASE,
)


def _is_replacement(prompt: str, continuity_module: Any) -> bool:
    text = prompt.strip()
    replace_pattern = getattr(
        continuity_module, "_REPLACE_REQUEST", _REPLACE_FALLBACK
    )
    correction_pattern = getattr(
        continuity_module, "_NATURAL_CORRECTION", _NATURAL_CORRECTION_FALLBACK
    )
    return bool(
        replace_pattern.search(text)
        or (not text.endswith("?") and correction_pattern.search(text))
    )


def _fresh_state_after_cancel(
    *,
    existing: dict[str, Any],
    session_id: str,
    turn_id: str,
    prompt: str,
    cwd: str,
    root: Path,
    continuity_module: Any,
    managed_hook_module: Any,
) -> dict[str, Any]:
    messages = [continuity_module._message(prompt, turn_id, "root")]
    state = {
        "schema_version": continuity_module.STATE_SCHEMA_VERSION,
        "session_id": session_id,
        "status": "active",
        "cwd": cwd,
        "messages": messages,
        "objective_sha256": continuity_module._objective_hash(messages),
        "generation": int(existing.get("generation", 1)) + 1,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "waiting_reason": "",
        "managed_run_required": continuity_module._requires_managed_run(prompt),
        "managed_run_started": False,
        "execution_intent": _execution_intent(prompt),
    }
    resolution = managed_hook_module._resolve_repository_binding(
        prompt=prompt,
        cwd=cwd,
        previous_bound_repo="",
        continuity_module=continuity_module,
    )
    state["repository_resolution"] = resolution
    state["bound_repo"] = str(resolution.get("repo") or "")
    _clear_completion_binding(state)
    return continuity_module._finalize_state(root, state)


def install_request_lifecycle_policy(
    continuity_module: Any, managed_hook_module: Any
) -> None:
    if getattr(
        continuity_module, "_manageroo_request_lifecycle_policy_installed", False
    ):
        return

    original_resolver = managed_hook_module._resolve_repository_binding

    def resolve_repository_binding(
        *,
        prompt: str,
        cwd: str,
        previous_bound_repo: str = "",
        projects: list[dict[str, Any]] | None = None,
        continuity_module: Any,
    ) -> dict[str, Any]:
        if previous_bound_repo and _is_replacement(prompt, continuity_module):
            previous_bound_repo = ""
        return original_resolver(
            prompt=prompt,
            cwd=cwd,
            previous_bound_repo=previous_bound_repo,
            projects=projects,
            continuity_module=continuity_module,
        )

    managed_hook_module._resolve_repository_binding = resolve_repository_binding

    original_capture = continuity_module._capture_current_request_locked

    def capture_request(
        *,
        session_id: str,
        turn_id: str,
        prompt: str,
        cwd: str,
        root: Path,
    ) -> dict[str, Any]:
        text = prompt.strip()
        existing = continuity_module._read_state(
            root, session_id, allow_legacy_unsigned=True
        )
        if existing is not None and existing.pop("legacy_unsigned_migration", False):
            continuity_module._save_state_locked(root, existing)

        if _CANCEL_REQUEST.fullmatch(text):
            messages = [
                item
                for item in (existing or {}).get("messages", [])
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            state = dict(existing or {})
            state.update(
                {
                    "schema_version": continuity_module.STATE_SCHEMA_VERSION,
                    "session_id": session_id,
                    "status": "cancelled",
                    "cwd": cwd,
                    "messages": messages,
                    "objective_sha256": continuity_module._objective_hash(messages),
                    "generation": int((existing or {}).get("generation", 1)),
                    "created_at": str((existing or {}).get("created_at") or utc_now()),
                    "updated_at": utc_now(),
                    "waiting_reason": text or "cancelled",
                    "cancelled_at": utc_now(),
                    "managed_run_required": False,
                    "managed_run_started": False,
                }
            )
            _clear_completion_binding(state)
            continuity_module._save_state_locked(root, state)
            return state

        if (
            isinstance(existing, dict)
            and existing.get("status") == "cancelled"
            and continuity_module._requires_managed_run(text)
        ):
            return _fresh_state_after_cancel(
                existing=existing,
                session_id=session_id,
                turn_id=turn_id,
                prompt=text,
                cwd=cwd,
                root=root,
                continuity_module=continuity_module,
                managed_hook_module=managed_hook_module,
            )

        if (
            isinstance(existing, dict)
            and existing.get("status") in {"active", "waiting", "paused"}
            and existing.get("bound_repo")
            and not _is_replacement(text, continuity_module)
        ):
            resolution = managed_hook_module._resolve_repository_binding(
                prompt=text,
                cwd=cwd,
                previous_bound_repo=str(existing.get("bound_repo") or ""),
                continuity_module=continuity_module,
            )
            if resolution.get("status") in {"conflict", "ambiguous", "missing"} and str(
                resolution.get("source") or ""
            ) in {"explicit-path", "explicit-project-name"}:
                state = dict(existing)
                state.update(
                    {
                        "updated_at": utc_now(),
                        "last_rejected_request": {
                            "turn_id": turn_id,
                            "text": text,
                            "reason": str(
                                resolution.get("detail")
                                or "Repository change requires an explicit replacement request."
                            ),
                            "resolution": resolution,
                            "at": utc_now(),
                        },
                    }
                )
                continuity_module._save_state_locked(root, state)
                return state

        state = original_capture(
            session_id=session_id,
            turn_id=turn_id,
            prompt=text,
            cwd=cwd,
            root=root,
        )
        metadata_text = str(state.get("managed_request_metadata_path") or "")
        if metadata_text:
            metadata_path = Path(metadata_text)
            if metadata_path.is_file():
                current_metadata_sha256 = sha256_file(metadata_path)
                if (
                    state.get("managed_request_metadata_sha256")
                    != current_metadata_sha256
                ):
                    state["managed_request_metadata_sha256"] = current_metadata_sha256
                    continuity_module._save_state_locked(root, state)
        return state

    continuity_module._capture_current_request_locked = capture_request

    original_audit = continuity_module._audit_managed_execution

    def audit_managed_execution(
        event: dict[str, Any], state: dict[str, Any], root: Path
    ) -> dict[str, Any]:
        if state.get("status") == "paused" and state.get("managed_run_required"):
            tokens, _command_key = continuity_module._shell_tokens(event)
            subcommand = tokens[1] if len(tokens) > 1 else ""
            if (
                tokens
                and Path(tokens[0]).name.casefold() == "manageroo"
                and subcommand in {"status", "report", "decisions"}
            ):
                return {}
            return continuity_module._managed_denial(
                "The active Manageroo request is paused. Resume or replace it "
                "before work continues."
            )
        return original_audit(event, state, root)

    continuity_module._audit_managed_execution = audit_managed_execution

    original_render = getattr(continuity_module, "render_active_objective", None)
    if callable(original_render):
        def render_active_objective(state: dict[str, Any]) -> str:
            rendered = original_render(state)
            rejected = state.get("last_rejected_request")
            if isinstance(rejected, dict) and rejected.get("text"):
                rendered += (
                    "\nA repository-changing follow-up was rejected without altering the active "
                    "request. Use explicit replace/cancel wording before changing repositories."
                )
            return rendered

        continuity_module.render_active_objective = render_active_objective
    continuity_module._manageroo_request_lifecycle_policy_installed = True
