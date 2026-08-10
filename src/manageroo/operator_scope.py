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


RECEIPT_SCHEMA_VERSION = 1
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])(/[A-Za-z0-9._~+@%:,=/-]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]:[\\/][^\s'\"`;|&]+)")
_CLAUSE_BOUNDARY = re.compile(r"[.!?;:\n]")
_NEGATED_ACTION = re.compile(
    r"\b(?:do\s+not|don't|never|must\s+not|mustn't|without|not\s+authorized\s+to)\b",
    re.IGNORECASE,
)
_ACTION_PATTERNS = {
    "mutate": re.compile(
        r"\b(?:build|change|clean\s*up|configure|create|delete|edit|fix|implement|"
        r"finish|install|move|patch|publish|rebuild|release|remove|repair|restore|"
        r"ship|update|write)\b|\bmake\s+it\s+live\b",
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
            r"(?:^|[;&|]\s*)(?:vercel|netlify\s+deploy|fly\s+deploy|"
            r"kubectl\s+(?:apply|create|replace)|gh\s+release\s+create)(?:\s|$)"
        ),
    ),
    (
        "install",
        re.compile(
            r"(?:^|[;&|]\s*)(?:pipx?|python\d*(?:\.\d+)?\s+-m\s+pip|npm|pnpm|"
            r"yarn|bun|cargo)\s+(?:install|add)(?:\s|$)"
        ),
    ),
    ("delete", re.compile(r"(?:^|[;&|]\s*)(?:rm|rmdir|unlink)(?:\s|$)")),
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
)
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
    re.MULTILINE,
)
_HOOK_COMMAND_TOKEN = "operator-scope-hook"


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


def _action_is_explicit(prompt: str, pattern: re.Pattern[str]) -> bool:
    for match in pattern.finditer(prompt):
        clause_start = 0
        for boundary in _CLAUSE_BOUNDARY.finditer(prompt, 0, match.start()):
            clause_start = boundary.end()
        if not _NEGATED_ACTION.search(prompt[clause_start : match.start()]):
            return True
    return False


def _allowed_actions(prompt: str) -> list[str]:
    actions = ["read"]
    for action, pattern in _ACTION_PATTERNS.items():
        if _action_is_explicit(prompt, pattern):
            actions.append(action)
    return actions


def _repo_root(cwd: Path) -> Path:
    current = cwd.expanduser().resolve(strict=True)
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate.resolve(strict=True)
    raise ValueError(f"No Git repository contains Codex cwd: {cwd}")


def _path_identity(path: Path) -> dict[str, int]:
    path_state = path.stat()
    return {"device": path_state.st_dev, "inode": path_state.st_ino}


def _named_external_read_paths(prompt: str, repo: Path) -> list[dict[str, Any]]:
    values = [match.group(1) for match in _ABSOLUTE_POSIX_PATH.finditer(prompt)]
    values.extend(match.group(1) for match in _ABSOLUTE_WINDOWS_PATH.finditer(prompt))
    entries: list[dict[str, Any]] = []
    for value in values:
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
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "active": True,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "session_id": session_id,
        "turn_id": turn_id,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "repo_root": str(repo),
        "repo_identity": _path_identity(repo),
        "git_common_dir": str(common_dir),
        "git_common_identity": _path_identity(common_dir),
        "allowed_paths": [str(repo)],
        "allowed_external_reads": _named_external_read_paths(prompt, repo),
        "allowed_actions": _allowed_actions(prompt),
    }
    receipt["signature"] = _sign_receipt(receipt, _authority_key(state_root, create=True))
    path = _receipt_path(state_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    atomic_write_json(path, receipt)
    return {}


def _load_receipt(
    event: dict[str, Any], state_root: Path, *, now: datetime
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
    if receipt.get("session_id") != session_id or receipt.get("turn_id") != turn_id:
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
    return list(dict.fromkeys(
        action
        for action, pattern in _SHELL_ACTION_PATTERNS
        if pattern.search(normalized)
    ))


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
            r"(?:^|[_:.\-])(?:add|apply|copy|create|delete|deploy|edit|install|"
            r"move|patch|publish|push|remove|rename|replace|update|upload|write)"
            r"(?:$|[_:.\-])",
            tool_name,
            re.IGNORECASE,
        )
    )


def _tool_deletes(tool_name: str) -> bool:
    return bool(re.search(r"(?:delete|remove|unlink)", tool_name, re.IGNORECASE))


def _shell_command(tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "cmd", "code"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


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
        if "mutate" not in allowed_actions:
            return _deny("The current locked request does not authorize mutation.")
        patch_command = (
            str(tool_input.get("command") or "")
            if isinstance(tool_input, dict)
            else ""
        )
        patch_paths = _patch_paths(patch_command, locked_root)
        if not patch_paths:
            return _deny("Manageroo could not prove the apply_patch target paths.")
        if any(not _inside(path, locked_root) for path in patch_paths):
            return _deny("Manageroo denied an action outside locked repository scope.")
        if "*** Delete File:" in patch_command and "delete" not in allowed_actions:
            return _deny("The current locked request does not authorize delete.")
    shell_tool = tool_name in {"Bash", "exec_command", "shell", "functions.exec"}
    if shell_tool:
        command = _shell_command(tool_input)
        for action in _required_shell_actions(command):
            if action not in allowed_actions:
                label = "mutation" if action == "mutate" else action
                return _deny(f"The current locked request does not authorize {label}.")
        command_paths = _command_paths(command, current_root)
        if any(
            not _inside(path, locked_root)
            and not _external_read_allowed(path, receipt)
            for path in command_paths
        ):
            return _deny("Manageroo denied an action outside locked repository scope.")
        if any(not _inside(path, locked_root) for path in command_paths):
            if not _shell_external_access_is_read_only(command) or any(
                action in _required_shell_actions(command) for action in ("mutate", "delete")
            ):
                return _deny("Manageroo external source paths are read-only.")
    if tool_name != "apply_patch" and not shell_tool:
        if _tool_mutates(tool_name) and "mutate" not in allowed_actions:
            return _deny("The current locked request does not authorize mutation.")
        if _tool_deletes(tool_name) and "delete" not in allowed_actions:
            return _deny("The current locked request does not authorize delete.")
        for path in _structured_tool_paths(tool_input, current_root):
            if not _inside(path, locked_root) and not _external_read_allowed(path, receipt):
                return _deny("Manageroo denied an action outside locked repository scope.")
            if not _inside(path, locked_root) and not _tool_external_access_is_read_only(tool_name):
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
