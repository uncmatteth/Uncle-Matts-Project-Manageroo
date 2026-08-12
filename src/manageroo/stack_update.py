from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .assets import asset_path
from .clawpatch_release import (
    SUPERVISOR_GATE_VERSION,
    supervisor_runtime_gate_ready,
    supervisor_runtime_lock,
)
from .errors import SafetyError
from .trufflehog import (
    TRUFFLEHOG_REFERENCE,
    TRUFFLEHOG_VERSION,
    install_trufflehog_binary,
)
from .token_modes import (
    CORE_HELPER_SKILLS,
    install_core_helper_skills,
    token_mode_skills_dir,
)
from .util import redact_text


GBRAIN_REFERENCE = "https://github.com/garrytan/gbrain"
GBRAIN_COMMIT = "f84bfb57f2ab9294ea9c4bb33e40dec75dab41bf"
GITNEXUS_REFERENCE = "https://github.com/abhigyanpatwari/GitNexus"
GITNEXUS_PACKAGE = "gitnexus@1.6.9"
AUTOREVIEW_REPO = "https://github.com/openclaw/agent-skills.git"
AUTOREVIEW_COMMIT = "4b79fc967ba4d7c5231f99dd27bb1372c83e9430"
AUTOREVIEW_REFERENCE = (
    "https://github.com/openclaw/agent-skills/tree/"
    f"{AUTOREVIEW_COMMIT}/skills/autoreview"
)
CLAWPATCH_PACKAGE = "clawpatch@0.7.2"
CLAWPATCH_REFERENCE = "https://github.com/openclaw/clawpatch"
CLAWPATCH_SUPERVISOR_COMMIT = "7217bcd7ac19902333308725223773825f6e599a"
CLAWPATCH_SUPERVISOR_REFERENCE = "https://github.com/uncmatteth/clawpatch-supervise"
CLAWPATCH_SUPERVISOR_SOURCE = (
    f"git+{CLAWPATCH_SUPERVISOR_REFERENCE}.git@{CLAWPATCH_SUPERVISOR_COMMIT}"
)
_SUPERVISOR_TARGET_UPDATE = (
    "import runpy,sys,sysconfig;"
    "sys.argv=['pip','install','--disable-pip-version-check','--no-cache-dir',"
    "'--no-deps','--upgrade','--force-reinstall','--target',"
    "sysconfig.get_path('purelib'),sys.argv[1]];"
    "runpy.run_module('pip',run_name='__main__')"
)
OBSIDIAN_REFERENCE = "https://obsidian.md/download"
MANAGEROO_SKILLS_REFERENCE = "https://github.com/unclematteth/Uncle-Matts-Project-Manageroo/tree/main/src/manageroo/assets/skills"
OBSIDIAN_PACKAGE_MANAGERS = frozenset({"brew", "flatpak", "snap", "winget"})
STACK_TOOL_NAMES = (
    "gbrain",
    "gitnexus",
    "trufflehog",
    "autoreview",
    "clawpatch",
    "clawpatch-supervise",
    "obsidian",
    "skills",
)


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 900) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd or Path.home()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout,
        )
        stdout = (result.stdout or "")[-8000:]
        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "argv": argv,
            "output": stdout,
            "stdout": stdout,
            "stderr": redact_text((result.stderr or "")[-8000:]),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "ok": False,
            "exit_code": 124,
            "argv": argv,
            "output": stdout[-8000:],
            "stdout": stdout[-8000:],
            "stderr": redact_text(stderr[-8000:]),
        }
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "argv": argv,
            "output": "",
            "stdout": "",
            "stderr": redact_text(str(exc)),
        }


def _tool(
    name: str,
    installed: bool,
    commands: list[list[str]],
    reference: str,
    note: str = "",
    **extra: Any,
) -> dict:
    return {
        "name": name,
        "installed": installed,
        "commands": commands,
        "reference": reference,
        "note": note,
        **extra,
    }


def _normalize_only(only: Iterable[str] | None) -> set[str] | None:
    if only is None:
        return None
    selected = {str(name).strip().lower() for name in only if str(name).strip()}
    unknown = selected - set(STACK_TOOL_NAMES)
    if unknown:
        raise ValueError(f"Unknown stack tool(s): {', '.join(sorted(unknown))}")
    return selected


