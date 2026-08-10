from __future__ import annotations

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

from .config_lock import config_mutation_lock
from .errors import ConfigurationError
from .util import atomic_write_json, canonical_json_bytes


RECEIPT_SCHEMA_VERSION = 3
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9._~+@%:,=/-]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]:[\\/][^\s'\"`;|&]+)")
_CLAUSE_BOUNDARY = re.compile(r"[.!?;\n]")
_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|never|must\s+not|mustn't|without|not\s+authorized\s+to)\b",
    re.IGNORECASE,
)
_ACTION_PATTERNS = {
    "mutate": re.compile(
        r"\b(?:build|change|clean\s*up|configure|copy|create|delete|deliver|edit|"
        r"export|fix|generate|implement|finish|install|make|move|patch|publish|"
        r"rebuild|release|remove|render|repair|restore|save|ship|update|write)\b|"
        r"\bmake\s+it\s+live\b",
        re.IGNORECASE,
    ),
    "commit": re.compile(
        r"\b(?:commit|finish|publish|release|ship)\b|\bmake\s+it\s+live\b",
        re.IGNORECASE,
    ),
    "push": re.compile(
        r"\b(?:finish|push|publish|ship)\b|\bmake\s+it\s+live\b",
        re.IGNORECASE,
    ),
    "deploy": re.compile(
        r"\bdeploy\b|\b(?:go|make\s+it)\s+live\b",
        re.IGNORECASE,
    ),
    "install": re.compile(r"\b(?:configure|install)\b", re.IGNORECASE),
    "delete": re.compile(r"\b(?:clean\s*up|delete|remove)\b", re.IGNORECASE),
}
_SHELL_ACTION_PATTERNS = (
    ("push", re.compile(r"(?:^|[;&|]\s*)git\s+(?:[^;&|]*\s)?push(?:\s|$)")),
    ("commit", re.compile(r"(?:^|[;&|]\s*)git\s+(?:[^;&|]*\s)?commit(?:\s|$)")),
    (
        "deploy",
        re.compile(
            r"(?:^|[;&|]\s*)(?:vercel(?:\s+deploy)?|netlify\s+deploy|fly\s+deploy|"
            r"npm\s+run\s+deploy|pnpm\s+run\s+deploy|yarn\s+deploy|"
            r"kubectl\s+(?:apply|create|replace)|gh\s+release\s+create)(?:\s|$)"
        ),
    ),
    (
        "install",
        re.compile(
            r"(?:^|[;&|]\s*)(?:brew|pipx?|python\d*(?:\.\d+)?\s+-m\s+pip|npm|pnpm|"
            r"yarn|bun|cargo)\s+(?:install|add)(?:\s|$)"
        ),
    ),
    (
        "delete",
        re.compile(
            r"(?:^|[;&|]\s*)(?:rm|rmdir|unlink|gio\s+trash)(?:\s|$)|"
            r"(?:^|[;&|]\s*)git\s+(?:[^;&|]*\s)?clean(?:\s|$)"
        ),
    ),
    (
        "mutate",
        re.compile(
            r"(?:^|[;&|]\s*)(?:chmod|chown|cp|install|ln|mkdir|mkfifo|mv|"
            r"patch|rename|rsync|sed\s+-i|tee|touch|truncate)(?:\s|$)|"
            r"(?:^|[;&|]\s*)git\s+(?:[^;&|]*\s)?(?:add|am|apply|checkout|"
            r"cherry-pick|clean|merge|mv|pull|rebase|reset|restore|rm|switch|"
            r"tag)(?:\s|$)|(?:^|[^<])(?:>>|>)(?!=)",
            re.IGNORECASE,
        ),
    ),
    (
        "mutate",
        re.compile(
            r"(?:^|[;&|]\s*)manageroo\s+(?:"
            r"run\b|solo\b|setup\b|init\b|brief\b|"
            r"memory\s+(?:init|update)\b|intent\s+capture\b|"
            r"decisions\s+answer\b|checks\s+(?:add|suggest\b[^;&|]*--apply)\b|"
            r"idea\s+add\b|learning\s+apply\b|integrations\s+configure\b|"
            r"skills\s+reconcile\b[^;&|]*--apply\b|stack-update\b[^;&|]*--apply\b"
            r")",
            re.IGNORECASE,
        ),
    ),
)
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
    re.MULTILINE,
)
_HOOK_COMMAND_TOKEN = "operator-scope-hook"
_MANAGEROO_SKILL = re.compile(r"\$?uncle-matts-project-manageroo", re.IGNORECASE)
_REFERENTIAL_FOLLOWUP = re.compile(
    r"(?:^\s*(?:>\s*)?(?:yes|and|also|now|then|leave|keep|make\s+sure|in\s+the\s+whole)\b|"
    r"\b(?:it|that|those|them|the\s+(?:txt|file|document|folder|output|target)|"
    r"whole\s+(?:txt|file|document)|everything|all\s+of\s+it|make\s+sure|"
    r"what\s+i\s+(?:said|asked|told))\b)",
    re.IGNORECASE,
)
_EXPLICIT_MUTATION_PROHIBITION = re.compile(
    r"\b(?:do\s+not|don't|never)\s+(?:edit|change|modify|patch|update|write|delete|remove|move|touch)\b|"
    r"\b(?:just|only)\s+(?:explain|review|read|inspect|look)\b",
    re.IGNORECASE,
)


def operator_scope_state_root() -> Path:
    explicit = os.environ.get("MANAGEROO_OPERATOR_SCOPE_STATE")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "manageroo" / "operator-scope"


def _receipt_path(state_root: Path, session_id: str) -> Path:
    identity = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return state_root / "receipts" / f"{identity}.json"


def _authority_key_path(state_root: Path) -> Path:
    return state_root / "authority.key"


def _validate_private_file(path: Path, *, expected_size: int | None = None) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        file_state = os.fstat(descriptor)
        if not stat.S_ISREG(file_state.st_mode) or file_state.st_nlink != 1:
            raise ValueError(f"Operator-scope file is not a private regular file: {path}")
        if os.name != "nt":
            if hasattr(os, "getuid") and file_state.st_uid != os.getuid():
                raise ValueError(f"Operator-scope file has the wrong owner: {path}")
            if stat.S_IMODE(file_state.st_mode) & 0o077:
                raise ValueError(f"Operator-scope file is readable by another account: {path}")
        value = os.read(descriptor, max(128, (expected_size or 0) + 1, 1024 * 1024))
    finally:
        os.close(descriptor)
    if expected_size is not None and len(value) != expected_size:
        raise ValueError(f"Operator-scope authority has an invalid length: {path}")
    return value


