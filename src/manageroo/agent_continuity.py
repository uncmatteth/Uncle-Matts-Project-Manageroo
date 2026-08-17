from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

from .config_lock import config_mutation_lock
from .errors import ConfigurationError
from .util import (
    atomic_write_json,
    atomic_write_text,
    canonical_json_bytes,
    sha256_file,
    sha256_text,
    utc_now,
)


STATE_SCHEMA_VERSION = 2
HOOK_COMMAND = "agent-continuity-hook"
INTERNAL_CONTINUATION_PREFIX = "[MANAGEROO INTERNAL CONTINUATION]"
MANAGEROO_MARK = "🦘"
STOPPED_MARK = "🛑"
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
    r"\b(?:the\s+)?whole\s+point\s+of\b[^.!?\n]{0,160}\bwas\s+to\b|"
    r"\bi\s+(?:have\s+)?told\s+it\s+to\s+do\s+what\s+i\s+said\b",
    re.IGNORECASE,
)
_CLEAR_WORK_REQUEST = re.compile(
    r"^\s*(?:ok(?:ay)?[,.]?\s+)?(?:please\s+)?"
    r"(?:(?:you\s+)?(?:need\s+to|must|should)\s+)?"
    r"(?:fix|finish|restore|rescue|audit|verify|test|update|refactor|implement|"
    r"change|edit|write|create|copy|move|rename|delete|remove|inspect|review|"
    r"diagnose|investigate|figure\s+out|run|build|install|publish|ship|deploy|"
    r"commit|push|make|do)\b",
    re.IGNORECASE,
)
_CLEAR_WORK_AFTER_PREAMBLE = re.compile(
    r"(?:(?:\bnow\b|[.!?;:,])\s*(?:please\s+)?|\bplease\s+)"
    r"(?:go\s+)?"
    r"(?:fix|finish|restore|rescue|audit|verify|test|update|refactor|implement|"
    r"change|edit|write|create|copy|move|rename|delete|remove|inspect|review|"
    r"diagnose|investigate|figure\s+out|run|build|install|publish|ship|deploy|"
    r"commit|push|make|do)\b",
    re.IGNORECASE,
)
_DIRECT_WORK_QUESTION = re.compile(
    r"^\s*(?:(?:can|could|will|would)\s+you|do\s+you\s+want\s+to)\s+"
    r"(?:please\s+)?(?:fix|finish|restore|rescue|audit|verify|test|update|refactor|"
    r"implement|change|edit|write|create|copy|move|rename|delete|remove|inspect|"
    r"review|diagnose|investigate|run|build|install|publish|ship|deploy|commit|"
    r"push|make|do)\b",
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


def _authority_key_path(root: Path) -> Path:
    return root / "authority.key"


def _read_private_file(
    path: Path, *, expected_size: int | None = None, max_bytes: int = 1024 * 1024
) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        file_state = os.fstat(descriptor)
        if not stat.S_ISREG(file_state.st_mode) or file_state.st_nlink != 1:
            raise ConfigurationError(
                f"Manageroo continuity authority is not a private regular file: {path}"
            )
        if os.name != "nt":
            if hasattr(os, "getuid") and file_state.st_uid != os.getuid():
                raise ConfigurationError(
                    f"Manageroo continuity authority has the wrong owner: {path}"
                )
            if stat.S_IMODE(file_state.st_mode) & 0o077:
                raise ConfigurationError(
                    f"Manageroo continuity authority is accessible by another account: {path}"
                )
        value = os.read(descriptor, max_bytes + 1)
    finally:
        os.close(descriptor)
    if expected_size is not None and len(value) != expected_size:
        raise ConfigurationError(
            f"Manageroo continuity authority has an invalid size: {path}"
        )
    if len(value) > max_bytes:
        raise ConfigurationError(
            f"Manageroo continuity private file is too large: {path}"
        )
    return value


def _authority_key(root: Path, *, create: bool) -> bytes:
    path = _authority_key_path(root)
    if create and not path.exists():
        value = secrets.token_bytes(32)
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            pass
        else:
            try:
                os.write(descriptor, value)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    try:
        return _read_private_file(path, expected_size=32, max_bytes=32)
    except FileNotFoundError as exc:
        raise ConfigurationError(
            "Manageroo continuity authority key is missing."
        ) from exc


def _sign_state(state: dict[str, Any], key: bytes) -> str:
    unsigned = {name: value for name, value in state.items() if name != "signature"}
    return hmac.new(key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()


def _read_state(
    root: Path, session_id: str, *, allow_legacy_unsigned: bool = False
) -> dict[str, Any] | None:
    path = _state_path(root, session_id)
    try:
        raw = _read_private_file(path).decode("utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise ConfigurationError(
            f"Manageroo continuity state is not valid UTF-8: {path}"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(
            f"Manageroo continuity state could not be read: {path}"
        ) from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Manageroo continuity state contains invalid JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise ConfigurationError(
            f"Manageroo continuity state must contain a JSON object: {path}"
        )
    if value.get("schema_version") == 1 and allow_legacy_unsigned:
        value["schema_version"] = STATE_SCHEMA_VERSION
        value.pop("signature", None)
        value["legacy_unsigned_migration"] = True
        return value
    if value.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ConfigurationError(
            "Manageroo continuity state has an unsupported schema version: "
            f"{path}"
        )
    signature = value.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature, _sign_state(value, _authority_key(root, create=False))
    ):
        raise ConfigurationError(
            f"Manageroo continuity state signature is invalid: {path}"
        )
    return value


def _objective_hash(messages: list[dict[str, str]]) -> str:
    return sha256_text("\n\n".join(item["text"] for item in messages))


def _save_state_locked(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root, str(state["session_id"]))
    signed = dict(state)
    signed["signature"] = _sign_state(signed, _authority_key(root, create=True))
    atomic_write_json(path, signed)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _save_state(root: Path, state: dict[str, Any]) -> None:
    path = _state_path(root, str(state["session_id"]))
    with config_mutation_lock(path):
        _save_state_locked(root, state)


def _managed_request_path(root: Path, session_id: str, generation: int) -> Path:
    identity = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return root / "requests" / f"{identity}-g{generation}.md"


def _requires_managed_run(prompt: str) -> bool:
    text = prompt.strip()
    if not text or _PAUSE_REQUEST.search(text):
        return False
    actionable = bool(
        _CLEAR_WORK_REQUEST.search(text)
        or _CLEAR_WORK_AFTER_PREAMBLE.search(text)
        or _DIRECT_WORK_QUESTION.search(text)
    )
    if text.endswith("?") and not actionable:
        return False
    return actionable


def _persist_managed_request(root: Path, state: dict[str, Any]) -> None:
    messages = [
        str(item.get("text") or "").strip()
        for item in state.get("messages", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    path = _managed_request_path(
        root, str(state["session_id"]), int(state.get("generation", 1))
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    text = "# Locked operator request\n\n" + "\n\n".join(
        f"## Request {index}\n\n{message}" for index, message in enumerate(messages, 1)
    )
    atomic_write_text(path, text.rstrip() + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)
    state["managed_request_path"] = str(path)
    state["managed_request_sha256"] = sha256_file(path)
    state["managed_request_content_sha256"] = sha256_text(
        path.read_text(encoding="utf-8").strip()
    )


def _finalize_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("status") == "active" and state.get("managed_run_required"):
        _persist_managed_request(root, state)
    _save_state_locked(root, state)
    return state


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
    with config_mutation_lock(_state_path(root, session_id)):
        return _capture_current_request_locked(
            session_id=session_id,
            turn_id=turn_id,
            prompt=prompt,
            cwd=cwd,
            root=root,
        )


def _capture_current_request_locked(
    *,
    session_id: str,
    turn_id: str,
    prompt: str,
    cwd: str,
    root: Path,
) -> dict[str, Any]:
    prompt = prompt.strip()
    existing = _read_state(root, session_id, allow_legacy_unsigned=True)
    if existing is not None and existing.pop("legacy_unsigned_migration", False):
        _save_state_locked(root, existing)
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
            "managed_run_required": bool(
                existing and existing.get("managed_run_required", False)
            ),
            "managed_run_started": bool(
                existing and existing.get("managed_run_started", False)
            ),
        }
        return _finalize_state(root, state)

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
            state["managed_run_required"] = bool(
                existing.get("managed_run_required", False)
            )
            return _finalize_state(root, state)
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
            state["managed_run_required"] = _requires_managed_run(prompt)
            return _finalize_state(root, state)
        if _REAFFIRM_ACTIVE_WORK.search(prompt):
            state = dict(existing)
            state.update(
                {
                    "status": "active",
                    "cwd": cwd,
                    "updated_at": utc_now(),
                    "waiting_reason": "",
                    "managed_run_required": bool(
                        existing.get("managed_run_required", True)
                    ),
                }
            )
            return _finalize_state(root, state)
        state = dict(existing)
        state.update({"cwd": cwd, "updated_at": utc_now()})
        return _finalize_state(root, state)

    natural_correction = bool(
        not prompt.rstrip().endswith("?") and _NATURAL_CORRECTION.search(prompt)
    )
    replace = bool(_REPLACE_REQUEST.search(prompt)) or natural_correction
    if existing is not None and not replace and _is_side_question(prompt):
        state = dict(existing)
        state.update({"cwd": cwd, "updated_at": utc_now()})
        _save_state_locked(root, state)
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
        "managed_run_required": (
            _requires_managed_run(prompt)
            or bool(existing and existing.get("managed_run_required") and not replace)
        ),
        "managed_run_started": False,
    }
    return _finalize_state(root, state)


def render_active_objective(state: dict[str, Any]) -> str:
    if state.get("status") == "paused":
        lines = [
            "# Manageroo continuity: paused",
            "",
            "The saved request is paused. Treat this as context only: the current "
            "operator request wins. Resume the saved managed request when the operator reaffirms it.",
            "",
            "## Saved requests",
            "",
        ]
        for index, item in enumerate(state.get("messages", []), start=1):
            lines.extend([f"{index}. {str(item.get('text') or '')}"])
        return "\n".join(lines)
    lines = [
        "Manageroo continuity: finish all active requests. Current instructions win; "
        "new work adds unless clearly replaced.",
        "Answer side questions, then resume. Preserve named scope, sources, and methods; "
        "do not ask the operator to repeat them.",
        "Active requests:",
    ]
    for index, item in enumerate(state.get("messages", []), start=1):
        relation = str(item.get("relation", "addition"))
        lines.append(f"{index}. [{relation}] {str(item.get('text') or '')}")
    if state.get("managed_run_required"):
        lines.append(
            "This request requires automatic managed execution. Start or continue the "
            "controller run; do not mutate the repository freehand."
        )
    lines.append("Only controller-owned evidence may prove completion.")
    return "\n".join(lines)


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


def _span_is_quoted(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith((">", "›")):
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
            if _span_is_quoted(text, match.start(), match.end()):
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
            if _span_is_quoted(text, match.start(), match.end()):
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


def _shell_tokens(event: dict[str, Any]) -> tuple[list[str], str]:
    if str(event.get("tool_name") or "") not in _SHELL_TOOLS:
        return [], ""
    tool_input = event.get("tool_input")
    payload = tool_input if isinstance(tool_input, dict) else {}
    key = "cmd" if isinstance(payload.get("cmd"), str) else "command"
    command = str(payload.get(key) or "")
    try:
        return shlex.split(command, posix=os.name != "nt"), key
    except ValueError:
        return [], key


def _managed_denial(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{STOPPED_MARK}{MANAGEROO_MARK} Manageroo stopped freehand work.\n"
                f"💡 Why: {reason}\n"
                "➡️ Next: Start or continue the controlled Manageroo run. The operator "
                "does not need to invoke Manageroo or repeat the request."
            ),
        }
    }


def _managed_completion_proof(state: dict[str, Any]) -> dict[str, Any] | None:
    request_path = Path(str(state.get("managed_request_path") or ""))
    expected_hash = str(state.get("managed_request_sha256") or "")
    expected_content_hash = str(
        state.get("managed_request_content_sha256") or ""
    )
    if not request_path.is_file() or not expected_hash or not expected_content_hash:
        return None
    try:
        if sha256_file(request_path) != expected_hash:
            return None
    except OSError:
        return None
    cwd = Path(str(state.get("cwd") or ".")).expanduser().resolve(strict=False)
    repo = _git_root(cwd)
    if repo is None:
        return None
    candidates = sorted(
        (repo / ".manageroo" / "runs").glob("*/delivery/final-result.json"),
        key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
        reverse=True,
    )
    for result_path in candidates:
        run_root = result_path.parents[1]
        brief_path = run_root / "artifacts" / "intake" / "product-brief.md"
        conformance_path = run_root / "artifacts" / "verification" / "intent-conformance.json"
        try:
            if (
                not brief_path.is_file()
                or sha256_text(brief_path.read_text(encoding="utf-8").strip())
                != expected_content_hash
            ):
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            conformance = json.loads(conformance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(result, dict)
            and result.get("status") == "COMPLETE"
            and result.get("applied_to_source") is True
            and isinstance(conformance, dict)
            and conformance.get("status") == "passed"
        ):
            return {"run_root": str(run_root), "result": result}
    return None


def _audit_managed_execution(
    event: dict[str, Any], state: dict[str, Any], root: Path
) -> dict[str, Any]:
    if not state.get("managed_run_required"):
        return {}
    tool_name = str(event.get("tool_name") or "")
    if tool_name in {"wait", "functions.wait"}:
        return {}
    if tool_name in {"write_stdin", "functions.write_stdin"}:
        payload = event.get("tool_input")
        chars = payload.get("chars") if isinstance(payload, dict) else None
        return {} if chars in {None, ""} else _managed_denial(
            "A controlled worker cannot be steered with new freehand instructions."
        )
    tokens, command_key = _shell_tokens(event)
    if not tokens or Path(tokens[0]).name.casefold() != "manageroo":
        return _managed_denial(
            "This actionable repository request is automatically controller-owned."
        )
    subcommand = tokens[1] if len(tokens) > 1 else ""
    if subcommand in {"status", "report", "decisions"}:
        return {}
    if subcommand != "run":
        return _managed_denial(
            "Only the Manageroo run, status, report, and decision paths belong to this request."
        )

    request_path = Path(str(state.get("managed_request_path") or ""))
    expected_hash = str(state.get("managed_request_sha256") or "")
    if not request_path.is_file() or not expected_hash:
        return _managed_denial("The controller-owned request artifact is missing.")
    try:
        if sha256_file(request_path) != expected_hash:
            return _managed_denial("The controller-owned request artifact changed.")
    except OSError:
        return _managed_denial("The controller-owned request artifact cannot be read.")

    cwd = Path(str(state.get("cwd") or ".")).expanduser().resolve(strict=False)
    repo = _git_root(cwd)
    if repo is None:
        return _managed_denial("The active request is not bound to a current Git repository.")
    if "--continue" in tokens:
        index = tokens.index("--continue")
        if index + 1 >= len(tokens):
            return _managed_denial("The continuation run id is missing.")
        rewritten = [tokens[0], "run", "--repo", str(repo), "--continue", tokens[index + 1], "--apply"]
    else:
        rewritten = [
            tokens[0],
            "run",
            "--repo",
            str(repo),
            "--brief",
            str(request_path),
            "--apply",
        ]
    if "--json" in tokens:
        rewritten.append("--json")
    state["managed_run_started"] = True
    state["managed_run_started_at"] = utc_now()
    _save_state(root, state)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {command_key: shlex.join(rewritten)},
        }
    }


