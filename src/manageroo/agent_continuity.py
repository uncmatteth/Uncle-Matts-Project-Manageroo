from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

from .config_lock import config_mutation_lock
from .errors import ConfigurationError
from .util import atomic_write_json, sha256_text, utc_now


STATE_SCHEMA_VERSION = 1
HOOK_COMMAND = "agent-continuity-hook"
INTERNAL_CONTINUATION_PREFIX = "[MANAGEROO INTERNAL CONTINUATION]"
MANAGEROO_MARK = "🦘"
REQUEST_MARK = "🧭"
ROOT_REQUEST_MARK = "🎯"
ADDITION_REQUEST_MARK = "➕"
FINISH_MARK = "🏁"
COMPLETE_MARK = "🎉"
BLOCKED_MARK = "🚧"
STOPPED_MARK = "🛑"
GENERIC_COMPLETE_RECEIPT = f"{COMPLETE_MARK} Manageroo: request complete"
GENERIC_BLOCKED_RECEIPT = f"{BLOCKED_MARK} Manageroo: waiting on an external blocker"
SPECIFIC_COMPLETE_PREFIX = "✅ Done — "
SPECIFIC_COMPLETE_TEMPLATE = f"{SPECIFIC_COMPLETE_PREFIX}<what actually finished>"
_REPLACE_REQUEST = re.compile(
    r"\b(?:cancel|drop|forget|ignore|replace|supersede)\s+(?:all\s+)?(?:the\s+)?"
    r"(?:earlier|old|prior|previous|unfinished)\s+(?:request|task|work|instructions?)\b|"
    r"\bstop\s+(?:the\s+)?(?:current|earlier|old|previous)\s+(?:request|task|work)\b|"
    r"\bstop\s+what\s+you(?:'re|\s+are)?\s+doing\b|"
    r"\b(?:do|work\s+on)\s+only\s+this\s+(?:now|instead)\b|"
    r"\bnew\s+task\s+instead\b|"
    r"^\s*(?:stop|cancel)(?:[.!]+)?\s*$",
    re.IGNORECASE,
)
_PAUSE_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:stop|pause|wait|hold)(?:\b|[.!])|"
    r"\b(?:i\s+(?:said|told\s+you)|did(?:n't|\s+not)\s+i\s+tell\s+you)\s+to\s+"
    r"(?:stop|pause|wait)\b|"
    r"\b(?:do\s+not|don't)\s+(?:continue|resume|work|run|do\s+anything)\b|"
    r"\bstop\s+and\s+(?:just\s+)?wait\b|"
    r"\bwait\s+until\s+i\b|"
    r"\bi(?:'ll|\s+will)\s+tell\s+you\s+when\s+(?:to|you\s+can)\s+"
    r"(?:resume|continue|work)\b",
    re.IGNORECASE,
)
_RESUME_REQUEST = re.compile(
    r"^\s*(?:ok(?:ay)?[,.]?\s+)?(?:please\s+)?(?:"
    r"resume|continue|go\s+ahead|start\s+working\s+again|"
    r"you\s+can\s+(?:resume|continue|work))\b",
    re.IGNORECASE,
)
_REAFFIRM_ACTIVE_WORK = re.compile(
    r"\bi\s+(?:(?:already|just)\s+|have\s+)?(?:told|asked)\s+(?:you|it)\s+to\s+"
    r"(?!(?:stop|pause|wait|hold)\b)|"
    r"\bi\s+(?:(?:already|just)\s+|have\s+)?told\s+you\s+what\s+to\s+do\b|"
    r"\b(?:do|finish|continue|resume)\s+what\s+i\s+(?:said|asked|told\s+you)\b|"
    r"\bi\s+(?:have\s+)?told\s+it\s+to\s+do\s+what\s+i\s+said\b",
    re.IGNORECASE,
)
_CLEAR_WORK_REQUEST = re.compile(
    r"^\s*(?:ok(?:ay)?[,.]?\s+)?(?:please\s+)?"
    r"(?:(?:you\s+)?(?:need\s+to|must|should)\s+)?"
    r"(?:fix|implement|change|edit|write|create|copy|move|rename|delete|remove|"
    r"inspect|review|diagnose|investigate|figure\s+out|run|build|install|publish|"
    r"commit|push|make|do)\b",
    re.IGNORECASE,
)
_CLEAR_WORK_AFTER_PREAMBLE = re.compile(
    r"(?:\bnow\b|[.!?;:,])\s*(?:please\s+)?"
    r"(?:fix|implement|change|edit|write|create|copy|move|rename|delete|remove|"
    r"inspect|review|diagnose|investigate|figure\s+out|run|build|install|publish|"
    r"commit|push|make|do)\b",
    re.IGNORECASE,
)
_DIRECT_WORK_QUESTION = re.compile(
    r"^\s*(?:(?:can|could|will|would)\s+you|do\s+you\s+want\s+to)\s+"
    r"(?:please\s+)?(?:fix|implement|change|edit|write|create|copy|move|rename|"
    r"delete|remove|inspect|review|diagnose|investigate|run|build|install|publish|"
    r"commit|push|make|do)\b",
    re.IGNORECASE,
)
_REPLACE_AND_CONTINUE = re.compile(
    r"\b(?:do|work\s+on)\s+only\s+this\s+(?:now|instead)\b|"
    r"\bnew\s+task\s+instead\b",
    re.IGNORECASE,
)
_NATURAL_CORRECTION = re.compile(
    r"^\s*(?:no(?:pe)?|actually|wrong|correction)\b\s*(?:[,. ;:\u2014-]\s*)?"
    r"(?:please\s+)?(?:i\s+mean\s+)?(?:use|switch\s+to|work\s+(?:in|on|from)|edit|"
    r"(?:the\s+)?(?:repo(?:sitory)?|path|file|source|target|method)\s+(?:is|should\s+be))\b",
    re.IGNORECASE,
)
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9._~+@%:,=/-]+)")
_RELATIVE_PATH = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:(?:[A-Za-z0-9._~+@%=-]+/)+"
    r"[A-Za-z0-9._~+@%:=-]+)|(?:[A-Za-z0-9_~+@%=-][A-Za-z0-9._~+@%:=-]*\."
    r"[A-Za-z0-9._~+@%:=-]+))"
)
_NEGATION_NEAR_PATH = re.compile(
    r"\b(?:do\s+not|don't|never|must\s+not|mustn't|without|leave)\b",
    re.IGNORECASE,
)
_MUTATING_SHELL_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:chmod|chown|cp|install|ln|mkdir|mkfifo|mv|patch|rename|rm|rmdir|"
    r"rsync|sed\s+-i|tee|touch|truncate)(?:\s|$)|"
    r"(?:^|[;&|]\s*)git\s+(?:[^;&|]*\s)?(?:add|am|apply|checkout|cherry-pick|"
    r"clean|commit|merge|mv|pull|push|rebase|reset|restore|rm|switch|tag)(?:\s|$)",
    re.IGNORECASE,
)
_PYTHON_MUTATION = re.compile(
    r"\b(?:python|python3|py)\b[^\n]*(?:"
    r"\.write_(?:text|bytes)\s*\(|\.unlink\s*\(|\.mkdir\s*\(|\.rename\s*\(|"
    r"\.replace\s*\(|\.touch\s*\(|\.chmod\s*\(|"
    r"\b(?:remove|unlink|rmdir|removedirs|mkdir|makedirs|rename|replace)\s*\(|"
    r"\b(?:rmtree|copy|copy2|copyfile|move)\s*\(|"
    r"\bopen\s*\([^)]*,\s*['\"](?:[wax+]))",
    re.IGNORECASE,
)
_SHELL_REDIRECTION = re.compile(
    r"(?<!<)(?:\d*)(?:>>|>)(?![=&])\s*"
    r"(?P<target>\"(?:\\.|[^\"])*\"|'[^']*'|[^\s;&|]+)"
)
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
    re.MULTILINE,
)
_SHELL_TOOLS = {"Bash", "exec_command", "shell", "functions.exec"}
_CLAUSE_BOUNDARIES = ".!?;\n"
_QUOTED_SPAN = re.compile(
    r'"(?:\\.|[^"\\])*"|`[^`\n]*`|“[^”\n]*”|‘[^’\n]*’|'
    r"(?<![A-Za-z0-9])'[^'\n]+'(?![A-Za-z0-9])"
)
_HISTORICAL_CONTEXT = re.compile(
    r"\b(?:last|prior|previous|earlier|old)\s+"
    r"(?:agent|session|chat|turn|request)\b|"
    r"\b(?:agent|handoff|report)\s+"
    r"(?:said|mentioned|claimed|asked|told|tried|used|edited|wrote|ran|touched)\b|"
    r"\b(?:for example|historically|previously)\b",
    re.IGNORECASE,
)
_CURRENT_PATH_DIRECTIVE = re.compile(
    r"^\s*(?:(?:now|instead)[:,]?\s+)?(?:please\s+)?"
    r"(?:use|edit|write|create|copy|move|rename|delete|remove|"
    r"work\s+(?:in|on|from)|read|inspect|review)\b",
    re.IGNORECASE,
)
_EXCLUSIVE_PATH_PREFIX = re.compile(r"\bonly\s*$", re.IGNORECASE)
_EXPLICIT_SCOPE_LIMIT = re.compile(
    r"\b(?:work|edit|change|write|operate)\s+only\s+(?:in|on|inside|within)\b|"
    r"\b(?:this|the|current)\s+(?:repo(?:sitory)?|file|path)\s+only\b|"
    r"\bleave\s+(?:the\s+)?rest\s+alone\b|"
    r"\b(?:do\s+not|don't)\s+(?:change|edit|touch|write\s+to)\s+anything\s+else\b",
    re.IGNORECASE,
)