def _skill_frontmatter_name(path: Path) -> str:
    try:
        content = path.read_bytes()
        if len(content) > 64 * 1024:
            return ""
        text = (
            content.decode("utf-8")
            .removeprefix("\ufeff")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
    except (OSError, UnicodeError):
        return ""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return ""
    try:
        end = lines.index("---", 1)
    except ValueError:
        return ""
    for line in lines[1:end]:
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def _autoreview_installation_error(
    installation: dict[str, Any], destination: Path
) -> str | None:
    path_fields = ("candidate_path", "approved_root", "resolved_path")
    identity_fields = (
        "candidate_device",
        "candidate_inode",
        "approved_root_device",
        "approved_root_inode",
        "target_device",
        "target_inode",
    )
    if any(not isinstance(installation.get(field), str) for field in path_fields) or any(
        not isinstance(installation.get(field), int) for field in identity_fields
    ):
        return "planned destination identity is missing or malformed"

    candidate = Path(installation["candidate_path"]).expanduser()
    approved_root = Path(installation["approved_root"]).expanduser()
    target = Path(installation["resolved_path"]).expanduser()
    try:
        canonical_destination = destination.expanduser().parent.resolve(strict=True) / destination.name
    except OSError as exc:
        return f"mutation target can no longer be verified: {exc}"
    if canonical_destination != target:
        return "mutation target identity does not match the planned resolved destination"
    if target.name != "autoreview" or target.parent != approved_root:
        return "planned target is not directly beneath its approved skill root"
    try:
        candidate_state = candidate.lstat()
        approved_root_state = approved_root.lstat()
        target_state = target.lstat()
        current_root = approved_root.resolve(strict=True)
        current_target = candidate.resolve(strict=True)
    except OSError as exc:
        return f"planned destination can no longer be verified: {exc}"
    if current_root != approved_root or not stat.S_ISDIR(approved_root_state.st_mode):
        return "approved skill root changed after planning"
    if (
        candidate_state.st_dev,
        candidate_state.st_ino,
    ) != (
        installation["candidate_device"],
        installation["candidate_inode"],
    ):
        return "AUTOREVIEW candidate identity changed after planning"
    if current_target != target:
        return "AUTOREVIEW candidate resolves to a different target than the plan"
    if (
        approved_root_state.st_dev,
        approved_root_state.st_ino,
    ) != (
        installation["approved_root_device"],
        installation["approved_root_inode"],
    ):
        return "approved skill root identity changed after planning"
    if not stat.S_ISDIR(target_state.st_mode) or (
        target_state.st_dev,
        target_state.st_ino,
    ) != (
        installation["target_device"],
        installation["target_inode"],
    ):
        return "AUTOREVIEW target identity changed after planning"
    if _skill_frontmatter_name(target / "SKILL.md").casefold() != "autoreview":
        return "SKILL.md no longer identifies the AUTOREVIEW skill"
    return None


def _autoreview_installations() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    roots = [
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
    ]
    candidates = [root / "autoreview" for root in roots]
    approved_roots: list[Path] = []
    for root in roots:
        try:
            resolved_root = root.resolve(strict=True)
        except OSError:
            continue
        if resolved_root not in approved_roots:
            approved_roots.append(resolved_root)
    installations: list[dict[str, Any]] = []
    unsafe: list[dict[str, str]] = []
    for path in candidates:
        if not (path / "SKILL.md").is_file():
            continue
        try:
            target = path.resolve(strict=True)
        except OSError:
            continue
        if target.name != "autoreview" or target.parent not in approved_roots:
            unsafe.append(
                {
                    "path": str(path),
                    "resolved_path": str(target),
                    "reason": (
                        "resolved target is not an autoreview destination directly beneath "
                        "an approved skill root"
                    ),
                }
            )
            continue
        if _skill_frontmatter_name(target / "SKILL.md").casefold() != "autoreview":
            unsafe.append(
                {
                    "path": str(path),
                    "resolved_path": str(target),
                    "reason": "SKILL.md does not identify the autoreview skill",
                }
            )
            continue
        if any(item["resolved_path"] == str(target) for item in installations):
            continue
        try:
            candidate_state = path.lstat()
            approved_root_state = target.parent.lstat()
            target_state = target.lstat()
        except OSError:
            continue
        installation = {
            "candidate_path": str(path),
            "approved_root": str(target.parent),
            "resolved_path": str(target),
            "candidate_device": candidate_state.st_dev,
            "candidate_inode": candidate_state.st_ino,
            "approved_root_device": approved_root_state.st_dev,
            "approved_root_inode": approved_root_state.st_ino,
            "target_device": target_state.st_dev,
            "target_inode": target_state.st_ino,
        }
        identity_error = _autoreview_installation_error(installation, target)
        if identity_error:
            unsafe.append(
                {
                    "path": str(path),
                    "resolved_path": str(target),
                    "reason": identity_error,
                }
            )
            continue
        installations.append(installation)
    return installations, unsafe


def _manageroo_owned_trufflehog_path(active_path: str | None) -> Path | None:
    """Return the active binary only when the install lock proves Manageroo ownership."""
    if not active_path:
        return None
    from .install_status import read_install_lock

    loaded = read_install_lock()
    if not loaded.get("ok"):
        return None
    lock = loaded["lock"]
    launcher = lock.get("launcher")
    if not isinstance(launcher, str) or not Path(launcher).is_absolute():
        return None
    active = Path(active_path).expanduser()
    try:
        active_resolved = active.resolve(strict=True)
        launcher_parent = Path(launcher).expanduser().parent.resolve(strict=False)
    except OSError:
        return None
    if active_resolved.parent != launcher_parent or active_resolved.name.lower() not in {"trufflehog", "trufflehog.exe"}:
        return None
    for tool in lock.get("external_tools", []):
        if not isinstance(tool, dict) or tool.get("name") != "trufflehog" or not tool.get("manageroo_owned"):
            continue
        recorded = tool.get("path")
        if isinstance(recorded, str):
            try:
                if Path(recorded).expanduser().resolve(strict=True) == active_resolved:
                    return active_resolved
            except OSError:
                return None
    return None


def _pinned_package_commands(
    *,
    executable: str | None,
    npm: str | None,
    pnpm: str | None,
    package: str,
) -> list[list[str]]:
    """Return deterministic update commands for an already-detected CLI.

    PATH discovery is the installation boundary for npm/pnpm-managed CLIs. Ownership
    probes are intentionally not required here: they made dry-run planning dependent on
    host-specific package-manager output and could suppress a valid pinned update.
    """
    if not executable:
        return []
    if npm:
        return [[npm, "install", "-g", package]]
    if pnpm:
        return [[pnpm, "add", "-g", package]]
    return []


def _safe_supervisor_path_states(path: Path, root: Path) -> dict[Path, os.stat_result] | None:
    """Return stable lexical path states without accepting links or reparse points."""
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    states: dict[Path, os.stat_result] = {}
    current = root
    for part in ("", *relative.parts):
        if part:
            current /= part
        try:
            state = current.lstat()
        except OSError:
            return None
        if stat.S_ISLNK(state.st_mode) or bool(
            getattr(state, "st_file_attributes", 0) & reparse_point
        ):
            return None
        if current == path:
            if not stat.S_ISREG(state.st_mode):
                return None
        elif not stat.S_ISDIR(state.st_mode):
            return None
        states[current] = state
    return states


def _supervisor_update_commands(executable: str | None) -> tuple[list[list[str]], str]:
    if not executable:
        return [], "The standalone ClawPatch supervisor was not detected."
    try:
        detected = Path(executable).expanduser()
        active = detected.parent.resolve(strict=True) / detected.name
        home = Path.home().resolve(strict=True)
    except OSError:
        return [], "The detected supervisor executable could not be resolved."
    candidates = {
        home
        / ".local"
        / "share"
        / "clawpatch-supervise"
        / "venv"
        / "bin"
        / "clawpatch-supervise": home,
        home
        / "Library"
        / "Application Support"
        / "ManagerooClawPatchSupervisor"
        / "venv"
        / "bin"
        / "clawpatch-supervise": home,
    }
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        try:
            local_app_root = Path(local_app_data).expanduser().resolve(strict=True)
        except OSError:
            local_app_root = None
        if local_app_root is not None:
            candidate = (
                local_app_root
                / "ManagerooClawPatchSupervisor"
                / "venv-f59afab"
                / "Scripts"
                / "clawpatch-supervise.exe"
            )
            candidates[candidate] = local_app_root
    candidate = next(
        (
            path
            for path in candidates
            if os.path.normcase(str(path)) == os.path.normcase(str(active))
        ),
        None,
    )
    if candidate is None:
        return [], (
            "Automatic update skipped because the active supervisor is not in a "
            "Manageroo native-installer location."
        )
    path_states = _safe_supervisor_path_states(candidate, candidates[candidate])
    if path_states is None:
        return [], (
            "Automatic update skipped because native-installer supervisor ownership "
            "could not be proven without symlinks or reparse points."
        )
    scripts = candidate.parent
    python_names = (
        ("python.exe",) if candidate.suffix.casefold() == ".exe" else ("python", "python3")
    )
    python = None
    python_state = None
    for name in python_names:
        interpreter = scripts / name
        try:
            state = interpreter.lstat()
        except OSError:
            continue
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            stat.S_ISREG(state.st_mode)
            and not stat.S_ISLNK(state.st_mode)
            and not bool(getattr(state, "st_file_attributes", 0) & reparse_point)
        ):
            python = interpreter
            python_state = state
            break
    if python is None:
        return [], (
            "Automatic update skipped because the owned supervisor venv has no interpreter."
        )
    current_states = _safe_supervisor_path_states(candidate, candidates[candidate])
    try:
        current_python_state = python.lstat()
    except OSError:
        current_python_state = None
    if (
        current_states is None
        or current_python_state is None
        or python_state is None
        or any(
            (current_states[path].st_dev, current_states[path].st_ino)
            != (state.st_dev, state.st_ino)
            for path, state in path_states.items()
        )
        or (current_python_state.st_dev, current_python_state.st_ino)
        != (python_state.st_dev, python_state.st_ino)
    ):
        return [], (
            "Automatic update skipped because native-installer supervisor ownership "
            "changed during validation."
        )
    gate_source = asset_path("supervisor_gate")
    commands = [
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--force-reinstall",
            str(gate_source),
        ],
        [
            str(python),
            "-c",
            _SUPERVISOR_TARGET_UPDATE,
            CLAWPATCH_SUPERVISOR_SOURCE,
        ],
        [str(candidate), "--version"],
    ]
    return commands, (
        "Installs the shared runtime gate, then updates only the proven native-installer "
        f"venv to standalone supervisor commit {CLAWPATCH_SUPERVISOR_COMMIT}."
    )


