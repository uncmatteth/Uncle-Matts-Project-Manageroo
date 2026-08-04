from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config_lock import _try_lock_file, _unlock_file


def _decode_timeout_output(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


@contextmanager
def _destination_lock(destination: Path, *, timeout: float = 30.0) -> Iterator[None]:
    lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
    flags = os.O_CREAT | os.O_RDWR
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    acquired = False
    try:
        lock_state = os.fstat(fd)
        if not stat.S_ISREG(lock_state.st_mode):
            raise OSError(f"AUTOREVIEW update lock is not a regular file: {lock}")
        if lock_state.st_size == 0:
            os.ftruncate(fd, 1)

        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock_file(fd)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out waiting for AUTOREVIEW update lock: {lock}"
                    ) from exc
                time.sleep(0.05)

        owner_payload = f"pid={os.getpid()}\n".encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, owner_payload)
        os.ftruncate(fd, len(owner_payload))
        os.fsync(fd)
        yield
    finally:
        try:
            if acquired:
                _unlock_file(fd)
        finally:
            os.close(fd)


def _manager_bin(module: Any, manager: str) -> Path | None:
    executable = shutil.which(manager)
    if not executable:
        return None
    if manager == "npm":
        probe = module._run([executable, "prefix", "-g"], timeout=30)
        if probe.get("ok"):
            prefix = Path(str(probe.get("output") or "").strip()).expanduser()
            return prefix if os.name == "nt" else prefix / "bin"
    if manager == "pnpm":
        probe = module._run([executable, "bin", "-g"], timeout=30)
        if probe.get("ok"):
            return Path(str(probe.get("output") or "").strip()).expanduser()
    return None


def _manager_package_root(module: Any, manager: str) -> Path | None:
    executable = shutil.which(manager)
    if not executable or manager not in {"npm", "pnpm"}:
        return None
    probe = module._run([executable, "root", "-g"], timeout=30)
    if not probe.get("ok"):
        return None
    return Path(str(probe.get("output") or "").strip()).expanduser()


def _owned_by_manager(
    module: Any,
    tool_path: str | None,
    manager: str,
    package_name: str = "",
) -> bool:
    if not tool_path:
        return False
    tool = Path(tool_path).expanduser()
    try:
        resolved_tool = tool.resolve(strict=True)
    except OSError:
        return False
    if manager in {"npm", "pnpm"}:
        root = _manager_bin(module, manager)
        if root is None:
            return False
        try:
            tool.absolute().relative_to(root.resolve(strict=False))
        except ValueError:
            return False
        if tool.is_symlink():
            package_root = _manager_package_root(module, manager)
            if package_root is None:
                return False
            try:
                resolved_tool.relative_to(package_root.resolve(strict=False))
            except ValueError:
                return False
        if package_name:
            executable = shutil.which(manager)
            if not executable:
                return False
            probe = module._run(
                [executable, "list", "-g", "--depth=0", package_name],
                timeout=30,
            )
            return bool(probe.get("ok"))
        return True
    if manager == "brew":
        executable = shutil.which("brew")
        if not executable:
            return False
        probe = module._run([executable, "list", "--cask", "obsidian"], timeout=30)
        return bool(probe.get("ok"))
    if manager == "flatpak":
        executable = shutil.which("flatpak")
        if not executable:
            return False
        probe = module._run(
            [executable, "info", "--user", "md.obsidian.Obsidian"],
            timeout=30,
        )
        return bool(probe.get("ok"))
    if manager == "snap":
        return str(tool).replace("\\", "/").startswith("/snap/bin/")
    return False