def continuity_state_root() -> Path:
    explicit = os.environ.get("MANAGEROO_CONTINUITY_STATE")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "manageroo" / "agent-continuity"


def _safe_state_root(root: Path) -> Path:
    lexical = root.expanduser().absolute()
    lexical.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = lexical.lstat()
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ConfigurationError(f"Manageroo continuity state is not a directory: {lexical}")
    if os.name != "nt":
        if hasattr(os, "getuid") and state.st_uid != os.getuid():
            raise ConfigurationError(f"Manageroo continuity state has the wrong owner: {lexical}")
        os.chmod(lexical, 0o700)
    return lexical.resolve(strict=True)


def _state_path(root: Path, session_id: str) -> Path:
    identity = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return root / f"{identity}.json"


def _read_state(root: Path, session_id: str) -> dict[str, Any] | None:
    path = _state_path(root, session_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
        return None
    return value


def _objective_hash(messages: list[dict[str, str]]) -> str:
    return sha256_text("\n\n".join(item["text"] for item in messages))


def _save_state(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root, str(state["session_id"]))
    with config_mutation_lock(path):
        atomic_write_json(path, state)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _message(prompt: str, turn_id: str, relation: str) -> dict[str, str]:
    return {
        "turn_id": turn_id,
        "text": prompt.strip(),
        "relation": relation,
        "sha256": sha256_text(prompt.strip()),
    }


def _is_side_question(prompt: str) -> bool:
    text = prompt.strip()
    if not text.endswith("?"):
        return False
    return not (
        _CLEAR_WORK_REQUEST.search(text) or _DIRECT_WORK_QUESTION.search(text)
    )


def capture_current_request(
    *,
    session_id: str,
    turn_id: str,
    prompt: str,
    cwd: str,
    state_root: Path | None = None,
) -> dict[str, Any]:
    root = _safe_state_root(state_root or continuity_state_root())
    prompt = prompt.strip()
    existing = _read_state(root, session_id)
    internal = prompt.startswith(INTERNAL_CONTINUATION_PREFIX)
    if internal and existing is not None:
        return existing

    if _PAUSE_REQUEST.search(prompt) and not _REPLACE_AND_CONTINUE.search(prompt):
        messages = (
            [
                item
                for item in existing.get("messages", [])
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if existing is not None
            else []
        )
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "session_id": session_id,
            "status": "paused",
            "cwd": cwd,
            "messages": messages,
            "objective_sha256": _objective_hash(messages),
            "generation": int(existing.get("generation", 1)) if existing else 1,
            "created_at": str(existing.get("created_at") or utc_now()) if existing else utc_now(),
            "updated_at": utc_now(),
            "waiting_reason": prompt,
        }
        _save_state(root, state)
        return state

    if existing is not None and existing.get("status") == "paused":
        if _RESUME_REQUEST.search(prompt) or _REAFFIRM_ACTIVE_WORK.search(prompt):
            state = dict(existing)
            state.update(
                {
                    "status": "active",
                    "cwd": cwd,
                    "updated_at": utc_now(),
                    "waiting_reason": "",
                }
            )
            _save_state(root, state)
            return state
        clear_new_work = bool(
            _CLEAR_WORK_REQUEST.search(prompt) or _CLEAR_WORK_AFTER_PREAMBLE.search(prompt)
        )
        if clear_new_work and not prompt.rstrip().endswith("?"):
            messages = [_message(prompt, turn_id, "replacement")]
            state = {
                "schema_version": STATE_SCHEMA_VERSION,
                "session_id": session_id,
                "status": "active",
                "cwd": cwd,
                "messages": messages,
                "objective_sha256": _objective_hash(messages),
                "generation": int(existing.get("generation", 1)) + 1,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "waiting_reason": "",
            }
            _save_state(root, state)
            return state
        state = dict(existing)
        state.update({"cwd": cwd, "updated_at": utc_now()})
        _save_state(root, state)
        return state

    natural_correction = bool(
        not prompt.rstrip().endswith("?") and _NATURAL_CORRECTION.search(prompt)
    )
    replace = bool(_REPLACE_REQUEST.search(prompt)) or natural_correction
    if existing is not None and not replace and _is_side_question(prompt):
        state = dict(existing)
        state.update({"cwd": cwd, "updated_at": utc_now()})
        _save_state(root, state)
        return state
    if existing is None or existing.get("status") == "complete" or replace:
        messages = [_message(prompt, turn_id, "root" if not replace else "replacement")]
        created_at = utc_now()
        generation = int(existing.get("generation", 0)) + 1 if existing else 1
    else:
        messages = [
            item
            for item in existing.get("messages", [])
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if not any(item.get("turn_id") == turn_id for item in messages):
            messages.append(_message(prompt, turn_id, "addition"))
        created_at = str(existing.get("created_at") or utc_now())
        generation = int(existing.get("generation", 1))
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "session_id": session_id,
        "status": "active",
        "cwd": cwd,
        "messages": messages,
        "objective_sha256": _objective_hash(messages),
        "generation": generation,
        "created_at": created_at,
        "updated_at": utc_now(),
        "waiting_reason": "",
    }
    _save_state(root, state)
    return state


def _completion_marker(state: dict[str, Any], status: str) -> str:
    label = (
        f"{COMPLETE_MARK} Manageroo: request complete"
        if status == "complete"
        else f"{BLOCKED_MARK} Manageroo: waiting on an external blocker"
    )
    return (
        f"[{label}](#manageroo-continuity-"
        f"{state['objective_sha256']}-{status})"
    )


def _previous_completion_marker(state: dict[str, Any], status: str) -> str:
    """Accept the earlier readable badge while an installed hook is upgraded."""
    label = (
        "Manageroo: request complete"
        if status == "complete"
        else "Manageroo: waiting on an external blocker"
    )
    return (
        f"[{label}](#manageroo-continuity-"
        f"{state['objective_sha256']}-{status})"
    )


def _legacy_completion_marker(state: dict[str, Any], status: str) -> str:
    """Accept already-issued receipts while an installed hook is upgraded."""
    return f"<!-- manageroo-continuity:{state['objective_sha256']}:{status} -->"


def _has_specific_completion_result(message: str) -> bool:
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped.startswith(SPECIFIC_COMPLETE_PREFIX):
            continue
        result = stripped[len(SPECIFIC_COMPLETE_PREFIX) :].strip()
        if result and result.casefold() not in {
            "<what actually finished>",
            "request complete",
            "done",
        }:
            return True
    return False


def render_active_objective(state: dict[str, Any]) -> str:
    if state.get("status") == "paused":
        lines = [
            f"# ⏸️ Manageroo: work paused by the operator",
            "",
            "Do not resume, monitor, or continue the saved work until the operator explicitly says to resume or gives a clear new work command.",
            "Questions and conversation do not resume the work. The agent may end the turn normally; no completion badge is required while paused.",
            "",
            f"## {REQUEST_MARK} Saved work — not active",
            "",
        ]
        for index, item in enumerate(state.get("messages", []), start=1):
            lines.extend([f"### {index}. Saved request", "", str(item.get("text") or ""), ""])
        return "\n".join(lines)
    lines = [
        f"# {MANAGEROO_MARK} Manageroo: current request",
        "",
        "Manageroo keeps the agent on the operator's unfinished request. It never limits what the operator may ask for.",
        "Finish every request below. New messages add to unfinished work unless they clearly cancel or replace it.",
        "Answer corrections or side questions, then resume the unfinished work in the same turn.",
        "Do not make the operator repeat a path, permission, or request already listed here.",
        "Questions, quotations, and historical examples are context, not new tasks or permission.",
        "Stay in scope and preserve every named source and requested method.",
        "",
        f"## {REQUEST_MARK} Work still in force",
        "",
    ]
    for index, item in enumerate(state.get("messages", []), start=1):
        relation = str(item.get("relation", "addition"))
        request_mark = ROOT_REQUEST_MARK if relation == "root" else ADDITION_REQUEST_MARK
        lines.extend(
            [
                f"### {request_mark} {index}. {relation.capitalize()} request",
                "",
                str(item.get("text") or ""),
                "",
            ]
        )
    lines.extend(
        [
            f"## {FINISH_MARK} Finish status",
            "",
            "Keep working while anything above remains unfinished.",
            "After current proof shows everything is complete, end the final reply with one specific result line:",
            SPECIFIC_COMPLETE_TEMPLATE,
            "If a concrete external blocker makes progress impossible, explain it under `Concrete blocker:` and end with:",
            _completion_marker(state, "blocked"),
            "The badge text is for the operator. Its link target is continuity bookkeeping and should not be explained or expanded.",
        ]
    )
    return "\n".join(lines)


def _task_excerpt(value: Any, *, limit: int = 240) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip().lstrip(" .:-")
    if len(text) <= limit:
        return text
    clipped = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{clipped}…"


def _active_task_reminder(state: dict[str, Any]) -> str:
    messages = [item for item in state.get("messages", []) if isinstance(item, dict)]
    if not messages:
        return f"{REQUEST_MARK} Continue the named Manageroo work shown in the current request."
    root = _task_excerpt(messages[0].get("text"))
    lines = [f"{REQUEST_MARK} Current Manageroo task: {root}"]
    if len(messages) > 1:
        latest = _task_excerpt(messages[-1].get("text"), limit=180)
        if latest and latest != root:
            lines.append(f"{ADDITION_REQUEST_MARK} Latest requested addition: {latest}")
    return "\n".join(lines)


_ACTIVITY_VERBS = {
    "add": "Adding",
    "audit": "Auditing",
    "change": "Changing",
    "clean": "Cleaning",
    "copy": "Copying",
    "diagnose": "Diagnosing",
    "explain": "Explaining",
    "fix": "Fixing",
    "implement": "Implementing",
    "install": "Installing",
    "investigate": "Investigating",
    "make": "Making",
    "move": "Moving",
    "publish": "Publishing",
    "remove": "Removing",
    "repair": "Repairing",
    "review": "Reviewing",
    "run": "Running",
    "update": "Updating",
    "verify": "Verifying",
}


def _current_activity(state: dict[str, Any]) -> str:
    """Describe current work from saved state without a model call or prompt replay."""
    messages = [item for item in state.get("messages", []) if isinstance(item, dict)]
    if not messages:
        return "Starting the current task summarized above."
    request = _task_excerpt(messages[-1].get("text"), limit=180)
    lowered = request.casefold()
    if (
        "manageroo is doing" in lowered
        and "generic line" in lowered
        and ("extra tokens" in lowered or "model-context" in lowered)
    ):
        return (
            "Making the activity line describe the actual current task without spending "
            "model-context tokens."
        )
    directive = re.search(
        r"(?:^|[.!?;:]\s+)(?:please\s+)?("
        + "|".join(_ACTIVITY_VERBS)
        + r")\b(?P<rest>[^.!?]*)",
        request,
        flags=re.IGNORECASE,
    )
    if directive is None:
        return "Starting the current task summarized above."
    verb = _ACTIVITY_VERBS[directive.group(1).casefold()]
    rest = directive.group("rest").strip().rstrip(" ,;:-")
    rest = re.sub(
        r"\band\s+(" + "|".join(_ACTIVITY_VERBS) + r")\b",
        lambda match: f"and {_ACTIVITY_VERBS[match.group(1).casefold()].casefold()}",
        rest,
        flags=re.IGNORECASE,
    )
    summary = f"{verb}{(' ' + rest) if rest else ''}."
    return _task_excerpt(summary, limit=180)


def render_compact_status(state: dict[str, Any], *, activity: str) -> str:
    """Render a bounded status projection without replaying stored operator text."""
    messages = [item for item in state.get("messages", []) if isinstance(item, dict)]
    count = len(messages)
    noun = "work item" if count == 1 else "work items"
    if state.get("status") == "paused":
        goal = _task_excerpt(messages[-1].get("text"), limit=160) if messages else "Saved work"
        return "\n".join(
            [
                f"{MANAGEROO_MARK} Manageroo update",
                f"{ROOT_REQUEST_MARK} You asked: {goal}",
                "⏸️ Manageroo is doing: Waiting. It will not resume, monitor, or use tools until you explicitly resume or give a clear new task.",
                f"📍 Status: Paused — {count} saved {noun}; questions and conversation do not resume it.",
            ]
        )
    goal = (
        _task_excerpt(messages[-1].get("text"), limit=160)
        if messages
        else "Continue the named request"
    )
    return "\n".join(
        [
            f"{MANAGEROO_MARK} Manageroo update",
            f"{ROOT_REQUEST_MARK} You asked: {goal}",
            f"🛠️ Manageroo is doing: {activity}",
            f"📍 Status: Active — {count} active {noun}; exact wording remains in private continuity state.",
        ]
    )


def _completion_contract() -> str:
    return "\n".join(
        [
            "When verified, end with one specific result line:",
            SPECIFIC_COMPLETE_TEMPLATE,
            "For a concrete external blocker, write `Concrete blocker:` and append:",
            GENERIC_BLOCKED_RECEIPT,
        ]
    )


def _stop_recovery_message(state: dict[str, Any]) -> str:
    messages = [item for item in state.get("messages", []) if isinstance(item, dict)]
    goal = (
        _task_excerpt(messages[-1].get("text"), limit=180)
        if messages
        else "the saved request"
    )
    return "\n".join(
        [
            INTERNAL_CONTINUATION_PREFIX,
            f"{MANAGEROO_MARK} Missing the completion line, so Manageroo continued this turn.",
            f"{ROOT_REQUEST_MARK} Finish: {goal}",
            f"{FINISH_MARK} When done, end with: {SPECIFIC_COMPLETE_TEMPLATE}",
        ]
    )


def _path_clause(text: str, start: int, end: int) -> tuple[str, str]:
    clause_start = max(text.rfind(mark, 0, start) for mark in _CLAUSE_BOUNDARIES) + 1
    following = [
        position
        for mark in _CLAUSE_BOUNDARIES
        if (position := text.find(mark, end)) >= 0
    ]
    clause_end = min(following) + 1 if following else len(text)
    clause = text[clause_start:clause_end]
    return text[clause_start:start], clause


def _path_is_quoted(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith(">"):
        return True
    return any(
        span.start() <= start and end <= span.end()
        for span in _QUOTED_SPAN.finditer(text)
    )


def _named_paths(state: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    cwd = Path(str(state.get("cwd") or ".")).expanduser().resolve(strict=False)
    base = _git_root(cwd) or cwd
    allowed: list[Path] = []
    excluded: list[Path] = []
    for item in state.get("messages", []):
        text = str(item.get("text") or "")
        matches = [*list(_ABSOLUTE_PATH.finditer(text)), *list(_RELATIVE_PATH.finditer(text))]
        for match in matches:
            if _path_is_quoted(text, match.start(), match.end()):
                continue
            prefix, clause = _path_clause(text, match.start(), match.end())
            if clause.rstrip().endswith("?"):
                continue
            if (
                _HISTORICAL_CONTEXT.search(clause)
                and not _CURRENT_PATH_DIRECTIVE.search(clause)
            ):
                continue
            raw = match.group(1).rstrip(".,;:!?)]}>\"'")
            if not raw:
                continue
            value = Path(raw).expanduser()
            if not value.is_absolute():
                value = base / value
            value = value.resolve(strict=False)
            target = excluded if _NEGATION_NEAR_PATH.search(prefix) else allowed
            if value not in target:
                target.append(value)
    return allowed, excluded


def _exclusive_paths(state: dict[str, Any]) -> list[Path]:
    cwd = Path(str(state.get("cwd") or ".")).expanduser().resolve(strict=False)
    base = _git_root(cwd) or cwd
    exclusive: list[Path] = []
    for item in state.get("messages", []):
        text = str(item.get("text") or "")
        matches = [*list(_ABSOLUTE_PATH.finditer(text)), *list(_RELATIVE_PATH.finditer(text))]
        for match in matches:
            if _path_is_quoted(text, match.start(), match.end()):
                continue
            prefix, clause = _path_clause(text, match.start(), match.end())
            if clause.rstrip().endswith("?") or not _EXCLUSIVE_PATH_PREFIX.search(prefix):
                continue
            raw = match.group(1).rstrip(".,;:!?)]}>\"'")
            if not raw:
                continue
            value = Path(raw).expanduser()
            if not value.is_absolute():
                value = base / value
            value = value.resolve(strict=False)
            if value not in exclusive:
                exclusive.append(value)
    return exclusive


def _has_explicit_scope_limit(state: dict[str, Any]) -> bool:
    return any(
        _EXPLICIT_SCOPE_LIMIT.search(str(item.get("text") or ""))
        for item in state.get("messages", [])
        if isinstance(item, dict)
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _git_root(cwd: Path) -> Path | None:
    current = cwd.resolve(strict=False)
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _literal_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _qualified_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _path_constructor_value(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    name = _qualified_call_name(node.func)
    return _literal_string(node.args[0]) if name in {"Path", "pathlib.Path"} else None


def _python_mutation_values(tokens: list[str]) -> list[str]:
    if "-c" not in tokens:
        return []
    index = tokens.index("-c")
    if index + 1 >= len(tokens):
        return []
    try:
        tree = ast.parse(tokens[index + 1])
    except SyntaxError:
        return []
    values: list[str] = []
    path_methods = {"write_text", "write_bytes", "unlink", "mkdir", "rename", "replace", "touch", "chmod"}
    one_path_calls = {"os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.mkdir", "os.makedirs", "shutil.rmtree"}
    copy_calls = {"shutil.copy", "shutil.copy2", "shutil.copyfile"}
    two_path_calls = {"os.rename", "os.replace", "shutil.move"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_call_name(node.func)
        if isinstance(node.func, ast.Attribute) and node.func.attr in path_methods:
            receiver = _path_constructor_value(node.func.value)
            if receiver:
                values.append(receiver)
            if node.func.attr in {"rename", "replace"} and node.args:
                if destination := _literal_string(node.args[0]):
                    values.append(destination)
        elif name in one_path_calls and node.args:
            if value := _literal_string(node.args[0]):
                values.append(value)
        elif name in copy_calls and len(node.args) >= 2:
            if destination := _literal_string(node.args[1]):
                values.append(destination)
        elif name in two_path_calls:
            values.extend(value for arg in node.args[:2] if (value := _literal_string(arg)))
        elif name == "open" and node.args:
            mode = _literal_string(node.args[1]) if len(node.args) > 1 else "r"
            if mode and any(flag in mode for flag in "wax+"):
                if value := _literal_string(node.args[0]):
                    values.append(value)
    return values


def _shell_mutation_values(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = []
    if not tokens:
        return []
    executable = Path(tokens[0]).name.casefold()
    if executable in {"python", "python3", "py"} and _PYTHON_MUTATION.search(command):
        return _python_mutation_values(tokens)
    if executable == "cp" and not re.search(r"[;&|]", command):
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-t", "--target-directory"} and index + 1 < len(tokens):
                return [tokens[index + 1]]
            if token.startswith("--target-directory="):
                return [token.split("=", 1)[1]]
        operands = [token for token in tokens[1:] if not token.startswith("-")]
        return operands[-1:] if len(operands) >= 2 else []
    if executable == "git":
        return [token for token in tokens[2:] if not token.startswith("-")]
    if _MUTATING_SHELL_COMMAND.search(command):
        return [token for token in tokens[1:] if not token.startswith("-")]
    return []


def _tool_mutation_paths(event: dict[str, Any]) -> list[Path]:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    payload = tool_input if isinstance(tool_input, dict) else {}
    cwd = Path(str(event.get("cwd") or ".")).expanduser().resolve(strict=False)
    if tool_name == "apply_patch":
        command = str(payload.get("command") or payload.get("patch") or "")
        values = _PATCH_PATH.findall(command)
    elif tool_name in _SHELL_TOOLS:
        command = str(payload.get("command") or payload.get("cmd") or "")
        command_mutates = bool(
            _MUTATING_SHELL_COMMAND.search(command) or _PYTHON_MUTATION.search(command)
        )
        redirect_values: list[str] = []
        for match in _SHELL_REDIRECTION.finditer(command):
            raw = match.group("target")
            try:
                parsed = shlex.split(raw, posix=os.name != "nt")
            except ValueError:
                parsed = []
            if parsed:
                redirect_values.append(parsed[0])
        if not command_mutates and not redirect_values:
            return []
        values = _shell_mutation_values(command) if command_mutates else []
        if command_mutates and not values:
            values = _ABSOLUTE_PATH.findall(command)
        values.extend(redirect_values)
    else:
        return []
    paths: list[Path] = []
    for value in values:
        candidate = Path(str(value).strip()).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        resolved = candidate.resolve(strict=False)
        if resolved not in paths:
            paths.append(resolved)
    return paths


def audit_agent_tool(event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    targets = _tool_mutation_paths(event)
    if not targets:
        return {}
    allowed, excluded = _named_paths(state)
    exclusive = _exclusive_paths(state)
    scope_limited = bool(exclusive) or _has_explicit_scope_limit(state)
    objective_cwd = Path(str(state.get("cwd") or ".")).expanduser().resolve(strict=False)
    repo = _git_root(objective_cwd)
    temporary_roots = [Path("/tmp"), Path("/dev/shm")]
    null_target = Path(os.devnull).expanduser().resolve(strict=False)
    for target in targets:
        if any(_inside(target, path) or target == path for path in excluded):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"{STOPPED_MARK}{MANAGEROO_MARK} Manageroo stopped this agent action.\n"
                        f"🎯 Target: {target}\n"
                        "💡 Why: The operator explicitly excluded this target.\n"
                        "➡️ Next: Continue the requested work without changing this target. "
                        "Do not ask the operator to authorize it again."
                    ),
                }
            }
        if target == null_target:
            continue
        target_repo = _git_root(target if target.is_dir() else target.parent)
        if (
            any(_inside(target, root) or target == root for root in temporary_roots)
            and not (repo is not None and (_inside(target, repo) or target == repo))
            and target_repo is None
        ):
            continue
        if exclusive and not any(
            _inside(target, path) or target == path for path in exclusive
        ):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"{STOPPED_MARK}{MANAGEROO_MARK} Manageroo stopped this agent action.\n"
                        f"🎯 Target: {target}\n"
                        "💡 Why: The operator limited changes to: "
                        f"{', '.join(str(path) for path in exclusive)}.\n"
                        "➡️ Next: Continue using only those named paths."
                    ),
                }
            }
        if repo is not None and (_inside(target, repo) or target == repo):
            continue
        if any(_inside(target, path) or target == path for path in allowed):
            continue
        if scope_limited:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"{STOPPED_MARK}{MANAGEROO_MARK} Manageroo stopped this agent action.\n"
                        f"🎯 Target: {target}\n"
                        "💡 Why: The operator explicitly limited where changes may be made.\n"
                        "➡️ Next: Continue within that explicit limit."
                    ),
                }
            }
    return {}