def _managed_stop_decision(
    event: dict[str, Any], state: dict[str, Any], root: Path
) -> dict[str, Any]:
    if state.get("status") == "paused" or not state.get("managed_run_required"):
        return {}
    proof = _managed_completion_proof(state)
    if proof is not None:
        state["status"] = "complete"
        state["completed_run_root"] = proof["run_root"]
        state["updated_at"] = utc_now()
        _save_state(root, state)
        return {}
    if event.get("stop_hook_active") is True:
        return {}
    return {
        "decision": "block",
        "reason": (
            "Manageroo has no controller-owned COMPLETE and applied proof for the exact "
            "current request. Start `manageroo run`; if a run stopped, inspect its status "
            "and continue that run. Do not claim completion or switch to freehand work."
        ),
    }


def _additional_context(event_name: str, text: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }


def _global_controller_contract() -> str:
    return "\n".join(
        [
            "Auto-select skills. Actionable repository work automatically uses a controlled "
            "Manageroo run.",
            "Resolve the repo; never initialize home. Current instructions and live evidence win.",
            "Only a COMPLETE, applied, exact-request Manageroo run proves repository work done.",
        ]
    )


def process_codex_continuity_hook(
    event: dict[str, Any], *, state_root: Path | None = None
) -> dict[str, Any]:
    from .execution_mode import operator_continuity_enabled

    if not operator_continuity_enabled():
        return {}
    session_id = str(event.get("session_id") or "")
    if not session_id:
        return {}
    root = _safe_state_root(state_root or continuity_state_root())
    name = str(event.get("hook_event_name") or "")
    if name == "UserPromptSubmit":
        with config_mutation_lock(_state_path(root, session_id)):
            _capture_current_request_locked(
                session_id=session_id,
                turn_id=str(event.get("turn_id") or ""),
                prompt=str(event.get("prompt") or ""),
                cwd=str(event.get("cwd") or ""),
                root=root,
            )
        return {}
    if name == "Stop":
        state = _read_state(root, session_id)
        if not isinstance(state, dict):
            return {}
        return _managed_stop_decision(event, state, root)
    state = _read_state(root, session_id)
    if not isinstance(state, dict) or state.get("status") not in {"active", "waiting", "paused"}:
        if name == "SessionStart":
            return _additional_context(name, _global_controller_contract())
        return {}
    if name in {"SessionStart", "SubagentStart", "PostCompact"}:
        context = render_active_objective(state)
        if name == "SessionStart":
            context = f"{_global_controller_contract()}\n\n{context}"
        return _additional_context(name, context)
    if name == "PreToolUse":
        if state.get("status") == "paused":
            return {}
        managed = _audit_managed_execution(event, state, root)
        return managed or audit_agent_tool(event, state)
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