def install_stack_update_policy(module: Any) -> None:
    if getattr(module, "_manageroo_stack_update_policy_installed", False):
        return
    original_run = module._run
    original_plan = module.stack_update_plan

    def hardened_run(argv: list[str], *, cwd: Path | None = None, timeout: int = 900):
        try:
            result = subprocess.run(
                argv,
                cwd=str(cwd or Path.home()),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                timeout=timeout,
            )
            return {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "argv": argv,
                "output": (result.stdout or "")[-8000:],
            }
        except subprocess.TimeoutExpired as exc:
            output = _decode_timeout_output(exc.stdout if exc.stdout is not None else exc.output)
            return {"ok": False, "exit_code": 124, "argv": argv, "output": output[-8000:]}
        except OSError as exc:
            return {"ok": False, "exit_code": 127, "argv": argv, "output": str(exc)}

    def hardened_replace(source: Path, destination: Path) -> dict[str, Any]:
        destination = destination.expanduser()
        if destination.is_symlink():
            return {
                "ok": False,
                "name": "autoreview",
                "path": str(destination),
                "error": "Refusing to replace a symlink alias directly; update its resolved target instead.",
            }
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage: Path | None = None
        rollback_root: Path | None = None
        previous: Path | None = None
        try:
            with _destination_lock(destination):
                stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.manageroo-stage-", dir=str(destination.parent)))
                shutil.rmtree(stage)
                shutil.copytree(source, stage)
                if destination.exists():
                    rollback_root, previous = module._temporary_rollback_path(destination)
                    destination.rename(previous)
                try:
                    stage.rename(destination)
                except Exception as swap_exc:
                    restore_error: Exception | None = None
                    if previous and previous.exists() and not destination.exists():
                        try:
                            previous.rename(destination)
                        except Exception as exc:
                            restore_error = exc
                    if restore_error:
                        raise RuntimeError(
                            f"update failed: {swap_exc}; rollback failed: {restore_error}; "
                            f"recovery data remains at {rollback_root}"
                        ) from swap_exc
                    raise
                if rollback_root is not None:
                    try:
                        shutil.rmtree(rollback_root)
                    except OSError as cleanup_exc:
                        return {
                            "ok": True,
                            "name": "autoreview",
                            "path": str(destination),
                            "backup": str(previous) if previous else None,
                            "cleanup_warning": (
                                "The update was installed, but old rollback storage could not be removed: "
                                f"{cleanup_exc}"
                            ),
                        }
                return {
                    "ok": True,
                    "name": "autoreview",
                    "path": str(destination),
                    "backup": None,
                }
        except Exception as exc:
            return {
                "ok": False,
                "name": "autoreview",
                "path": str(destination),
                "error": f"update failed and the previous installation was preserved when possible: {exc}",
            }
        finally:
            if stage is not None and stage.exists() and stage != destination:
                try:
                    if stage.is_dir() and not stage.is_symlink():
                        shutil.rmtree(stage)
                    else:
                        stage.unlink()
                except OSError:
                    pass
            if rollback_root is not None and rollback_root.exists():
                try:
                    if not any(rollback_root.iterdir()):
                        rollback_root.rmdir()
                except OSError:
                    pass

    def ownership_checked_plan(only=None):
        report = original_plan(only)
        for tool in report.get("tools", []):
            name = tool.get("name")
            commands = list(tool.get("commands", []) or [])
            active_path = shutil.which(str(name)) if name in {"gitnexus", "clawpatch", "obsidian"} else None
            if name in {"gitnexus", "clawpatch"} and commands:
                manager = Path(str(commands[0][0])).name.lower()
                manager = "pnpm" if "pnpm" in manager else "npm" if "npm" in manager else manager
                package = module.GITNEXUS_PACKAGE if name == "gitnexus" else module.CLAWPATCH_PACKAGE
                package_name = package.split("@", 1)[0]
                if not _owned_by_manager(module, active_path, manager, package_name):
                    alternate = "pnpm" if manager == "npm" else "npm"
                    alternate_executable = shutil.which(alternate)
                    if alternate_executable and _owned_by_manager(
                        module, active_path, alternate, package_name
                    ):
                        verb = "add" if alternate == "pnpm" else "install"
                        tool["commands"] = [[alternate_executable, verb, "-g", package]]
                        if name == "clawpatch":
                            tool["commands"].append([active_path, "doctor"])
                        continue
                    tool["commands"] = []
                    tool["note"] = (
                        str(tool.get("note") or "")
                        + f" Automatic update skipped because {manager} ownership of the active executable could not be proven."
                    ).strip()
            elif name == "obsidian" and commands:
                manager = Path(str(commands[0][0])).name.lower()
                if manager in {"brew", "flatpak", "snap"} and not _owned_by_manager(
                    module, active_path, manager
                ):
                    tool["commands"] = []
                    tool["note"] = (
                        f"Automatic update skipped because {manager} ownership of the active "
                        "Obsidian executable could not be proven."
                    )
                elif manager not in {"brew", "flatpak", "snap"}:
                    tool["commands"] = []
                    tool["note"] = (
                        "Automatic Obsidian update skipped because ownership of the active executable "
                        "cannot be proven from the detected package manager."
                    )
        return report

    module._run = hardened_run
    module._replace_autoreview = hardened_replace
    module.stack_update_plan = ownership_checked_plan
    module._manageroo_stack_update_policy_installed = True
