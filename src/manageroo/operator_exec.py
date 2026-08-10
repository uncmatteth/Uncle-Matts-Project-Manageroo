from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import ConfigurationError
from .project import git_root


def operator_exec(repo_path: Path, command: list[str]) -> int:
    """Run an opaque command in Codex's native workspace-only OS sandbox."""
    repo = git_root(repo_path)
    if not command:
        raise ConfigurationError("operator-exec requires a command after `--`.")
    if Path(command[0]).name.lower() == "manageroo" and len(command) > 1 and command[1] == "operator-exec":
        raise ConfigurationError("Nested manageroo operator-exec commands are not allowed.")
    codex = shutil.which("codex")
    if not codex:
        raise ConfigurationError(
            "operator-exec requires the local Codex CLI because its native OS sandbox is the enforcement boundary."
        )
    argv = [
        codex,
        "sandbox",
        "--permission-profile",
        ":workspace",
        "-C",
        str(repo),
        "--",
        *command,
    ]
    completed = subprocess.run(argv, cwd=repo, check=False)
    return int(completed.returncode)