def continuity_hook_is_registered(*, hooks_path: Path | None = None) -> bool:
    """Return whether the host still authorizes Manageroo continuity hooks.

    Codex can retain an already-loaded hook command for the life of a session.
    Re-checking the current registration makes uninstall/disable effective for
    those cached invocations without replacing the Manageroo launcher.
    """

    if hooks_path is None:
        explicit = os.environ.get("MANAGEROO_CODEX_HOOKS_FILE", "").strip()
        if explicit:
            hooks_path = Path(explicit).expanduser()
        else:
            codex_home = Path(
                os.environ.get("CODEX_HOME") or Path.home() / ".codex"
            ).expanduser()
            hooks_path = codex_home / "hooks.json"
    try:
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        return False
    return any(
        _manageroo_hook_group(group)
        for groups in hooks.values()
        if isinstance(groups, list)
        for group in groups
    )


_CODEX_CONTINUITY_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "SubagentStart",
    "Stop",
)


def codex_continuity_hooks_status(
    *, codex_home: Path, manageroo_command: Path
) -> dict[str, Any]:
    home = codex_home.expanduser().resolve(strict=False)
    hooks_path = home / "hooks.json"
    expected_command = shlex.join(
        [str(manageroo_command.expanduser().resolve(strict=False)), HOOK_COMMAND]
    )
    try:
        payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "ok": False,
            "hooks_path": str(hooks_path),
            "missing_events": list(_CODEX_CONTINUITY_EVENTS),
            "error": "Codex hooks.json is missing.",
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "hooks_path": str(hooks_path),
            "missing_events": list(_CODEX_CONTINUITY_EVENTS),
            "error": f"Codex hooks.json is unreadable or malformed: {exc}",
        }
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        return {
            "ok": False,
            "hooks_path": str(hooks_path),
            "missing_events": list(_CODEX_CONTINUITY_EVENTS),
            "error": "Codex hooks.json does not contain a hooks object.",
        }
    missing_events: list[str] = []
    for event in _CODEX_CONTINUITY_EVENTS:
        groups = hooks.get(event)
        matching = [] if not isinstance(groups, list) else [
            group for group in groups if _manageroo_hook_group(group)
        ]
        valid = False
        if len(matching) == 1:
            handlers = matching[0].get("hooks")
            valid = bool(
                isinstance(handlers, list)
                and len(handlers) == 1
                and isinstance(handlers[0], dict)
                and handlers[0].get("command") == expected_command
            )
        if not valid:
            missing_events.append(event)
    return {
        "ok": not missing_events,
        "hooks_path": str(hooks_path),
        "missing_events": missing_events,
        "error": "" if not missing_events else "Manageroo continuity hooks are missing or point to a different launcher.",
    }


