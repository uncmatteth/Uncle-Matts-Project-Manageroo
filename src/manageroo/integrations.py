from __future__ import annotations

import ctypes
import errno
import os
import platform
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Iterable

from .errors import SafetyError
from .runner import CommandRunner
from .util import safe_repo_relative


MAX_EXTERNAL_TEXT_CHARS = 12_000
_OPENAT2_RESOLVE_NO_MAGICLINKS = 0x02
_OPENAT2_RESOLVE_NO_SYMLINKS = 0x04
_OPENAT2_RESOLVE_BENEATH = 0x08


class _OpenHow(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    ]


def _terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[a-zA-Z0-9_-]{3,}", query)}


def _descriptor_export_supported() -> bool:
    return (
        _descriptor_relative_open_supported()
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.unlink in os.supports_dir_fd
    )


def _descriptor_relative_open_supported() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
    )


def _openat2_syscall_number() -> int | None:
    if os.name != "posix" or platform.system() != "Linux":
        return None
    machine = platform.machine().lower()
    if machine in {
        "aarch64",
        "arm64",
        "i386",
        "i686",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390x",
        "x86_64",
    }:
        return 437
    return None


def _open_beneath(root_fd: int, relative: str, flags: int, mode: int = 0) -> int:
    syscall_number = _openat2_syscall_number()
    if syscall_number is None:
        if not _descriptor_relative_open_supported():
            raise OSError(errno.ENOSYS, "descriptor-relative open is unavailable")
        safe_relative = safe_repo_relative(relative)
        parts = PurePosixPath(safe_relative).parts
        current_fd = os.dup(root_fd)
        try:
            directory_flags = (
                os.O_RDONLY
                | os.O_DIRECTORY
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0)
            )
            for part in parts[:-1]:
                child_fd = os.open(part, directory_flags, dir_fd=current_fd)
                child_state = os.fstat(child_fd)
                if not stat.S_ISDIR(child_state.st_mode):
                    os.close(child_fd)
                    raise OSError(errno.ENOTDIR, "path component is not a directory", part)
                os.close(current_fd)
                current_fd = child_fd
            return os.open(parts[-1], flags, mode, dir_fd=current_fd)
        finally:
            os.close(current_fd)
    how = _OpenHow(
        flags=flags,
        mode=mode,
        resolve=(
            _OPENAT2_RESOLVE_BENEATH
            | _OPENAT2_RESOLVE_NO_MAGICLINKS
            | _OPENAT2_RESOLVE_NO_SYMLINKS
        ),
    )
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        ctypes.c_long(syscall_number),
        ctypes.c_int(root_fd),
        ctypes.c_char_p(os.fsencode(relative)),
        ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    )
    if result < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), relative)
    return int(result)


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _require_owner_only_mutable_directory(directory_fd: int) -> None:
    state = os.fstat(directory_fd)
    effective_uid = getattr(os, "geteuid", lambda: -1)()
    group_is_private = True
    if state.st_mode & 0o020:
        try:
            import grp
            import pwd

            current_name = pwd.getpwuid(effective_uid).pw_name
            group = grp.getgrgid(state.st_gid)
            group_users = set(group.gr_mem)
            group_users.update(
                entry.pw_name for entry in pwd.getpwall() if entry.pw_gid == state.st_gid
            )
            group_is_private = group_users <= {current_name}
        except (ImportError, KeyError):
            group_is_private = False
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != effective_uid
        or state.st_mode & 0o002
        or not group_is_private
    ):
        raise SafetyError(
            "Obsidian vault and export directories must be owned by the current "
            "user and not writable by another account."
        )


