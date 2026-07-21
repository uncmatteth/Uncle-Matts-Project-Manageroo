from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def _decode_timeout_output(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _pid_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


@contextmanager
def _destination_lock(destination: Path, *, timeout: float = 30.0) -> Iterator[None]:
    lock = destination.with_name(f".{destination.name}.manageroo-update.lock")
    deadline = time.monotonic() + timeout
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                text = lock.read_text(encoding="utf-8").strip()
                pid = int(text.split("=", 1)[1]) if text.startswith("pid=") else 0
            except (OSError, ValueError):
                pid = 0
            if not pid or not _pid_live(pid):
                try:
                    lock.unlink()
                    continue
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for AUTOREVIEW update lock: {lock}")
            time.sleep(0.05)
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        try:
            text = lock.read_text(encoding="utf-8").strip()
            if text == f"pid={os.getpid()}":
                lock.unlink()
        except FileNotFoundError:
            pass


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


def _owned_by_manager(module: Any, tool_path: str | None, manager: str) -> bool:
    if not tool_path:
        return False
    tool = Path(tool_path).expanduser()
    try:
        resolved = tool.resolve(strict=True)
    except OSError:
        return False
    if manager in {"npm", "pnpm"}:
        root = _manager_bin(module, manager)
        if root is None:
            return False
        try:
            resolved.relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False
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
        backup: Path | None = None
        try:
            with _destination_lock(destination):
                stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.manageroo-stage-", dir=str(destination.parent)))
                shutil.rmtree(stage)
                shutil.copytree(source, stage)
                if destination.exists():
                    backup = module._unique_backup(destination)
                    destination.rename(backup)
                try:
                    stage.rename(destination)
                except Exception as swap_exc:
                    restore_error: Exception | None = None
                    if backup and backup.exists() and not destination.exists():
                        try:
                            backup.rename(destination)
                        except Exception as exc:
                            restore_error = exc
                    if restore_error:
                        raise RuntimeError(f"update failed: {swap_exc}; rollback failed: {restore_error}") from swap_exc
                    raise
                return {
                    "ok": True,
                    "name": "autoreview",
                    "path": str(destination),
                    "backup": str(backup) if backup else None,
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

    def ownership_checked_plan(only=None):
        report = original_plan(only)
        for tool in report.get("tools", []):
            name = tool.get("name")
            commands = list(tool.get("commands", []) or [])
            active_path = shutil.which(str(name)) if name in {"gitnexus", "clawpatch", "obsidian"} else None
            if name in {"gitnexus", "clawpatch"} and commands:
                manager = Path(str(commands[0][0])).name.lower()
                manager = "pnpm" if "pnpm" in manager else "npm" if "npm" in manager else manager
                if not _owned_by_manager(module, active_path, manager):
                    tool["commands"] = []
                    tool["note"] = (
                        str(tool.get("note") or "")
                        + f" Automatic update skipped because {manager} ownership of the active executable could not be proven."
                    ).strip()
            elif name == "obsidian" and commands:
                manager = Path(str(commands[0][0])).name.lower()
                if manager == "snap" and not _owned_by_manager(module, active_path, "snap"):
                    tool["commands"] = []
                    tool["note"] = "Automatic update skipped because Snap ownership of the active Obsidian executable could not be proven."
                elif manager != "snap":
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
