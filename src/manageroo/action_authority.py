from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import load_config
from .errors import ConfigurationError


READ_ONLY_PERMISSION_MODES = frozenset({"read-only", "read_only", "readonly"})


@dataclass(frozen=True)
class ActionAuthority:
    source: str
    detail: str

    @property
    def authorized(self) -> bool:
        return self.source != "unbound"


def _argv(command: str) -> list[str] | None:
    if any(token in command for token in ("\n", ";", "&&", "||", "|", ">", "<", "`", "$(")):
        return None
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return None


def _resolved_program(raw: str) -> Path | None:
    requested = Path(raw).expanduser()
    try:
        if requested.parent != Path("."):
            return requested.resolve(strict=False)
        discovered = shutil.which(raw)
        return Path(discovered).resolve(strict=False) if discovered else None
    except OSError:
        return None


def _installed_program(argv: list[str], name: str) -> bool:
    if not argv:
        return False
    installed = shutil.which(name)
    if not installed:
        return False
    try:
        return _resolved_program(argv[0]) == Path(installed).resolve(strict=False)
    except OSError:
        return False


def _configured_gate_argv(repo: Path) -> list[list[str]]:
    if not (repo / ".manageroo" / "config.toml").is_file():
        return []
    try:
        config = load_config(repo)
    except (OSError, ValueError, ConfigurationError):
        return []
    gates = config.get("verification", {}).get("gates", [])
    return [
        [str(value) for value in gate.get("argv", [])]
        for gate in gates
        if isinstance(gate, dict) and isinstance(gate.get("argv"), list)
    ]


def _normalized_brief(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def _resolve_from(cwd: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (cwd / path).resolve(strict=False) if not path.is_absolute() else path.resolve(strict=False)


def _is_controller_entry(
    argv: list[str],
    *,
    cwd: Path,
    repo: Path | None,
    operator_brief: str,
) -> bool:
    if len(argv) < 4 or repo is None or not _installed_program(argv, "manageroo"):
        return False
    if argv[1] != "run" or not operator_brief.strip():
        return False
    brief_path: Path | None = None
    requested_repo = repo
    index = 2
    while index < len(argv):
        option = argv[index]
        if option in {"--apply", "--no-apply", "--json"}:
            index += 1
            continue
        if option in {"--brief", "--repo", "--mode"}:
            if index + 1 >= len(argv):
                return False
            value = argv[index + 1]
            if option == "--brief":
                if brief_path is not None:
                    return False
                brief_path = _resolve_from(cwd, value)
            elif option == "--repo":
                requested_repo = _resolve_from(cwd, value)
            elif value not in {"build", "repair"}:
                return False
            index += 2
            continue
        return False
    if requested_repo != repo or brief_path is None or not brief_path.is_file():
        return False
    try:
        if brief_path.stat().st_size > 1_000_000:
            return False
        supplied_brief = brief_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _normalized_brief(supplied_brief) == _normalized_brief(operator_brief)


def _is_read_only_sandbox_entry(argv: list[str]) -> bool:
    if len(argv) < 6 or not _installed_program(argv, "codex") or argv[1] != "sandbox":
        return False
    try:
        separator = argv.index("--", 2)
    except ValueError:
        return False
    if separator == len(argv) - 1:
        return False
    index = 2
    profile_count = 0
    while index < separator:
        option = argv[index]
        if option in {"-P", "--permission-profile"}:
            if index + 1 >= separator or argv[index + 1] != ":read-only":
                return False
            profile_count += 1
            index += 2
            continue
        if option in {"-C", "--cd"}:
            if index + 1 >= separator:
                return False
            index += 2
            continue
        return False
    return profile_count == 1


def authorize_shell_action(
    command: str,
    *,
    cwd: Path,
    repo: Path | None,
    operator_brief: str,
    permission_mode: str = "",
) -> ActionAuthority:
    """Bind action authority without reading agent-authored prose.

    The host sandbox, an exact configured proof gate, or Manageroo's controlled
    executor owns the action. Everything else remains unbound.
    """

    if permission_mode.casefold() in READ_ONLY_PERMISSION_MODES:
        return ActionAuthority("host-read-only", "the host already enforces read-only execution")
    argv = _argv(command)
    if argv is None:
        return ActionAuthority("unbound", "raw shell composition has no controller-owned authority")
    if _is_read_only_sandbox_entry(argv):
        return ActionAuthority("sandbox", "Codex's built-in read-only profile owns the execution")
    if _is_controller_entry(
        argv,
        cwd=cwd,
        repo=repo,
        operator_brief=operator_brief,
    ):
        return ActionAuthority(
            "controller",
            "Manageroo owns the side effect under the verbatim operator brief",
        )
    if repo is not None and argv in _configured_gate_argv(repo):
        return ActionAuthority("proof", "command exactly matches a configured proof gate")
    return ActionAuthority("unbound", "no operator-authorized action contract owns this side effect")
