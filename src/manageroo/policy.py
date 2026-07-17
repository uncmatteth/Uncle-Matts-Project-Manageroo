from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .branding import PROJECT_DIR
from .errors import SafetyError
from .util import safe_repo_relative


FORBIDDEN_SCOPE_PATTERNS = (
    ".git/**",
    f"{PROJECT_DIR}/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/*secret*",
    "**/*credential*",
)


def validate_allowed_scope_patterns(patterns: Iterable[str]) -> list[str]:
    """Validate locked plan/edit scopes before any worker can use them."""
    accepted: list[str] = []
    broad = {"*", "**", "**/*"}
    for raw in patterns:
        raw_text = str(raw).strip().replace("\\", "/")
        if raw_text.endswith("/"):
            raise SafetyError(f"Allowed scope must be a file path, not a directory: {raw!r}")
        try:
            path = safe_repo_relative(raw_text)
        except SafetyError:
            raise
        if path in {".", ""} or str(raw).strip() in {"/", "\\"}:
            raise SafetyError(f"Allowed scope must be an exact task-owned file path: {raw!r}")
        if path in broad or "*" in path or "?" in path or "[" in path or "]" in path:
            raise SafetyError(f"Allowed scope is too broad: {raw!r}")
        if any(fnmatch.fnmatch(path, pattern) for pattern in FORBIDDEN_SCOPE_PATTERNS):
            raise SafetyError(f"Allowed scope points at a forbidden path: {path}")
        accepted.append(path)
    if not accepted:
        raise SafetyError("Allowed scope cannot be empty.")
    return accepted


@dataclass(frozen=True)
class ScopePolicy:
    allowed: tuple[str, ...]
    forbidden: tuple[str, ...] = FORBIDDEN_SCOPE_PATTERNS

    def _matches(self, path: str, patterns: Iterable[str]) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)

    def validate_paths(self, changed_paths: Iterable[str]) -> list[str]:
        violations: list[str] = []
        for raw in changed_paths:
            path = safe_repo_relative(raw)
            if self._matches(path, self.forbidden):
                violations.append(f"{path}: forbidden")
                continue
            if self.allowed and not self._matches(path, self.allowed):
                violations.append(f"{path}: outside approved scope")
        if violations:
            raise SafetyError("Scope policy violation:\n" + "\n".join(violations))
        return list(changed_paths)


@dataclass(frozen=True)
class CommandPolicy:
    allowed_programs: tuple[str, ...]

    def validate(self, argv: list[str]) -> None:
        if not argv:
            raise SafetyError("Empty command.")

        raw_program = argv[0]
        program_path = Path(raw_program)
        program = program_path.name
        allowed_raw = set(self.allowed_programs)
        allowed_names = {Path(item).name for item in self.allowed_programs}
        python_family_allowed = any(item.startswith("python") for item in allowed_names)

        # A bare allowlist entry such as "python" must not implicitly trust an
        # arbitrary path-qualified executable such as /tmp/python. Exact paths
        # remain supported when the operator explicitly allowlists that path.
        if program_path.parent != Path(".") and raw_program not in allowed_raw:
            raise SafetyError(
                f"Path-qualified command must be explicitly allowlisted: {raw_program}"
            )

        if program not in allowed_names and not (
            python_family_allowed and program.startswith("python") and raw_program == program
        ):
            raise SafetyError(f"Command program is not allowlisted: {program}")

        dangerous = {"sudo", "su", "rm", "shutdown", "reboot", "mkfs", "dd"}
        if program in dangerous:
            raise SafetyError(f"Dangerous command is forbidden: {program}")