def _additional_context(event_name: str, text: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }


def process_codex_continuity_hook(
    event: dict[str, Any], *, state_root: Path | None = None
) -> dict[str, Any]:
    session_id = str(event.get("session_id") or "")
    if not session_id:
        return {}
    root = _safe_state_root(state_root or continuity_state_root())
    name = str(event.get("hook_event_name") or "")
    if name == "UserPromptSubmit":
        previous = _read_state(root, session_id)
        state = capture_current_request(
            session_id=session_id,
            turn_id=str(event.get("turn_id") or ""),
            prompt=str(event.get("prompt") or ""),
            cwd=str(event.get("cwd") or ""),
            state_root=root,
        )
        result: dict[str, Any] = {
            "systemMessage": render_compact_status(
                state,
                activity=_current_activity(state),
            )
        }
        advertised = bool(
            (previous or {}).get("receipt_contract_advertised")
            or (previous or {}).get("receipt_objective_sha256")
        )
        if not advertised and state.get("status") != "paused":
            state["receipt_contract_advertised"] = True
            _save_state(root, state)
            result.update(_additional_context(name, _completion_contract()))
        elif advertised:
            state["receipt_contract_advertised"] = True
            _save_state(root, state)
        return result
    state = _read_state(root, session_id)
    if not isinstance(state, dict) or state.get("status") not in {"active", "waiting", "paused"}:
        return {}
    if name in {"SessionStart", "SubagentStart", "PostCompact"}:
        return _additional_context(name, render_active_objective(state))
    if name == "PreToolUse":
        if state.get("status") == "paused":
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"⏸️{MANAGEROO_MARK} Manageroo paused this agent action.\n"
                        "💡 Why: The operator said to stop and has not explicitly resumed work.\n"
                        "➡️ Next: End the turn or answer without tools. Do not monitor or resume the saved task."
                    ),
                }
            }
        return audit_agent_tool(event, state)
    if name == "Stop":
        if state.get("status") == "paused":
            return {}
        last = str(event.get("last_assistant_message") or "")
        complete_marker = _completion_marker(state, "complete")
        blocked_marker = _completion_marker(state, "blocked")
        previous_complete_marker = _previous_completion_marker(state, "complete")
        previous_blocked_marker = _previous_completion_marker(state, "blocked")
        legacy_complete_marker = _legacy_completion_marker(state, "complete")
        legacy_blocked_marker = _legacy_completion_marker(state, "blocked")
        if (
            _has_specific_completion_result(last)
            or GENERIC_COMPLETE_RECEIPT in last
            or complete_marker in last
            or previous_complete_marker in last
            or legacy_complete_marker in last
        ):
            state["status"] = "complete"
            state["updated_at"] = utc_now()
            _save_state(root, state)
            return {}
        if (
            GENERIC_BLOCKED_RECEIPT in last
            or blocked_marker in last
            or previous_blocked_marker in last
            or legacy_blocked_marker in last
        ) and "Concrete blocker:" in last:
            state["status"] = "waiting"
            state["waiting_reason"] = last
            state["updated_at"] = utc_now()
            _save_state(root, state)
            return {}
        return {
            "decision": "block",
            "reason": _stop_recovery_message(state),
        }
    return {}