def _supervisor_update_blocker(executable: str | None) -> str | None:
    """Find a legacy supervisor while its launcher is migrated to the runtime gate."""
    if not executable:
        return None
    if platform.system().lower() == "windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return (
                "Automatic supervisor update could not inspect legacy Windows processes; "
                "the owned virtual environment was not updated."
            )
        try:
            probe = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process | "
                        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
                    ),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            probe = None
        if probe is None or probe.returncode != 0:
            return (
                "Automatic supervisor update could not inspect legacy Windows processes; "
                "the owned virtual environment was not updated."
            )
        try:
            records = json.loads(probe.stdout or "[]")
        except json.JSONDecodeError:
            return (
                "Automatic supervisor update received an invalid Windows process snapshot; "
                "the owned virtual environment was not updated."
            )
        if isinstance(records, dict):
            records = [records]
        candidates = {str(Path(executable).expanduser())}
        try:
            candidates.add(str(Path(executable).expanduser().resolve(strict=True)))
        except OSError:
            pass
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            command = str(record.get("CommandLine") or "")
            if any(
                candidate and candidate.casefold() in command.casefold()
                for candidate in candidates
            ):
                return (
                    f"Standalone supervisor process {record.get('ProcessId', '?')} is still "
                    "running; the owned virtual environment was not updated."
                )
        return None
    candidates = {str(Path(executable).expanduser())}
    try:
        candidates.add(str(Path(executable).expanduser().resolve(strict=True)))
    except OSError:
        pass
    ps = shutil.which("ps")
    if not ps:
        return (
            "Automatic supervisor update could not inspect legacy processes because ps is "
            "unavailable; the owned virtual environment was not updated."
        )
    try:
        probe = subprocess.run(
            [ps, "-axo", "pid=,command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return (
            "Automatic supervisor update could not inspect legacy processes; the owned "
            "virtual environment was not updated."
        )
    if probe.returncode != 0:
        return (
            "Automatic supervisor update could not inspect legacy processes; the owned "
            "virtual environment was not updated."
        )
    current_pid = os.getpid()
    for line in probe.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit() or int(fields[0]) == current_pid:
            continue
        command = fields[1]
        if any(candidate and candidate in command for candidate in candidates):
            return (
                f"Standalone supervisor process {fields[0]} is still running; "
                "the owned virtual environment was not updated."
            )
    return None


def _supervisor_gate_migration_marker(executable: str) -> Path:
    active = Path(executable).expanduser().resolve(strict=True)
    return active.parent / "cache" / f"{active.name}.manageroo-gate-migrated"


def _supervisor_gate_migration_complete(executable: str) -> bool:
    descriptor: int | None = None
    try:
        marker = _supervisor_gate_migration_marker(executable)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(marker, flags)
        descriptor_state = os.fstat(descriptor)
        path_state = marker.lstat()
        content = os.read(descriptor, 64)
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return bool(
        stat.S_ISREG(descriptor_state.st_mode)
        and stat.S_ISREG(path_state.st_mode)
        and descriptor_state.st_nlink == 1
        and path_state.st_nlink == 1
        and (descriptor_state.st_dev, descriptor_state.st_ino)
        == (path_state.st_dev, path_state.st_ino)
        and content == f"{SUPERVISOR_GATE_VERSION}\n".encode("utf-8")
    )


def _record_supervisor_gate_migration(executable: str) -> None:
    marker = _supervisor_gate_migration_marker(executable)
    payload = f"{SUPERVISOR_GATE_VERSION}\n".encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(marker, flags, 0o600)
    except FileExistsError as exc:
        if _supervisor_gate_migration_complete(executable):
            return
        raise SafetyError(
            f"Supervisor runtime gate migration marker is unsafe or invalid: {marker}"
        ) from exc
    except OSError as exc:
        raise SafetyError(
            f"Could not create supervisor runtime gate migration marker: {marker}: {exc}"
        ) from exc
    try:
        descriptor_state = os.fstat(descriptor)
        path_state = marker.lstat()
        if (
            not stat.S_ISREG(descriptor_state.st_mode)
            or not stat.S_ISREG(path_state.st_mode)
            or descriptor_state.st_nlink != 1
            or path_state.st_nlink != 1
            or (descriptor_state.st_dev, descriptor_state.st_ino)
            != (path_state.st_dev, path_state.st_ino)
        ):
            raise SafetyError(
                f"Supervisor runtime gate migration marker is unsafe: {marker}"
            )
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _snap_owned_obsidian_path(obsidian: str | None) -> bool:
    if not obsidian:
        return False
    normalized = str(obsidian).replace("\\", "/").lower()
    if normalized.startswith("/snap/"):
        return True
    try:
        resolved = Path(obsidian).expanduser().resolve(strict=True)
    except OSError:
        return False
    return str(resolved).replace("\\", "/").lower().startswith("/snap/")


def _obsidian_owned_by_manager(obsidian: str | None, manager: str) -> bool:
    if not obsidian or manager not in OBSIDIAN_PACKAGE_MANAGERS:
        return False
    if manager == "snap" and _snap_owned_obsidian_path(obsidian):
        return True
    try:
        Path(obsidian).expanduser().resolve(strict=True)
    except OSError:
        return False
    executable = shutil.which(manager)
    if not executable:
        return False
    probes = {
        "brew": [executable, "list", "--cask", "obsidian"],
        "flatpak": [executable, "info", "--user", "md.obsidian.Obsidian"],
        "snap": [executable, "list", "obsidian"],
        "winget": [
            executable,
            "list",
            "--id",
            "Obsidian.Obsidian",
            "-e",
            "--source",
            "winget",
        ],
    }
    return bool(_run(probes[manager], timeout=30).get("ok"))


def _obsidian_update_commands(obsidian: str | None) -> tuple[list[list[str]], str]:
    if not obsidian:
        return [], "Obsidian was not detected."
    system = platform.system().lower()
    if system == "windows" and shutil.which("winget"):
        if _obsidian_owned_by_manager(obsidian, "winget"):
            return [[
                shutil.which("winget") or "winget",
                "upgrade",
                "--id",
                "Obsidian.Obsidian",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]], "Winget owns the detected Obsidian installation."
        return [], "Could not prove that Winget owns the detected Obsidian installation."
    if system == "darwin" and shutil.which("brew"):
        if _obsidian_owned_by_manager(obsidian, "brew"):
            return [[shutil.which("brew") or "brew", "upgrade", "--cask", "obsidian"]], "Homebrew owns the detected Obsidian installation."
        return [], "Could not prove that Homebrew owns the detected Obsidian installation."
    if system == "linux":
        flatpak = shutil.which("flatpak")
        snap = shutil.which("snap")
        # The resolved executable path is strong ownership evidence for a Snap install.
        if snap and _snap_owned_obsidian_path(obsidian):
            return [[snap, "refresh", "obsidian"]], (
                "Detected Snap-owned Obsidian installation."
            )
        if flatpak and _obsidian_owned_by_manager(obsidian, "flatpak"):
            return [[flatpak, "update", "--user", "-y", "md.obsidian.Obsidian"]], "Flatpak owns the detected Obsidian installation."
        if snap and _obsidian_owned_by_manager(obsidian, "snap"):
            return [[snap, "refresh", "obsidian"]], "Snap owns the detected Obsidian installation."
        return [], "Could not safely identify which Linux package manager owns the detected Obsidian installation."
    return [], "No supported automatic update lane was identified for the detected Obsidian installation."


def stack_update_plan(only: Iterable[str] | None = None) -> dict[str, Any]:
    selected = _normalize_only(only)
    gbrain = shutil.which("gbrain")
    npm = shutil.which("npm")
    gitnexus = shutil.which("gitnexus")
    pnpm = shutil.which("pnpm")
    clawpatch = shutil.which("clawpatch")
    clawpatch_supervise = shutil.which("clawpatch-supervise")
    obsidian = shutil.which("obsidian")
    trufflehog = shutil.which("trufflehog")
    owned_trufflehog = _manageroo_owned_trufflehog_path(trufflehog)
    autoreview_installations, unsafe_autoreview_paths = _autoreview_installations()
    skills_root = token_mode_skills_dir().expanduser()
    installed_core_skills = [
        name
        for name in CORE_HELPER_SKILLS
        if (skills_root / name / "SKILL.md").is_file()
    ]

    gitnexus_commands = _pinned_package_commands(
        executable=gitnexus,
        npm=npm,
        pnpm=pnpm,
        package=GITNEXUS_PACKAGE,
    )
    gitnexus_note = (
        f"Updates only to the Manageroo-release pin {GITNEXUS_PACKAGE}. "
        "Repository indexing remains project-specific and is performed with `gitnexus analyze` from a target repo."
    )
    if not gitnexus:
        gitnexus_note += " No persistent GitNexus installation was detected, so stack-update will not install one implicitly."

    clawpatch_commands = _pinned_package_commands(
        executable=clawpatch,
        npm=npm if not pnpm else None,
        pnpm=pnpm,
        package=CLAWPATCH_PACKAGE,
    )
    if clawpatch_commands and clawpatch:
        clawpatch_commands.append([clawpatch, "doctor"])
    supervisor_commands, supervisor_note = _supervisor_update_commands(clawpatch_supervise)

    obsidian_commands, obsidian_note = _obsidian_update_commands(obsidian)

    tools = [
        _tool(
            "gbrain",
            bool(gbrain),
            [[gbrain, "doctor", "--json"]] if gbrain else [],
            GBRAIN_REFERENCE,
            (
                "Manageroo does not run GBrain's mutable self-upgrade command. "
                f"The installer pin for this Manageroo release is commit {GBRAIN_COMMIT}; stack-update only verifies the existing installation."
            ),
        ),
        _tool(
            "gitnexus",
            bool(gitnexus),
            gitnexus_commands,
            GITNEXUS_REFERENCE,
            gitnexus_note,
        ),
        _tool(
            "trufflehog",
            bool(trufflehog),
            [],
            TRUFFLEHOG_REFERENCE,
            (
                f"Updates the Manageroo-owned binary only to release pin {TRUFFLEHOG_VERSION}."
                if owned_trufflehog
                else "Automatic update skipped because Manageroo ownership of the active TruffleHog binary was not proven."
            ),
            install_paths=[str(owned_trufflehog)] if owned_trufflehog else [],
            pinned_version=TRUFFLEHOG_VERSION,
        ),
        _tool(
            "autoreview",
            bool(autoreview_installations or unsafe_autoreview_paths),
            [],
            AUTOREVIEW_REFERENCE,
            (
                f"Updates each unique resolved AUTOREVIEW installation from pinned commit {AUTOREVIEW_COMMIT}. "
                "Skill-root symlinks remain symlinks and aliases to the same target are updated only once."
            ),
            install_paths=[item["resolved_path"] for item in autoreview_installations],
            installation_records=autoreview_installations,
            unsafe_destinations=unsafe_autoreview_paths,
        ),
        _tool(
            "clawpatch",
            bool(clawpatch),
            clawpatch_commands,
            CLAWPATCH_REFERENCE,
            f"Updates only to the Manageroo-release pin {CLAWPATCH_PACKAGE} and reruns `clawpatch doctor`.",
        ),
        _tool(
            "clawpatch-supervise",
            bool(clawpatch_supervise),
            supervisor_commands,
            CLAWPATCH_SUPERVISOR_REFERENCE,
            supervisor_note,
            pinned_commit=CLAWPATCH_SUPERVISOR_COMMIT,
        ),
        _tool(
            "obsidian",
            bool(obsidian),
            obsidian_commands,
            OBSIDIAN_REFERENCE,
            obsidian_note,
        ),
        _tool(
            "skills",
            bool(installed_core_skills),
            [],
            MANAGEROO_SKILLS_REFERENCE,
            (
                "Reconciles the complete Manageroo core skill pack shipped by this release. "
                "Only missing or cryptographically proven Manageroo-owned trees are written; "
                "host-owned and user-edited same-name skills are preserved."
            ),
            install_paths=[str(skills_root)],
            bundled_skill_count=len(CORE_HELPER_SKILLS),
            detected_skill_count=len(installed_core_skills),
            bundled_skills=sorted(CORE_HELPER_SKILLS),
        ),
    ]
    if selected is not None:
        tools = [tool for tool in tools if tool["name"] in selected]
    return {
        "ok": True,
        "executes_changes": False,
        "selected_tools": [tool["name"] for tool in tools],
        "tools": tools,
    }


def _temporary_rollback_path(destination: Path) -> tuple[Path, Path]:
    """Create same-filesystem rollback storage outside the discovered skills root."""
    rollback_root = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.manageroo-rollback-",
            dir=str(destination.parent.parent),
        )
    )
    return rollback_root, rollback_root / destination.name