def remove_codex_continuity_hooks(
    *, codex_home: Path, manageroo_command: Path
) -> dict[str, Any]:
    home = codex_home.expanduser().resolve(strict=False)
    hooks_path = home / "hooks.json"
    expected_command = shlex.join(
        [str(manageroo_command.expanduser().resolve(strict=False)), HOOK_COMMAND]
    )
    with config_mutation_lock(hooks_path):
        try:
            payload = json.loads(hooks_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "ok": True,
                "path": str(hooks_path),
                "changed": False,
                "removed": 0,
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot safely remove Codex hooks: {exc}") from exc
        hooks = payload.get("hooks") if isinstance(payload, dict) else None
        if not isinstance(hooks, dict):
            raise ConfigurationError("Codex hooks file must contain a hooks object")
        removed = 0
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                raise ConfigurationError(f"Codex hook event {event} must contain an array")
            kept = []
            for group in groups:
                handlers = group.get("hooks") if isinstance(group, dict) else None
                matches = bool(
                    isinstance(handlers, list)
                    and any(
                        isinstance(handler, dict)
                        and handler.get("command") == expected_command
                        for handler in handlers
                    )
                )
                if matches:
                    removed += 1
                else:
                    kept.append(group)
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if removed:
            atomic_write_json(hooks_path, payload)
    return {
        "ok": True,
        "path": str(hooks_path),
        "changed": bool(removed),
        "removed": removed,
    }


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
        "SubagentStart": {"hooks": [context_handler]},
        "Stop": {"hooks": [context_handler]},
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