def _prepare_state_root(path: Path) -> Path:
    lexical = path.expanduser().absolute()
    try:
        state = lexical.lstat()
    except FileNotFoundError:
        lexical.mkdir(parents=True, mode=0o700)
        state = lexical.lstat()
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISDIR(state.st_mode):
        raise ValueError(f"Operator-scope state root is not a private directory: {lexical}")
    if os.name != "nt":
        if hasattr(os, "getuid") and state.st_uid != os.getuid():
            raise ValueError(f"Operator-scope state root has the wrong owner: {lexical}")
        if stat.S_IMODE(state.st_mode) & 0o077:
            raise ValueError(f"Operator-scope state root is accessible by another account: {lexical}")
    return lexical.resolve(strict=True)


def _authority_key(state_root: Path, *, create: bool) -> bytes:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(state_root, 0o700)
    path = _authority_key_path(state_root)
    if create and not path.exists():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            pass
        else:
            try:
                value = secrets.token_bytes(32)
                if os.write(descriptor, value) != len(value):
                    raise OSError("short authority-key write")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return _validate_private_file(path, expected_size=32)


def _sign_receipt(receipt: dict[str, Any], key: bytes) -> str:
    unsigned = {name: value for name, value in receipt.items() if name != "signature"}
    return hmac.new(key, canonical_json_bytes(unsigned), hashlib.sha256).hexdigest()


def _directive_prefix(value: str) -> str:
    """Normalize harmless Markdown list/quote markers around an operator directive."""
    normalized = value.strip().lower()
    normalized = re.sub(r"^(?:(?:>+|[-*+]|\d+[.)])\s*)+", "", normalized)
    return " ".join(normalized.split())


def _action_is_explicit(prompt: str, pattern: re.Pattern[str]) -> bool:
    for match in pattern.finditer(prompt):
        clause_start = 0
        for boundary in _CLAUSE_BOUNDARY.finditer(prompt, 0, match.start()):
            clause_start = boundary.end()
        prefix = prompt[clause_start : match.start()]
        if _NEGATED_ACTION.search(prefix):
            continue
        normalized = _directive_prefix(prefix)
        if not normalized:
            return True
        if re.match(r"^(?:why|what|when|where|who|how|did|does|do|is|are|was|were|has|have|had)\b", normalized):
            continue
        if re.fullmatch(
            r"(?:(?:please|now|then|also|ok|okay|permanently)\s+)*",
            normalized,
        ):
            return True
        if re.fullmatch(r"\$?uncle-matts-project-manageroo(?:\s+please)?\s*", normalized):
            return True
        if re.fullmatch(
            r"(?:i\s+(?:want|need|authorize)\s+you\s+to|you\s+(?:must|should)|go\s+ahead(?:\s+and)?)"
            r"(?:\s+(?:please|now|permanently))*\s*",
            normalized,
        ):
            return True
        connector = re.search(r"\b(?:and|then|also)\b\s*(?:please\s+|now\s+|permanently\s+)*$", normalized)
        if connector and not re.match(
            r"^(?:why|what|when|where|who|how|did|does|is|are|was|were|has|have|had)\b",
            normalized,
        ):
            return True
    return False


def _allowed_actions(prompt: str) -> list[str]:
    actions = ["read"]
    for action, pattern in _ACTION_PATTERNS.items():
        if _action_is_explicit(prompt, pattern):
            actions.append(action)
    return actions


