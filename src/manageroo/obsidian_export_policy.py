from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .errors import SafetyError
from .util import safe_repo_relative


def install_obsidian_export_policy(integrations_module: Any) -> None:
    """Enable the existing descriptor-safe export algorithm on supported macOS hosts."""

    integration_class = integrations_module.ObsidianIntegration
    if getattr(integration_class, "_manageroo_portable_export_installed", False):
        return
    original_export = integration_class.export

    def export(self: Any, filename: str, markdown: str) -> Path | None:
        # Linux keeps the openat2-enforced implementation and its existing tests.
        # Native Windows is intentionally unsupported by the secure artifact backend.
        if integrations_module.platform.system() != "Darwin":
            return original_export(self, filename, markdown)
        if not self.vault or not self.vault.is_dir():
            return None
        if not integrations_module._descriptor_export_supported():
            raise SafetyError(
                "Obsidian export requires descriptor-relative no-follow filesystem access."
            )

        export_relative = safe_repo_relative(self.export_folder)
        filename_relative = safe_repo_relative(filename)
        try:
            vault_fd = integrations_module.os.open(
                self.vault, integrations_module._directory_flags()
            )
        except OSError as exc:
            raise SafetyError("Configured Obsidian vault is not a safe directory.") from exc

        export_fd: int | None = None
        destination_parent_fd: int | None = None
        try:
            vault_state = integrations_module.os.fstat(vault_fd)
            export_fd = integrations_module._open_safe_directory_chain(
                vault_fd, export_relative
            )
            parent_relative = str(Path(filename_relative).parent)
            destination_parent_fd = integrations_module._open_safe_directory_chain(
                export_fd, parent_relative
            )
            integrations_module.os.close(destination_parent_fd)
            destination_parent_fd = None

            destination_name = Path(filename_relative).name
            destination_parent_relative = str(
                Path(export_relative) / Path(parent_relative)
            )
            destination_relative = str(
                Path(destination_parent_relative) / destination_name
            )
            written_state = integrations_module._write_text_beneath(
                vault_fd, destination_relative, markdown
            )

            current_vault = integrations_module.os.stat(
                self.vault, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(current_vault.st_mode)
                or not integrations_module._same_filesystem_object(
                    vault_state, current_vault
                )
            ):
                raise SafetyError("Configured Obsidian vault changed during export.")

            current_parent_fd = integrations_module._open_safe_directory_chain(
                vault_fd, destination_parent_relative
            )
            verification_fd: int | None = None
            try:
                try:
                    verification_fd = integrations_module._open_beneath(
                        vault_fd,
                        destination_relative,
                        os.O_RDONLY
                        | os.O_NOFOLLOW
                        | getattr(os, "O_CLOEXEC", 0),
                    )
                except OSError as exc:
                    raise SafetyError(
                        "Obsidian export destination changed during export."
                    ) from exc
                destination_state = integrations_module.os.fstat(verification_fd)
                if (
                    not stat.S_ISREG(destination_state.st_mode)
                    or destination_state.st_nlink != 1
                    or not integrations_module._same_filesystem_object(
                        written_state, destination_state
                    )
                ):
                    raise SafetyError(
                        "Obsidian export destination changed during export."
                    )
            finally:
                if verification_fd is not None:
                    integrations_module.os.close(verification_fd)
                integrations_module.os.close(current_parent_fd)
            return self.vault / export_relative / filename_relative
        finally:
            if destination_parent_fd is not None:
                integrations_module.os.close(destination_parent_fd)
            if export_fd is not None:
                integrations_module.os.close(export_fd)
            integrations_module.os.close(vault_fd)

    integration_class.export = export
    integration_class._manageroo_portable_export_installed = True