def _moved_autoreview_installation_error(
    moved: Path,
    installation: dict[str, Any] | None,
) -> str | None:
    """Verify that rollback storage contains the target validated by the plan."""
    if installation is None:
        return None
    try:
        moved_state = moved.lstat()
    except OSError as exc:
        return f"moved AUTOREVIEW target can no longer be verified: {exc}"
    if not stat.S_ISDIR(moved_state.st_mode) or (
        moved_state.st_dev,
        moved_state.st_ino,
    ) != (
        installation["target_device"],
        installation["target_inode"],
    ):
        return "moved AUTOREVIEW target identity does not match the plan"
    return None


def _move_verified_autoreview_destination(
    destination: Path,
    previous: Path,
    installation: dict[str, Any] | None,
) -> None:
    destination.rename(previous)
    identity_error = _moved_autoreview_installation_error(previous, installation)
    if not identity_error:
        return

    restore_error: OSError | None = None
    try:
        destination.lstat()
    except FileNotFoundError:
        try:
            previous.rename(destination)
        except OSError as exc:
            restore_error = exc
    except OSError as exc:
        restore_error = exc
    if restore_error:
        raise OSError(
            f"Unsafe AUTOREVIEW destination rejected: {identity_error}; "
            f"substituted entry could not be restored: {restore_error}; "
            f"recovery data remains at {previous.parent}"
        ) from restore_error
    raise OSError(f"Unsafe AUTOREVIEW destination rejected: {identity_error}")