def run_codex_continuity_hook(
    *, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout
) -> int:
    try:
        event = json.load(input_stream)
        if not isinstance(event, dict):
            raise ValueError("Codex hook input must be a JSON object")
        result = process_codex_continuity_hook(event)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ConfigurationError) as exc:
        # Hook bookkeeping must never deny the operator or strand the agent.
        result = {
            "systemMessage": (
                f"{MANAGEROO_MARK}⚠️ Manageroo could not load continuity state. Continue the current operator request normally. "
                f"Details: {exc}"
            )
        }
    if result:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=output_stream)
    return 0


def _manageroo_hook_group(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    return isinstance(handlers, list) and any(
        isinstance(handler, dict)
        and any(
            token in str(handler.get("command") or "")
            for token in ("operator-" "scope-hook", HOOK_COMMAND)
        )
        for handler in handlers
    )


def install_codex_continuity_hooks(
    *, codex_home: Path, manageroo_command: Path
) -> dict[str, Any]:
    home = codex_home.expanduser().resolve(strict=False)
    home.mkdir(parents=True, exist_ok=True)
    hooks_path = home / "hooks.json"
    command = shlex.join([str(manageroo_command.expanduser().resolve(strict=False)), HOOK_COMMAND])
    command_windows = subprocess.list2cmdline(
        [str(manageroo_command.expanduser().resolve(strict=False)), HOOK_COMMAND]
    )
    handler = {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": 10,
        "statusMessage": f"{MANAGEROO_MARK} Keeping the agent on the active request",
    }
    context_handler = {**handler, "additionalContextLimit": 10000}
    additions = {
        "SessionStart": {"matcher": "startup|resume|clear|compact", "hooks": [context_handler]},
        "UserPromptSubmit": {"hooks": [context_handler]},
        "PreToolUse": {"matcher": "*", "hooks": [context_handler]},
        "Stop": {"hooks": [handler]},
        "SubagentStart": {"hooks": [context_handler]},
    }
    with config_mutation_lock(hooks_path):
        if hooks_path.exists():
            try:
                payload = json.loads(hooks_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConfigurationError(f"Cannot safely update Codex hooks: {exc}") from exc
        else:
            payload = {}
        if not isinstance(payload, dict):
            raise ConfigurationError("Codex hooks file must contain a JSON object")
        hooks = payload.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ConfigurationError("Codex hooks field must contain an object")
        before = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                raise ConfigurationError(f"Codex hook event {event} must contain an array")
            kept = [group for group in groups if not _manageroo_hook_group(group)]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        for event, addition in additions.items():
            hooks.setdefault(event, []).append(addition)
        after = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        changed = before != after
        if changed:
            atomic_write_json(hooks_path, payload)
    return {
        "ok": True,
        "path": str(hooks_path),
        "changed": changed,
        "trust_required": changed,
        "next": "/hooks" if changed else "",
    }