def _open_safe_directory_chain(
    root_fd: int,
    relative: str,
) -> int:
    current_fd = os.dup(root_fd)
    keep_open = False
    try:
        _require_owner_only_mutable_directory(current_fd)
        for part in Path(relative).parts:
            child_fd = os.open(part, _directory_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = child_fd
            _require_owner_only_mutable_directory(current_fd)
        keep_open = True
        return current_fd
    except OSError as exc:
        raise SafetyError(
            f"Obsidian export directory is not a safe real directory: {relative!r}"
        ) from exc
    finally:
        if not keep_open:
            os.close(current_fd)


def _same_filesystem_object(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _write_text_beneath(
    root_fd: int,
    relative: str,
    text: str,
) -> os.stat_result:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = _open_beneath(root_fd, relative, flags, 0o600)
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
            raise SafetyError(f"Refusing unsafe Obsidian export: {relative}")
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            written_state = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(written_state.st_mode)
                or written_state.st_nlink != 1
                or not _same_filesystem_object(state, written_state)
            ):
                raise SafetyError("Obsidian export file changed during write.")
            return written_state
    except OSError as exc:
        raise SafetyError(
            f"Obsidian export destination is not safely beneath the vault: {relative!r}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_text_beneath(root_fd: int, relative: str) -> str:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    verification_fd: int | None = None
    try:
        descriptor = _open_beneath(root_fd, relative, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SafetyError(f"Refusing to read unsafe Obsidian note: {relative}")
        chunks: list[bytes] = []
        while block := os.read(descriptor, 1024 * 1024):
            chunks.append(block)
        after = os.fstat(descriptor)
        if (
            after.st_nlink != 1
            or not _same_filesystem_object(before, after)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise SafetyError(f"Obsidian note changed during read: {relative}")
        verification_fd = _open_beneath(root_fd, relative, flags)
        current = os.fstat(verification_fd)
        if current.st_nlink != 1 or not _same_filesystem_object(after, current):
            raise SafetyError(f"Obsidian note changed during read: {relative}")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError as exc:
        raise SafetyError(
            f"Obsidian note is not safely beneath the vault: {relative!r}"
        ) from exc
    finally:
        if verification_fd is not None:
            os.close(verification_fd)
        if descriptor is not None:
            os.close(descriptor)

class ObsidianIntegration:
    """Reads/writes plain Markdown. Obsidian itself is not required."""

    def __init__(self, vault: str, export_folder: str):
        self.vault = Path(vault).expanduser().resolve() if vault else None
        self.export_folder = export_folder

    def search(self, query: str, limit: int = 12) -> list[dict]:
        if not self.vault or not self.vault.is_dir():
            return []
        if not _descriptor_export_supported():
            raise SafetyError(
                "Obsidian search requires descriptor-relative no-follow filesystem access."
            )
        terms = _terms(query)
        scored: list[tuple[int, str, str]] = []
        try:
            vault_fd = os.open(self.vault, _directory_flags())
        except OSError as exc:
            raise SafetyError("Configured Obsidian vault is not a safe directory.") from exc
        try:
            vault_state = os.fstat(vault_fd)
            for path in self.vault.rglob("*.md"):
                try:
                    relative = safe_repo_relative(str(path.relative_to(self.vault)))
                    text = _read_text_beneath(vault_fd, relative)
                except (OSError, SafetyError, ValueError):
                    continue
                haystack = (Path(relative).name + "\n" + text).lower()
                score = sum(haystack.count(term) for term in terms)
                if score:
                    scored.append((score, relative, text))
            current_vault = os.stat(self.vault, follow_symlinks=False)
            if not stat.S_ISDIR(current_vault.st_mode) or not _same_filesystem_object(
                vault_state, current_vault
            ):
                raise SafetyError("Configured Obsidian vault changed during search.")
        finally:
            os.close(vault_fd)
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [
            {"path": relative, "score": score, "excerpt": text[:4000]}
            for score, relative, text in scored[:limit]
        ]

    def export(self, filename: str, markdown: str) -> Path | None:
        if not self.vault or not self.vault.is_dir():
            return None
        if not _descriptor_export_supported():
            raise SafetyError(
                "Obsidian export requires descriptor-relative no-follow filesystem access."
            )
        export_relative = safe_repo_relative(self.export_folder)
        filename_relative = safe_repo_relative(filename)
        try:
            vault_fd = os.open(self.vault, _directory_flags())
        except OSError as exc:
            raise SafetyError("Configured Obsidian vault is not a safe directory.") from exc
        export_fd: int | None = None
        destination_parent_fd: int | None = None
        try:
            vault_state = os.fstat(vault_fd)
            export_fd = _open_safe_directory_chain(vault_fd, export_relative)
            parent_relative = str(Path(filename_relative).parent)
            destination_parent_fd = _open_safe_directory_chain(
                export_fd,
                parent_relative,
            )
            os.close(destination_parent_fd)
            destination_parent_fd = None
            destination_name = Path(filename_relative).name
            destination_parent_relative = str(
                Path(export_relative) / Path(parent_relative)
            )
            destination_relative = str(
                Path(destination_parent_relative) / destination_name
            )
            written_state = _write_text_beneath(
                vault_fd,
                destination_relative,
                markdown,
            )

            current_vault = os.stat(self.vault, follow_symlinks=False)
            if not stat.S_ISDIR(current_vault.st_mode) or not _same_filesystem_object(
                vault_state, current_vault
            ):
                raise SafetyError("Configured Obsidian vault changed during export.")
            current_parent_fd = _open_safe_directory_chain(
                vault_fd,
                destination_parent_relative,
            )
            verification_fd: int | None = None
            try:
                try:
                    verification_fd = _open_beneath(
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
                destination_state = os.fstat(verification_fd)
                if (
                    not stat.S_ISREG(destination_state.st_mode)
                    or destination_state.st_nlink != 1
                    or not _same_filesystem_object(written_state, destination_state)
                ):
                    raise SafetyError("Obsidian export destination changed during export.")
            finally:
                if verification_fd is not None:
                    os.close(verification_fd)
                os.close(current_parent_fd)
            return self.vault / export_relative / filename_relative
        finally:
            if destination_parent_fd is not None:
                os.close(destination_parent_fd)
            if export_fd is not None:
                os.close(export_fd)
            os.close(vault_fd)


class ExternalCommandIntegration:
    """Optional integration point with argv-only execution and explicit configuration."""

    def __init__(self, argv_template: Iterable[str], runner: CommandRunner):
        self.argv_template = list(argv_template)
        self.runner = runner

    @property
    def enabled(self) -> bool:
        return bool(self.argv_template)

    def run(self, *, cwd: Path, values: dict[str, str], timeout_seconds: int = 300, log_name: str | None = None):
        if not self.enabled:
            return None
        argv = [item.format(**values) for item in self.argv_template]
        return self.runner.run(argv, cwd=cwd, timeout_seconds=timeout_seconds, log_name=log_name)


def command_record(name: str, result) -> dict:
    if result is None:
        return {"name": name, "enabled": False, "ok": False}
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "name": name,
        "enabled": True,
        "ok": result.passed,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "argv": result.argv,
        "stdout": stdout[:MAX_EXTERNAL_TEXT_CHARS],
        "stderr": stderr[:MAX_EXTERNAL_TEXT_CHARS],
        "truncated": len(stdout) > MAX_EXTERNAL_TEXT_CHARS or len(stderr) > MAX_EXTERNAL_TEXT_CHARS,
    }