def _replace_autoreview(
    source: Path,
    destination: Path,
    installation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    destination = destination.expanduser()
    identity_error = (
        _autoreview_installation_error(installation, destination)
        if installation is not None
        else None
    )
    if identity_error:
        return {
            "ok": False,
            "name": "autoreview",
            "path": str(destination),
            "error": f"Unsafe AUTOREVIEW destination rejected: {identity_error}",
        }
    if destination.is_symlink():
        return {
            "ok": False,
            "name": "autoreview",
            "path": str(destination),
            "error": "Refusing to replace a symlink alias directly; update its resolved target instead.",
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(destination.name + ".manageroo-stage")
    if stage.exists():
        shutil.rmtree(stage)
    rollback_root: Path | None = None
    previous: Path | None = None
    try:
        shutil.copytree(source, stage)
        identity_error = (
            _autoreview_installation_error(installation, destination)
            if installation is not None
            else None
        )
        if identity_error:
            raise OSError(f"Unsafe AUTOREVIEW destination rejected: {identity_error}")
        if destination.exists():
            rollback_root, previous = _temporary_rollback_path(destination)
            _move_verified_autoreview_destination(destination, previous, installation)
        stage.rename(destination)
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
        rollback_errors: list[str] = []
        if stage.exists():
            try:
                shutil.rmtree(stage)
            except OSError as cleanup_exc:
                rollback_errors.append(f"stage cleanup failed: {cleanup_exc}")
        if previous and previous.exists() and not destination.exists():
            try:
                previous.rename(destination)
            except OSError as restore_exc:
                rollback_errors.append(f"original restoration failed: {restore_exc}")
        if rollback_root and rollback_root.exists():
            try:
                if not any(rollback_root.iterdir()):
                    rollback_root.rmdir()
            except OSError as cleanup_exc:
                rollback_errors.append(f"rollback cleanup failed: {cleanup_exc}")
        if rollback_errors:
            return {
                "ok": False,
                "name": "autoreview",
                "path": str(destination),
                "error": (
                    f"update failed: {exc}; {'; '.join(rollback_errors)}; "
                    f"recovery data may remain at {rollback_root}"
                ),
            }
        return {
            "ok": False,
            "name": "autoreview",
            "path": str(destination),
            "error": f"update failed and original installation was preserved: {exc}",
        }


def _update_autoreview(installations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    targets: list[tuple[Path, dict[str, Any]]] = []
    for installation in installations:
        target_value = installation.get("resolved_path")
        if not isinstance(target_value, str):
            return {
                "ok": False,
                "name": "autoreview",
                "error": "planned AUTOREVIEW destination identity is missing or malformed",
            }
        target = Path(target_value).expanduser()
        if all(existing != target for existing, _record in targets):
            targets.append((target, installation))
    if not targets:
        return {"ok": True, "name": "autoreview", "skipped": True, "reason": "not installed"}
    git = shutil.which("git")
    if not git:
        return {"ok": False, "name": "autoreview", "error": "git is required to update AUTOREVIEW"}
    with tempfile.TemporaryDirectory(prefix="manageroo-autoreview-update-") as temp:
        checkout = Path(temp) / "agent-skills"
        clone = _run([git, "clone", "--no-checkout", AUTOREVIEW_REPO, str(checkout)], cwd=Path(temp))
        if not clone["ok"]:
            return {"name": "autoreview", **clone}
        checkout_result = _run([git, "checkout", "--detach", AUTOREVIEW_COMMIT], cwd=checkout)
        if not checkout_result["ok"]:
            return {"name": "autoreview", **checkout_result}
        resolved = _run([git, "rev-parse", "HEAD"], cwd=checkout)
        resolved_stdout = resolved.get("stdout", resolved.get("output", ""))
        if not resolved["ok"] or resolved_stdout.strip().lower() != AUTOREVIEW_COMMIT.lower():
            return {
                "ok": False,
                "name": "autoreview",
                "error": "pinned AUTOREVIEW commit verification failed",
            }
        source = checkout / "skills" / "autoreview"
        if not (source / "SKILL.md").is_file():
            return {"ok": False, "name": "autoreview", "error": "pinned autoreview skill was not found"}
        symlinks = [path for path in source.rglob("*") if path.is_symlink()]
        allowed_alias = source / "CLAUDE.md"
        if source.is_symlink() or any(
            path != allowed_alias or path.readlink() != Path("AGENTS.md") for path in symlinks
        ):
            return {
                "ok": False,
                "name": "autoreview",
                "error": "pinned autoreview tree contains an unapproved symlink",
            }
        sanitized = Path(temp) / "autoreview-sanitized"
        shutil.copytree(
            source,
            sanitized,
            ignore=lambda directory, names: [
                name for name in names if (Path(directory) / name).is_symlink()
            ],
        )
        if not (sanitized / "SKILL.md").is_file() or (sanitized / "CLAUDE.md").exists():
            return {"ok": False, "name": "autoreview", "error": "sanitized autoreview tree is invalid"}
        results = [
            _replace_autoreview(sanitized, destination, installation)
            for destination, installation in targets
        ]
        return {
            "ok": all(item.get("ok") for item in results),
            "name": "autoreview",
            "pinned_commit": AUTOREVIEW_COMMIT,
            "omitted_compatibility_aliases": ["CLAUDE.md"] if symlinks else [],
            "installations": results,
        }


def apply_stack_updates(only: Iterable[str] | None = None) -> dict[str, Any]:
    plan = stack_update_plan(only)
    results: list[dict[str, Any]] = []
    for tool in plan["tools"]:
        if tool["name"] == "skills":
            try:
                installed = install_core_helper_skills()
            except (OSError, RuntimeError, ValueError) as exc:
                results.append({"name": "skills", "ok": False, "error": str(exc)})
            else:
                results.append(
                    {
                        "name": "skills",
                        "ok": True,
                        "bundled_skill_count": len(CORE_HELPER_SKILLS),
                        "resolved_skills": dict(sorted(installed.items())),
                    }
                )
            continue
        if tool["name"] == "trufflehog":
            paths = [Path(path) for path in tool.get("install_paths", [])]
            if not paths:
                results.append({"name": "trufflehog", "ok": True, "skipped": True, "reason": "Manageroo ownership was not proven"})
                continue
            try:
                installations = [install_trufflehog_binary(path) for path in paths]
            except (OSError, RuntimeError) as exc:
                results.append({"name": "trufflehog", "ok": False, "error": str(exc)})
            else:
                results.append({"name": "trufflehog", "ok": True, "pinned_version": TRUFFLEHOG_VERSION, "installations": installations})
            continue
        if tool["name"] == "autoreview":
            unsafe_destinations = list(tool.get("unsafe_destinations", []))
            if unsafe_destinations:
                results.append(
                    {
                        "name": "autoreview",
                        "ok": False,
                        "error": "Unsafe AUTOREVIEW destination rejected; no files were changed.",
                        "unsafe_destinations": unsafe_destinations,
                    }
                )
                continue
            results.append(_update_autoreview(tool.get("installation_records", [])))
            continue
        commands = tool.get("commands", [])
        if not commands:
            results.append(
                {
                    "name": tool["name"],
                    "ok": True,
                    "skipped": True,
                    "reason": "no safe automatic update command for the detected installation",
                }
            )
            continue
        if tool["name"] == "clawpatch-supervise":
            executable = shutil.which("clawpatch-supervise")
            try:
                if not executable:
                    raise SafetyError(
                        "The planned standalone supervisor executable is no longer available."
                    )
                with supervisor_runtime_lock(executable):
                    command_results: list[dict[str, Any]] = []
                    gate_ready = supervisor_runtime_gate_ready(executable)
                    migration_complete = (
                        gate_ready and _supervisor_gate_migration_complete(executable)
                    )
                    if not gate_ready:
                        gate_result = _run(list(commands[0]))
                        command_results.append(gate_result)
                        if not gate_result.get("ok"):
                            results.append(
                                {
                                    "name": "clawpatch-supervise",
                                    "ok": False,
                                    "error": (
                                        "Could not install the shared supervisor runtime gate."
                                    ),
                                    "commands": command_results,
                                }
                            )
                            continue
                        if not supervisor_runtime_gate_ready(executable):
                            results.append(
                                {
                                    "name": "clawpatch-supervise",
                                    "ok": False,
                                    "error": (
                                        "The installed supervisor runtime gate failed verification."
                                    ),
                                    "commands": command_results,
                                }
                            )
                            continue
                    if not migration_complete:
                        blocker = _supervisor_update_blocker(executable)
                        if blocker:
                            results.append(
                                {
                                    "name": "clawpatch-supervise",
                                    "ok": False,
                                    "error": blocker,
                                    "commands": command_results,
                                }
                            )
                            continue
                        _record_supervisor_gate_migration(executable)
                    command_results.extend(
                        _run(list(command)) for command in commands[1:]
                    )
            except SafetyError as exc:
                results.append(
                    {"name": "clawpatch-supervise", "ok": False, "error": str(exc)}
                )
            else:
                results.append(
                    {
                        "name": "clawpatch-supervise",
                        "ok": all(item.get("ok") for item in command_results),
                        "commands": command_results,
                    }
                )
            continue
        command_results = [_run(list(command)) for command in commands]
        results.append(
            {
                "name": tool["name"],
                "ok": all(item.get("ok") for item in command_results),
                "commands": command_results,
            }
        )
    return {
        "ok": all(item.get("ok") for item in results),
        "executes_changes": True,
        "selected_tools": plan.get("selected_tools", []),
        "results": results,
    }


def format_stack_update(report: dict[str, Any]) -> str:
    if report.get("executes_changes"):
        lines = ["STACK UPDATE RESULTS", ""]
        for item in report.get("results", []):
            label = "OK" if item.get("ok") else "FAIL"
            if item.get("skipped"):
                label = "SKIP"
            lines.append(f"- {label} {item.get('name')}: {item.get('reason', '')}".rstrip())
        return "\n".join(lines) + "\n"
    lines = ["STACK UPDATE PLAN", "", "No changes were made. Pass --apply to execute supported updates.", ""]
    for item in report.get("tools", []):
        state = "installed" if item.get("installed") else "not detected"
        lines.append(f"- {item['name']}: {state}")
        if item.get("note"):
            lines.append(f"  {item['note']}")
        for path in item.get("install_paths", []):
            lines.append(f"  path: {path}")
        for command in item.get("commands", []):
            lines.append("  update: " + " ".join(command))
    return "\n".join(lines) + "\n"