def _allowed_repo_paths(prompt: str, repo: Path) -> list[str]:
    """Narrow an explicit `only` request to named repo paths; otherwise lock the repo."""
    if not re.search(r"\bonly\b|do\s+not\s+(?:edit|change|modify|touch)\s+any\s+other", prompt, re.IGNORECASE):
        return [str(repo)]
    candidates = re.findall(
        r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+(?:[/\\][A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+)(?![A-Za-z0-9_.-])",
        prompt,
    )
    allowed: list[str] = []
    for value in candidates:
        candidate = (repo / value).resolve(strict=False)
        if _inside(candidate, repo) and str(candidate) not in allowed:
            allowed.append(str(candidate))
    return allowed or [str(repo)]


def _repo_root(cwd: Path) -> Path:
    current = cwd.expanduser().resolve(strict=True)
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate.resolve(strict=True)
    raise ValueError(f"No Git repository contains Codex cwd: {cwd}")


def _requested_repo_root(prompt: str, current_repo: Path) -> Path:
    """Honor one explicit, existing repo transition named by the current prompt."""
    candidates: list[Path] = []
    matches = [*list(_ABSOLUTE_POSIX_PATH.finditer(prompt)), *list(_ABSOLUTE_WINDOWS_PATH.finditer(prompt))]
    for match in matches:
        prefix = prompt[max(0, match.start() - 100) : match.start()]
        explicit_transition = re.search(
            r"(?:switch\s+to|work(?:\s+only)?\s+(?:in|on)|"
            r"(?:fix|repair|review|edit|update)\s+(?:only\s+)?in)\s*$",
            prefix,
            re.IGNORECASE,
        )
        direct_repo = re.search(
            r"(?:^|[.!?;\n]\s*)(?:please\s+)?(?:fix|repair|review|update)\s+(?:only\s+)?$",
            prefix,
            re.IGNORECASE,
        )
        if not explicit_transition and not direct_repo:
            continue
        candidate = None
        for value in (match.group(1), match.group(1).rstrip(".,")):
            try:
                requested = Path(value).expanduser()
                if direct_repo and not explicit_transition:
                    resolved = requested.resolve(strict=True)
                    if not resolved.is_dir() or not (resolved / ".git").exists():
                        continue
                    candidate = resolved
                else:
                    candidate = _repo_root(requested)
                break
            except (OSError, ValueError):
                pass
        if candidate is None:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates[0] if len(candidates) == 1 else current_repo


def _path_identity(path: Path) -> dict[str, int]:
    path_state = path.stat()
    return {"device": path_state.st_dev, "inode": path_state.st_ino}


def _named_external_read_paths(prompt: str, repo: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    matches = sorted(
        [*_ABSOLUTE_POSIX_PATH.finditer(prompt), *_ABSOLUTE_WINDOWS_PATH.finditer(prompt)],
        key=lambda item: item.start(),
    )
    for match in matches:
        clause_start = 0
        for boundary in _CLAUSE_BOUNDARY.finditer(prompt, 0, match.start()):
            clause_start = boundary.end()
        prefix = _directive_prefix(prompt[clause_start : match.start()])
        if _NEGATED_ACTION.search(prefix) or not re.match(
            r"^(?:please\s+)?(?:review|read|inspect|open|use)\b",
            prefix,
        ):
            continue
        value = match.group(1)
        try:
            path = Path(value).expanduser().resolve(strict=True)
            state = path.stat()
        except (OSError, RuntimeError):
            continue
        if _inside(path, repo) or not stat.S_ISREG(state.st_mode):
            continue
        entry = {"path": str(path), "identity": _path_identity(path)}
        if entry not in entries:
            entries.append(entry)
    return entries


def _named_external_write_paths(prompt: str, repo: Path) -> list[dict[str, Any]]:
    """Capture only affirmative, explicit external output destinations."""
    entries: list[dict[str, Any]] = []
    matches = sorted(
        [*_ABSOLUTE_POSIX_PATH.finditer(prompt), *_ABSOLUTE_WINDOWS_PATH.finditer(prompt)],
        key=lambda item: item.start(),
    )
    for match in matches:
        clause_start = 0
        for boundary in _CLAUSE_BOUNDARY.finditer(prompt, 0, match.start()):
            clause_start = boundary.end()
        prefix = _directive_prefix(prompt[clause_start : match.start()])
        if _NEGATED_ACTION.search(prefix) or not re.search(
            r"(?:\b(?:change|copy|create|deliver|edit|export|fix|generate|modify|move|"
            r"output|patch|put|render|save|update|write)\b"
            r"[^.!?;\n]{0,120}\b(?:at|in|into|to|under)\s*|"
            r"\b(?:change|copy|create|deliver|edit|export|fix|generate|modify|move|"
            r"output|patch|put|render|save|update|write)\s*|"
            r"\b(?:destination|output|target)(?:\s+(?:directory|folder|path))?\s*:\s*)$",
            prefix,
            re.IGNORECASE,
        ):
            continue
        raw_value = match.group(1).rstrip(".,")
        candidate = Path(raw_value).expanduser().resolve(strict=False)
        if _inside(candidate, repo):
            continue
        try:
            existing = candidate
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            state = existing.stat()
        except OSError:
            continue
        if not (stat.S_ISDIR(state.st_mode) or stat.S_ISREG(state.st_mode)):
            continue
        subtree = candidate.exists() and candidate.is_dir()
        entry = {
            "path": str(candidate),
            "subtree": subtree,
            "anchor": str(existing.resolve(strict=True)),
            "anchor_identity": _path_identity(existing),
        }
        if entry not in entries:
            entries.append(entry)
    return entries


def _referential_followup(prompt: str) -> bool:
    """Recognize a user continuation that refers to the already signed task target."""
    return bool(_REFERENTIAL_FOLLOWUP.search(prompt))


def _manageroo_instruction_reads(repo: Path) -> list[dict[str, Any]]:
    """Pin the one skill entrypoint an explicit Manageroo turn must be able to read."""
    candidates = (
        repo / "src" / "manageroo" / "assets" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md",
        Path.home() / ".agents" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md",
        Path.home() / ".codex" / "skills" / "uncle-matts-project-manageroo" / "SKILL.md",
    )
    entries: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            path = candidate.expanduser().resolve(strict=True)
            state = path.stat()
        except (OSError, RuntimeError):
            continue
        if not stat.S_ISREG(state.st_mode):
            continue
        entry = {"path": str(path), "identity": _path_identity(path)}
        if entry not in entries:
            entries.append(entry)
    return entries


def _git_common_directory(repo: Path) -> Path:
    marker = repo / ".git"
    if marker.is_dir():
        return marker.resolve(strict=True)
    if not marker.is_file():
        raise ValueError(f"Repository has no usable .git marker: {repo}")
    text = marker.read_text(encoding="utf-8", errors="strict")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if not first_line.startswith("gitdir: "):
        raise ValueError(f"Repository .git file has no gitdir: {marker}")
    git_dir = Path(first_line.removeprefix("gitdir: ").strip()).expanduser()
    if not git_dir.is_absolute():
        git_dir = repo / git_dir
    git_dir = git_dir.resolve(strict=True)
    common_marker = git_dir / "commondir"
    if not common_marker.is_file():
        return git_dir
    common_value = common_marker.read_text(encoding="utf-8", errors="strict").strip()
    if not common_value:
        raise ValueError(f"Repository commondir is empty: {common_marker}")
    common = Path(common_value).expanduser()
    if not common.is_absolute():
        common = git_dir / common
    return common.resolve(strict=True)


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _capture(
    event: dict[str, Any], state_root: Path, *, now: datetime
) -> dict[str, Any]:
    session_id = str(event.get("session_id") or "")
    turn_id = str(event.get("turn_id") or "")
    prompt = str(event.get("prompt") or "")
    if not session_id or not turn_id or not prompt:
        return {}
    try:
        repo = _repo_root(Path(str(event.get("cwd") or ".")))
        repo = _requested_repo_root(prompt, repo)
    except (OSError, ValueError):
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "active": False,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        }
        receipt["signature"] = _sign_receipt(
            receipt, _authority_key(state_root, create=True)
        )
        path = _receipt_path(state_root, session_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
        atomic_write_json(path, receipt)
        return {}
    common_dir = _git_common_directory(repo)
    operator_messages = _operator_messages(event)
    current_actions = _allowed_actions(prompt)
    current_paths = _allowed_repo_paths(prompt, repo)
    current_reads = _named_external_read_paths(prompt, repo)
    current_writes = _named_external_write_paths(prompt, repo)
    previous = _load_receipt(
        event,
        state_root,
        now=now,
        require_turn=False,
    )
    continues_previous = bool(
        previous
        and _referential_followup(prompt)
        and previous.get("active") is True
        and previous.get("repo_root") == str(repo)
        and previous.get("repo_identity") == _path_identity(repo)
        and previous.get("git_common_dir") == str(common_dir)
        and previous.get("git_common_identity") == _path_identity(common_dir)
    )
    if continues_previous:
        previous_actions = previous.get("allowed_actions")
        if (
            isinstance(previous_actions, list)
            and not _EXPLICIT_MUTATION_PROHIBITION.search(prompt)
        ):
            current_actions = list(
                dict.fromkeys(
                    [
                        *current_actions,
                        *(
                            action
                            for action in previous_actions
                            if isinstance(action, str)
                        ),
                    ]
                )
            )
        if current_paths == [str(repo)]:
            previous_paths = previous.get("allowed_paths")
            if isinstance(previous_paths, list) and all(
                isinstance(path, str) for path in previous_paths
            ):
                current_paths = previous_paths
        if not current_reads:
            previous_reads = previous.get("allowed_external_reads")
            if isinstance(previous_reads, list):
                current_reads = previous_reads
        if not current_writes and not _EXPLICIT_MUTATION_PROHIBITION.search(prompt):
            previous_writes = previous.get("allowed_external_writes")
            if isinstance(previous_writes, list):
                current_writes = previous_writes
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "active": True,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "session_id": session_id,
        "turn_id": turn_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "operator_messages": operator_messages,
        "operator_messages_sha256": hashlib.sha256(
            canonical_json_bytes(operator_messages)
        ).hexdigest(),
        "repo_root": str(repo),
        "repo_identity": _path_identity(repo),
        "git_common_dir": str(common_dir),
        "git_common_identity": _path_identity(common_dir),
        "allowed_paths": current_paths,
        "allowed_external_reads": current_reads,
        "allowed_external_writes": current_writes,
        "allowed_instruction_reads": _manageroo_instruction_reads(repo),
        "allowed_actions": current_actions,
        "continues_previous_scope": continues_previous,
        "controlled_run_required": bool(
            _MANAGEROO_SKILL.search(prompt)
            or (continues_previous and previous.get("controlled_run_required") is True)
        ),
        "controlled_run_started": False,
        "temporary_root": str(repo / ".manageroo" / "operator-tmp"),
    }
    receipt["signature"] = _sign_receipt(receipt, _authority_key(state_root, create=True))
    path = _receipt_path(state_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    atomic_write_json(path, receipt)
    return {}


def _user_message_text(value: object) -> list[str]:
    """Extract user-authored text from the current Codex JSONL transcript shape."""
    if isinstance(value, dict):
        if value.get("role") == "user":
            content = value.get("content")
            if isinstance(content, str):
                return [content]
            texts: list[str] = []
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if isinstance(text, str) and item.get("type") in {"input_text", "text"}:
                        texts.append(text)
            return texts
        messages: list[str] = []
        for child in value.values():
            messages.extend(_user_message_text(child))
        return messages
    if isinstance(value, list):
        messages = []
        for child in value:
            messages.extend(_user_message_text(child))
        return messages
    return []


def _operator_messages(event: dict[str, Any]) -> list[str]:
    """Snapshot bounded user-only conversation context; fall back to the current prompt."""
    messages: list[str] = []
    transcript_value = event.get("transcript_path")
    if isinstance(transcript_value, str) and transcript_value:
        try:
            transcript = Path(transcript_value).expanduser().resolve(strict=True)
            state = transcript.stat()
            if (
                stat.S_ISREG(state.st_mode)
                and state.st_size <= 16 * 1024 * 1024
                and (not hasattr(os, "getuid") or state.st_uid == os.getuid())
            ):
                for line in transcript.read_text(encoding="utf-8", errors="strict").splitlines():
                    if line.strip():
                        messages.extend(_user_message_text(json.loads(line)))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError):
            messages = []
    bounded: list[str] = []
    for message in messages[-32:]:
        value = message.strip()
        if value and (not bounded or bounded[-1] != value):
            bounded.append(value[:32768])
    prompt = str(event.get("prompt") or "").strip()
    if prompt and (not bounded or bounded[-1] != prompt):
        bounded.append(prompt[:32768])
    while len(canonical_json_bytes(bounded)) > 256 * 1024 and len(bounded) > 1:
        bounded.pop(0)
    return bounded


def load_operator_context(
    receipt_path: Path,
    *,
    repo: Path,
    state_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a hook-injected receipt and return its signed operator conversation."""
    state = _prepare_state_root(state_root or operator_scope_state_root())
    expected_parent = (state / "receipts").resolve(strict=True)
    path = receipt_path.expanduser().resolve(strict=True)
    if path.parent != expected_parent:
        raise ConfigurationError("Operator receipt is outside Manageroo's private receipt store.")
    try:
        receipt = json.loads(_validate_private_file(path).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Operator receipt is invalid: {exc}") from exc
    current = now or datetime.now(timezone.utc)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ConfigurationError("Operator receipt schema is invalid or stale.")
    try:
        expires_at = datetime.fromisoformat(str(receipt["expires_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError("Operator receipt expiry is invalid.") from exc
    if expires_at.tzinfo is None or current >= expires_at:
        raise ConfigurationError("Operator receipt expired.")
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(
        signature,
        _sign_receipt(receipt, _authority_key(state, create=False)),
    ):
        raise ConfigurationError("Operator receipt signature is invalid.")
    locked_repo = repo.expanduser().resolve(strict=True)
    if (
        receipt.get("active") is not True
        or receipt.get("controlled_run_required") is not True
        or receipt.get("repo_root") != str(locked_repo)
        or receipt.get("repo_identity") != _path_identity(locked_repo)
    ):
        raise ConfigurationError("Operator receipt does not authorize this repository run.")
    messages = receipt.get("operator_messages")
    if not isinstance(messages, list) or not messages or any(
        not isinstance(message, str) or not message.strip() for message in messages
    ):
        raise ConfigurationError("Operator receipt has no usable signed conversation context.")
    messages_hash = hashlib.sha256(canonical_json_bytes(messages)).hexdigest()
    if receipt.get("operator_messages_sha256") != messages_hash:
        raise ConfigurationError("Operator conversation context does not match its signed hash.")
    return {
        "messages": messages,
        "messages_sha256": messages_hash,
        "prompt_sha256": receipt.get("prompt_sha256"),
        "turn_id": receipt.get("turn_id"),
    }


def _load_receipt(
    event: dict[str, Any],
    state_root: Path,
    *,
    now: datetime,
    require_turn: bool = True,
) -> dict[str, Any] | None:
    session_id = str(event.get("session_id") or "")
    turn_id = str(event.get("turn_id") or "")
    if not session_id or not turn_id:
        return None
    path = _receipt_path(state_root, session_id)
    try:
        receipt = json.loads(_validate_private_file(path).decode("utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(receipt, dict):
        return None
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return None
    if receipt.get("session_id") != session_id:
        return None
    if require_turn and receipt.get("turn_id") != turn_id:
        return None
    try:
        expires_at = datetime.fromisoformat(str(receipt["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return None
    if expires_at.tzinfo is None or now >= expires_at:
        return None
    signature = receipt.get("signature")
    if not isinstance(signature, str):
        return None
    try:
        expected = _sign_receipt(receipt, _authority_key(state_root, create=False))
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not hmac.compare_digest(signature, expected):
        return None
    return receipt


def _mark_controlled_run_started(
    receipt: dict[str, Any], state_root: Path, *, now: datetime
) -> None:
    """Persist that the signed controlled run was launched for this exact turn."""
    path = _receipt_path(state_root, str(receipt["session_id"]))
    with config_mutation_lock(path):
        current = _load_receipt(
            {
                "session_id": receipt["session_id"],
                "turn_id": receipt["turn_id"],
            },
            state_root,
            now=now,
        )
        if current is None or current.get("signature") != receipt.get("signature"):
            raise ConfigurationError(
                "Operator receipt changed before the controlled run could start."
            )
        current["controlled_run_started"] = True
        current["controlled_run_started_at"] = now.isoformat()
        current["signature"] = _sign_receipt(
            current, _authority_key(state_root, create=False)
        )
        atomic_write_json(path, current)


def _authorize_stop(
    event: dict[str, Any], state_root: Path, *, now: datetime
) -> dict[str, Any]:
    """Keep an explicit Manageroo turn alive until its signed run is launched."""
    receipt = _load_receipt(event, state_root, now=now)
    if (
        receipt is not None
        and receipt.get("active") is True
        and receipt.get("controlled_run_required") is True
        and receipt.get("controlled_run_started") is not True
        and event.get("stop_hook_active") is not True
    ):
        return {
            "decision": "block",
            "reason": (
                "The operator explicitly invoked Manageroo, but this turn has not started "
                "the signed `manageroo run`. Start that controlled run now; do not finish, "
                "fall back to freehand work, or substitute another workflow."
            ),
        }
    return {}


def _command_paths(command: str, cwd: Path) -> list[Path]:
    values = [match.group(1) for match in _ABSOLUTE_POSIX_PATH.finditer(command)]
    values.extend(match.group(1) for match in _ABSOLUTE_WINDOWS_PATH.finditer(command))
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = []
    for token in tokens:
        candidate = token.split("=", 1)[1] if token.startswith("--") and "=" in token else token
        if candidate.startswith(("http://", "https://")):
            continue
        if (
            candidate in {".", "..", "~"}
            or candidate.startswith(("./", "../", "~/"))
            or "/" in candidate
            or "\\" in candidate
            or re.fullmatch(r"[^/\\]+\.[A-Za-z0-9][A-Za-z0-9._-]*", candidate)
        ):
            values.append(candidate)
    paths: list[Path] = []
    for value in values:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        resolved = candidate.resolve(strict=False)
        if resolved not in paths:
            paths.append(resolved)
    return paths


def _patch_paths(command: str, root: Path) -> list[Path]:
    paths: list[Path] = []
    for match in _PATCH_PATH.finditer(command):
        value = match.group(1).strip()
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        paths.append(candidate.resolve(strict=False))
    return paths


def _required_shell_actions(command: str) -> list[str]:
    normalized = " ".join(command.strip().split())
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        tokens = []
    if tokens and Path(tokens[0]).name.lower() == "manageroo" and len(tokens) > 1 and tokens[1] == "operator-exec":
        try:
            separator = tokens.index("--")
        except ValueError:
            pass
        else:
            normalized += " ; " + shlex.join(tokens[separator + 1 :])
    return list(dict.fromkeys(
        action
        for action, pattern in _SHELL_ACTION_PATTERNS
        if pattern.search(normalized)
    ))


def _unprovable_shell_reason(command: str) -> str | None:
    """Reject command forms whose effective argv or nested behavior cannot be proven."""
    if re.search(r"[`$]", command):
        return "dynamic shell expansion"
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return "invalid shell quoting"
    if not tokens:
        return "empty shell command"
    executable = Path(tokens[0]).name.lower()
    if executable in {"sh", "bash", "zsh", "fish", "dash", "cmd", "powershell", "pwsh"}:
        return "nested shell execution"
    if executable in {"python", "python3", "node", "nodejs", "perl", "ruby", "php"} and any(
        token in {"-c", "-e", "--eval"} for token in tokens[1:]
    ):
        return "dynamic interpreter code"
    if executable == "codex" and any(
        token in {"--ignore-user-config", "--disable-hooks", "--no-hooks"}
        for token in tokens[1:]
    ):
        return "nested Codex hook bypass"
    if executable in {"eval", "xargs"} or (executable == "find" and any(token.startswith("-exec") for token in tokens[1:])):
        return "indirect command execution"
    return None


def _direct_shell_is_provable(command: str) -> bool:
    """Allow direct argv only for inspected primitives; opaque programs require operator-exec."""
    if re.search(r"(?:&&|\|\||[;|<>])", command):
        return False
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return False
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    if executable == "manageroo" and len(tokens) > 1:
        if tokens[1] == "operator-exec":
            return "--" in tokens and tokens.index("--") < len(tokens) - 1
        return tokens[1] in {
            "brief", "checks", "compact", "decisions", "doctor", "init", "intent",
            "memory", "next", "ready", "report", "run", "setup", "solo", "status",
        }
    if executable in {
        "cat", "cmp", "diff", "file", "grep", "head", "less", "ls", "more",
        "pwd", "rg", "sha256sum", "shasum", "stat", "tail", "wc", "which",
        "cp", "mv", "mkdir", "touch", "rm", "rmdir", "unlink", "chmod", "chown",
        "ln", "patch", "rename", "rsync", "tee", "truncate", "vercel", "netlify",
        "fly", "kubectl", "gh", "brew", "pip", "pip3", "pipx", "npm", "pnpm",
        "yarn", "bun", "cargo", "gio",
    }:
        return True
    if executable == "sed":
        return not any(token in {"-i", "--in-place", "-e"} or token.startswith("-i") for token in tokens[1:])
    if executable == "find":
        return not any(token == "-delete" or token.startswith("-exec") for token in tokens[1:])
    if executable == "git":
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token in {"-C", "--git-dir", "--work-tree", "-c"}:
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            return token in {
                "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean",
                "commit", "diff", "fetch", "log", "ls-files", "merge", "mv", "pull",
                "push", "rebase", "remote", "reset", "restore", "rev-parse", "rm", "show",
                "status", "switch", "tag", "worktree",
            }
        return False
    return False


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _belongs_to_git_repository(path: Path) -> bool:
    candidate = path.resolve(strict=False)
    if not candidate.is_dir():
        candidate = candidate.parent
    return any((parent / ".git").exists() for parent in (candidate, *candidate.parents))


def _external_read_allowed(path: Path, receipt: dict[str, Any]) -> bool:
    entries = receipt.get("allowed_external_reads")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("path") != str(path):
            continue
        try:
            return entry.get("identity") == _path_identity(path)
        except OSError:
            return False
    return False


def _external_write_allowed(path: Path, receipt: dict[str, Any]) -> bool:
    entries = receipt.get("allowed_external_writes")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            root = Path(str(entry["path"])).resolve(strict=False)
            anchor = Path(str(entry["anchor"])).resolve(strict=True)
            if entry.get("anchor_identity") != _path_identity(anchor):
                continue
        except (KeyError, OSError, RuntimeError):
            continue
        if path == root or (entry.get("subtree") is True and _inside(path, root)):
            return True
    return False


def _instruction_read_allowed(path: Path, receipt: dict[str, Any]) -> bool:
    entries = receipt.get("allowed_instruction_reads")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("path") != str(path):
            continue
        try:
            return entry.get("identity") == _path_identity(path)
        except OSError:
            return False
    return False


def _structured_tool_paths(value: object, cwd: Path, *, key: str = "") -> list[Path]:
    paths: list[Path] = []
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            paths.extend(
                _structured_tool_paths(child_value, cwd, key=str(child_key).lower())
            )
        return paths
    if isinstance(value, list):
        for child in value:
            paths.extend(_structured_tool_paths(child, cwd, key=key))
        return paths
    if not isinstance(value, str) or not re.search(
        r"(?:^|_)(?:cwd|dir|directory|file|folder|path|root|source|target)(?:$|_)",
        key,
    ):
        return paths
    if value.startswith(("http://", "https://", "data:")):
        return paths
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    paths.append(candidate.resolve(strict=False))
    return paths


def _tool_mutates(tool_name: str) -> bool:
    return bool(
        re.search(
            r"(?:^|[_:.\-])(?:add|apply|commit|copy|create|delete|deploy|edit|install|"
            r"move|patch|publish|push|remove|rename|replace|update|upload|write)"
            r"(?:$|[_:.\-])",
            tool_name,
            re.IGNORECASE,
        )
    )


def _tool_deletes(tool_name: str) -> bool:
    return bool(re.search(r"(?:delete|remove|unlink)", tool_name, re.IGNORECASE))


def _required_tool_actions(tool_name: str) -> list[str]:
    actions = []
    for action, words in (
        ("commit", "commit"),
        ("push", "push"),
        ("deploy", "deploy|publish|release"),
        ("install", "install"),
        ("delete", "delete|remove|unlink|trash"),
    ):
        if re.search(rf"(?:^|[_:.\-])(?:{words})(?:$|[_:.\-])", tool_name, re.IGNORECASE):
            actions.append(action)
    return actions


def _path_is_allowed(path: Path, receipt: dict[str, Any]) -> bool:
    values = receipt.get("allowed_paths")
    if not isinstance(values, list) or not values:
        return False
    for value in values:
        if not isinstance(value, str):
            continue
        allowed = Path(value).resolve(strict=False)
        if path == allowed or _inside(path, allowed):
            return True
    temporary = receipt.get("temporary_root")
    if isinstance(temporary, str) and temporary:
        root = Path(temporary).resolve(strict=False)
        if path == root or _inside(path, root):
            return True
    return False


def _private_temporary_paths_only(
    paths: list[Path], receipt: dict[str, Any]
) -> bool:
    temporary = receipt.get("temporary_root")
    if not paths or not isinstance(temporary, str) or not temporary:
        return False
    root = Path(temporary).resolve(strict=False)
    return all(path == root or _inside(path, root) for path in paths)


def _shell_command(tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "cmd", "code"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


def _controlled_shell_allowed(tokens: list[str]) -> bool:
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    if executable == "manageroo":
        return True
    if executable != "git":
        return False
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-C", "--git-dir", "--work-tree", "-c"}:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token in {
            "commit",
            "diff",
            "log",
            "ls-files",
            "ls-remote",
            "push",
            "rev-parse",
            "show",
            "status",
        }
    return False


def _shell_external_access_is_read_only(command: str) -> bool:
    if re.search(r"[;&|`]|\$\(", command):
        return False
    try:
        tokens = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return False
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    return executable in {
        "cat",
        "cmp",
        "diff",
        "file",
        "grep",
        "head",
        "less",
        "more",
        "rg",
        "sed",
        "sha256sum",
        "shasum",
        "stat",
        "tail",
        "wc",
    }


def _tool_external_access_is_read_only(tool_name: str) -> bool:
    return not re.search(
        r"(?:^|[_:.\-])(?:eval|execute|invoke|run)(?:$|[_:.\-])",
        tool_name,
        re.IGNORECASE,
    ) and bool(
        re.search(
            r"(?:^|[_:.\-])(?:find|get|hash|inspect|list|read|search|stat|view)"
            r"(?:$|[_:.\-])",
            tool_name,
            re.IGNORECASE,
        )
    ) and not _tool_mutates(tool_name)


def _authorize(
    event: dict[str, Any], state_root: Path, *, now: datetime
) -> dict[str, Any]:
    receipt = _load_receipt(event, state_root, now=now)
    if receipt is None:
        return _deny("Manageroo operator action has no valid current-turn scope receipt.")
    if receipt.get("active") is False:
        current_cwd = Path(str(event.get("cwd") or ".")).resolve(strict=False)
        tool_name = str(event.get("tool_name") or "")
        tool_input = event.get("tool_input")
        paths = _structured_tool_paths(tool_input, current_cwd)
        if tool_name in {"Bash", "exec_command", "shell", "functions.exec"}:
            paths.extend(_command_paths(_shell_command(tool_input), current_cwd))
        if _belongs_to_git_repository(current_cwd) or any(
            _belongs_to_git_repository(path) for path in paths
        ):
            return _deny(
                "Manageroo denied access to an unnamed repository; submit a current request from or naming that repository."
            )
        return {}
    if receipt.get("active") is not True:
        return _deny("Manageroo operator action has no valid current-turn scope receipt.")
    try:
        locked_root = Path(str(receipt["repo_root"])).resolve(strict=True)
        current_root = _repo_root(Path(str(event.get("cwd") or ".")))
    except (KeyError, OSError, ValueError):
        return _deny("Manageroo operator scope receipt does not match a current repository.")
    if current_root != locked_root:
        return _deny("Manageroo denied an action outside locked repository scope.")
    try:
        current_common = _git_common_directory(current_root)
        identity_matches = (
            receipt.get("repo_identity") == _path_identity(current_root)
            and receipt.get("git_common_dir") == str(current_common)
            and receipt.get("git_common_identity") == _path_identity(current_common)
        )
    except (OSError, UnicodeDecodeError, ValueError):
        identity_matches = False
    if not identity_matches:
        return _deny("Manageroo denied the action because repository identity changed.")

    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    allowed_actions = receipt.get("allowed_actions")
    if not isinstance(allowed_actions, list) or any(
        not isinstance(action, str) for action in allowed_actions
    ):
        return _deny("Manageroo operator action has no valid current-turn scope receipt.")
    if tool_name == "apply_patch":
        if receipt.get("controlled_run_required") is True:
            return _deny(
                "The explicit Manageroo request requires a controlled Manageroo run; freehand apply_patch edits are not authorized."
            )
        patch_command = (
            str(tool_input.get("command") or "")
            if isinstance(tool_input, dict)
            else ""
        )
        patch_paths = _patch_paths(patch_command, locked_root)
        if not patch_paths:
            return _deny("Manageroo could not prove the apply_patch target paths.")
        temporary_only = _private_temporary_paths_only(patch_paths, receipt)
        if "mutate" not in allowed_actions and not temporary_only:
            return _deny("The current locked request does not authorize mutation.")
        if any(
            not _inside(path, locked_root)
            and not _external_write_allowed(path, receipt)
            for path in patch_paths
        ):
            return _deny("Manageroo denied an action outside locked repository scope.")
        if any(
            _inside(path, locked_root) and not _path_is_allowed(path, receipt)
            for path in patch_paths
        ):
            return _deny("Manageroo denied a mutation outside the current request's allowed paths.")
        if (
            "*** Delete File:" in patch_command
            and "delete" not in allowed_actions
            and not temporary_only
        ):
            return _deny("The current locked request does not authorize delete.")
    if receipt.get("controlled_run_required") is True and tool_name in {
        "write_stdin",
        "functions.write_stdin",
    }:
        chars = tool_input.get("chars") if isinstance(tool_input, dict) else None
        if chars not in {None, ""}:
            return _deny(
                "The agent cannot interrupt or steer the controlled Manageroo process."
            )
        return {}
    if receipt.get("controlled_run_required") is True and tool_name in {
        "wait",
        "functions.wait",
    }:
        return {}
    shell_tool = tool_name in {"Bash", "exec_command", "shell", "functions.exec"}
    if shell_tool:
        command = _shell_command(tool_input)
        if reason := _unprovable_shell_reason(command):
            return _deny(f"Manageroo cannot prove shell command scope: {reason}.")
        required_shell_actions = _required_shell_actions(command)
        try:
            shell_tokens = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            shell_tokens = []
        is_manageroo_command = bool(
            shell_tokens and Path(shell_tokens[0]).name.lower() == "manageroo"
        )
        manageroo_subcommand = (
            shell_tokens[1] if is_manageroo_command and len(shell_tokens) > 1 else ""
        )
        command_paths = _command_paths(command, current_root)
        instruction_read = bool(
            command_paths
            and _shell_external_access_is_read_only(command)
            and all(_instruction_read_allowed(path, receipt) for path in command_paths)
        )
        if (
            receipt.get("controlled_run_required") is True
            and not _controlled_shell_allowed(shell_tokens)
            and not instruction_read
        ):
            return _deny(
                "The explicit Manageroo request requires a controlled Manageroo run; freehand search or execution is not authorized."
            )
        controlled_run = (
            receipt.get("controlled_run_required") is True
            and manageroo_subcommand == "run"
        )
        if (
            receipt.get("controlled_run_required") is True
            and manageroo_subcommand == "operator-exec"
        ):
            return _deny(
                "A controlled Manageroo request cannot use operator-exec; implementation must pass through manageroo run."
            )
        if controlled_run and any(
            token == "--operator-receipt" or token.startswith("--operator-receipt=")
            for token in shell_tokens[2:]
        ):
            return _deny("The agent cannot supply or replace the signed operator receipt.")
        temporary_support = _private_temporary_paths_only(command_paths, receipt)
        for action in required_shell_actions:
            if controlled_run and action == "mutate":
                continue
            if temporary_support and action in {"mutate", "delete"}:
                continue
            if action not in allowed_actions:
                label = "mutation" if action == "mutate" else action
                return _deny(f"The current locked request does not authorize {label}.")
        if (
            receipt.get("controlled_run_required") is True
            and not is_manageroo_command
            and any(action in {"mutate", "delete"} for action in required_shell_actions)
        ):
            return _deny(
                "The explicit Manageroo request requires a controlled Manageroo run; freehand shell mutations are not authorized."
            )
        external_paths = [path for path in command_paths if not _inside(path, locked_root)]
        if any(
            not _external_read_allowed(path, receipt)
            and not _external_write_allowed(path, receipt)
            and not _instruction_read_allowed(path, receipt)
            for path in external_paths
        ):
            return _deny("Manageroo denied an action outside locked repository scope.")
        if external_paths:
            command_mutates = any(
                action in required_shell_actions for action in ("mutate", "delete")
            )
            if (
                (command_mutates or not _shell_external_access_is_read_only(command))
                and any(
                    not _external_write_allowed(path, receipt)
                    and not _instruction_read_allowed(path, receipt)
                    for path in external_paths
                )
            ):
                return _deny("Manageroo external source paths are read-only.")
        if required_shell_actions and any(
            _inside(path, locked_root) and not _path_is_allowed(path, receipt)
            for path in command_paths
        ):
            return _deny("Manageroo denied a mutation outside the current request's allowed paths.")
        if not _direct_shell_is_provable(command):
            return _deny(
                "Manageroo cannot prove this direct command's effects. Run it through "
                f"`manageroo operator-exec --repo {locked_root} -- COMMAND ...` so the OS sandbox locks writes to the repo."
            )
        if controlled_run:
            receipt_path = _receipt_path(state_root, str(receipt["session_id"]))
            try:
                _mark_controlled_run_started(receipt, state_root, now=now)
            except (ConfigurationError, OSError, ValueError) as exc:
                return _deny(f"Manageroo could not bind the controlled run: {exc}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": {
                        "command": shlex.join(
                            [*shell_tokens, "--operator-receipt", str(receipt_path)]
                        )
                    },
                }
            }
    if tool_name != "apply_patch" and not shell_tool:
        structured_paths = _structured_tool_paths(tool_input, current_root)
        instruction_read = bool(
            structured_paths
            and _tool_external_access_is_read_only(tool_name)
            and all(_instruction_read_allowed(path, receipt) for path in structured_paths)
        )
        if receipt.get("controlled_run_required") is True and not instruction_read:
            return _deny(
                "The explicit Manageroo request requires a controlled Manageroo run; alternate read or mutation tools are not authorized."
            )
        for action in _required_tool_actions(tool_name):
            if action not in allowed_actions:
                return _deny(f"The current locked request does not authorize {action}.")
        if _tool_mutates(tool_name) and "mutate" not in allowed_actions:
            return _deny("The current locked request does not authorize mutation.")
        if receipt.get("controlled_run_required") is True and _tool_mutates(tool_name):
            return _deny(
                "The explicit Manageroo request requires a controlled Manageroo run; freehand mutation tools are not authorized."
            )
        if _tool_deletes(tool_name) and "delete" not in allowed_actions:
            return _deny("The current locked request does not authorize delete.")
        for path in structured_paths:
            if (
                not _inside(path, locked_root)
                and not _external_read_allowed(path, receipt)
                and not _external_write_allowed(path, receipt)
                and not _instruction_read_allowed(path, receipt)
            ):
                return _deny("Manageroo denied an action outside locked repository scope.")
            if (
                not _inside(path, locked_root)
                and not _tool_external_access_is_read_only(tool_name)
                and not _external_write_allowed(path, receipt)
            ):
                return _deny("Manageroo external source paths are read-only.")
    return {}


def process_codex_hook(
    event: dict[str, Any],
    *,
    state_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = _prepare_state_root(state_root or operator_scope_state_root())
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("Operator-scope clock must be timezone-aware")
    name = str(event.get("hook_event_name") or "")
    if name == "UserPromptSubmit":
        return _capture(event, root, now=current_time)
    if name == "PreToolUse":
        return _authorize(event, root, now=current_time)
    if name == "Stop":
        return _authorize_stop(event, root, now=current_time)
    return {}


def _manageroo_hook_group(group: object) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    return isinstance(handlers, list) and any(
        isinstance(handler, dict)
        and _HOOK_COMMAND_TOKEN in str(handler.get("command") or "")
        for handler in handlers
    )


def install_codex_operator_hooks(
    *, codex_home: Path, manageroo_command: Path
) -> dict[str, Any]:
    lexical_home = codex_home.expanduser().absolute()
    lexical_home.mkdir(parents=True, exist_ok=True)
    if lexical_home.is_symlink() or not lexical_home.is_dir():
        raise ConfigurationError(f"Codex home is not a safe directory: {lexical_home}")
    home = lexical_home.resolve(strict=True)
    hooks_path = home / "hooks.json"
    lock_directory = home / "cache"
    lock_directory.mkdir(mode=0o700, exist_ok=True)
    lock_state = lock_directory.lstat()
    if stat.S_ISLNK(lock_state.st_mode) or not stat.S_ISDIR(lock_state.st_mode):
        raise ConfigurationError(f"Codex config lock directory is unsafe: {lock_directory}")
    if os.name != "nt":
        if hasattr(os, "getuid") and lock_state.st_uid != os.getuid():
            raise ConfigurationError(f"Codex config lock directory has the wrong owner: {lock_directory}")
        os.chmod(lock_directory, 0o700)
    manageroo = manageroo_command.expanduser().resolve(strict=False)
    command = shlex.join([str(manageroo), _HOOK_COMMAND_TOKEN])
    command_windows = subprocess.list2cmdline([str(manageroo), _HOOK_COMMAND_TOKEN])
    handler = {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": 10,
        "statusMessage": "Checking Manageroo operator scope",
    }
    additions = {
        "UserPromptSubmit": {"hooks": [handler]},
        "PreToolUse": {"matcher": "*", "hooks": [handler]},
        "Stop": {"hooks": [handler]},
    }

    with config_mutation_lock(hooks_path):
        if hooks_path.is_symlink():
            raise ConfigurationError(f"Refusing symlinked Codex hooks file: {hooks_path}")
        if hooks_path.exists():
            hook_state = hooks_path.stat()
            if not stat.S_ISREG(hook_state.st_mode) or hook_state.st_nlink != 1:
                raise ConfigurationError(f"Codex hooks file is not a private regular file: {hooks_path}")
            try:
                payload = json.loads(hooks_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConfigurationError(f"Cannot safely merge Codex hooks: {exc}") from exc
        else:
            payload = {}
        if not isinstance(payload, dict):
            raise ConfigurationError("Codex hooks file must contain a JSON object")
        before = canonical_json_bytes(payload)
        hooks = payload.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ConfigurationError("Codex hooks field must contain a JSON object")
        for event, addition in additions.items():
            groups = hooks.setdefault(event, [])
            if not isinstance(groups, list):
                raise ConfigurationError(f"Codex hook event {event} must contain an array")
            hooks[event] = [group for group in groups if not _manageroo_hook_group(group)]
            hooks[event].append(addition)
        changed = before != canonical_json_bytes(payload)
        if changed:
            atomic_write_json(hooks_path, payload)
    return {
        "ok": True,
        "path": str(hooks_path),
        "changed": changed,
        "trust_required": changed,
        "next": "/hooks" if changed else "",
    }


def run_codex_operator_scope_hook(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
    state_root: Path | None = None,
) -> int:
    try:
        event = json.load(input_stream)
        if not isinstance(event, dict):
            raise ValueError("Codex hook input must be a JSON object")
        result = process_codex_hook(event, state_root=state_root)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"Manageroo operator scope failed closed: {exc}", file=error_stream)
        return 2
    if result:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False), file=output_stream)
    return 0
