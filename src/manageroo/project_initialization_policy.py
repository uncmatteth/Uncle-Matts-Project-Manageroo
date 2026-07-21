from __future__ import annotations

from pathlib import Path
from typing import Any


def install_project_initialization_policy(project_module: Any) -> None:
    if getattr(project_module, "_manageroo_project_initialization_policy_installed", False):
        return
    original_atomic_write_text = project_module.atomic_write_text

    def preserving_write(path: Path, text: str) -> None:
        normalized = path.as_posix()
        managed_skill_suffix = "/.agents/skills/uncle-matts-project-manageroo/SKILL.md"
        if normalized.endswith(managed_skill_suffix) and path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Refusing to overwrite unsafe repository-local Manageroo skill: {path}")
            # Repository-local skill edits belong to the repository owner. Initialization
            # installs the packaged skill only when no local copy exists.
            return
        original_atomic_write_text(path, text)

    project_module.atomic_write_text = preserving_write
    project_module._manageroo_project_initialization_policy_installed = True
