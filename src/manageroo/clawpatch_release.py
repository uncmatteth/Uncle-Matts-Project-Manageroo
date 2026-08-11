from __future__ import annotations

import shlex
import shutil
import subprocess
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Callable

from .config_lock import config_mutation_lock
from .errors import SafetyError


SUPERVISOR_EXECUTABLE = "clawpatch-supervise"
SUPERVISOR_REPOSITORY = "https://github.com/uncmatteth/clawpatch-supervise"
SUPERVISOR_VERSION = "0.1.34"
SUPERVISOR_GATE_VERSION = "1.0.0"
SUPERVISOR_GATE_VERSION_ARG = "--manageroo-runtime-gate-version"
TRANSIENT_EXIT_CODE = 75


def supervisor_runtime_lock(executable: str) -> AbstractContextManager[None]:
    """Exclude updates while the standalone supervisor executable is active."""
    try:
        active = Path(executable).expanduser().resolve(strict=True)
    except OSError as exc:
        raise SafetyError(
            f"Could not resolve the standalone supervisor for its runtime lock: {exc}"
        ) from exc
    return config_mutation_lock(active, timeout_seconds=0)


def supervisor_runtime_gate_ready(executable: str) -> bool:
    try:
        probe = subprocess.run(
            [executable, SUPERVISOR_GATE_VERSION_ARG],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0 and probe.stdout.strip() == SUPERVISOR_GATE_VERSION


def _supervisor_path(*, which: Callable[[str], str | None] = shutil.which) -> str:
    path = which(SUPERVISOR_EXECUTABLE)
    if path:
        return path
    raise SafetyError(
        "The standalone clawpatch-supervise command is not installed. "
        f"Install version {SUPERVISOR_VERSION} from {SUPERVISOR_REPOSITORY}."
    )


def _verify_supervisor_version(
    executable: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    try:
        result = run(
            [executable, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafetyError(f"Could not verify standalone clawpatch-supervise version: {exc}") from exc
    stdout = result.stdout if isinstance(result.stdout, str) else ""
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    reported = stdout.strip()
    fields = reported.split()
    if result.returncode == 0 and len(fields) == 2:
        program, version = fields
        if program.casefold() in {
            SUPERVISOR_EXECUTABLE.casefold(),
            f"{SUPERVISOR_EXECUTABLE}.exe".casefold(),
        } and version == SUPERVISOR_VERSION:
            return
    detail = stderr.strip() or reported or f"exit {result.returncode}"
    raise SafetyError(
        f"Standalone clawpatch-supervise requires version {SUPERVISOR_VERSION}; "
        f"the installed command reported {detail!r}."
    )


def supervisor_argv(
    repo: Path,
    *,
    branch: str = "auto",
    push_mode: str = "none",
    publish_clawpatch_state: bool = False,
    trusted_host_codex_sandbox_bypass: bool = False,
    fresh: bool = True,
    timeout_minutes: int = 15,
    executable: str = SUPERVISOR_EXECUTABLE,
) -> list[str]:
    if push_mode not in {"none", "each", "final"}:
        raise SafetyError("push_mode must be one of: none, each, final.")
    if timeout_minutes < 1:
        raise SafetyError("timeout_minutes must be at least 1.")
    argv = [
        executable,
        "--repo",
        str(repo.expanduser().resolve()),
        "--branch",
        branch,
        "--push",
        push_mode,
        "--timeout-minutes",
        str(timeout_minutes),
        "--fresh" if fresh else "--resume-stopped",
    ]
    if publish_clawpatch_state:
        argv.append("--publish-clawpatch-state")
    if trusted_host_codex_sandbox_bypass:
        argv.append("--trusted-host-codex-sandbox-bypass")
    return argv


def release_sweep(
    repo: Path,
    *,
    apply: bool = False,
    branch: str = "auto",
    push_mode: str = "none",
    publish_clawpatch_state: bool = False,
    trusted_host_codex_sandbox_bypass: bool = False,
    fresh: bool = True,
    timeout_minutes: int = 15,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    version_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Plan or invoke the separately installed ClawPatch supervisor."""
    executable = _supervisor_path() if apply else SUPERVISOR_EXECUTABLE
    argv = supervisor_argv(
        repo,
        branch=branch,
        push_mode=push_mode,
        publish_clawpatch_state=publish_clawpatch_state,
        trusted_host_codex_sandbox_bypass=trusted_host_codex_sandbox_bypass,
        fresh=fresh,
        timeout_minutes=timeout_minutes,
        executable=executable,
    )
    report: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "adapter": "standalone-clawpatch-supervise",
        "repository": SUPERVISOR_REPOSITORY,
        "required_version": SUPERVISOR_VERSION,
        "command": argv,
        "exit_code": 0,
    }
    if not apply:
        return report

    _verify_supervisor_version(executable, run=version_run)

    def invoke() -> subprocess.CompletedProcess[str]:
        try:
            return run(
                argv,
                cwd=repo.expanduser().resolve(),
                text=True,
                check=False,
                shell=False,
            )
        except OSError as exc:
            raise SafetyError(f"Could not start standalone clawpatch-supervise: {exc}") from exc

    if supervisor_runtime_gate_ready(executable):
        result = invoke()
    else:
        with supervisor_runtime_lock(executable):
            result = invoke()
    report["exit_code"] = int(result.returncode)
    report["ok"] = result.returncode == 0
    report["transient"] = result.returncode == TRANSIENT_EXIT_CODE
    return report


def supervisor_state_root(
    repo: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Path:
    """Ask the standalone tool for its state root without duplicating path rules."""
    executable = _supervisor_path()
    resolved_repo = repo.expanduser().resolve()
    argv = [executable, "--repo", str(resolved_repo), "--print-state-path"]
    try:
        result = run(
            argv,
            cwd=resolved_repo,
            text=True,
            capture_output=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SafetyError(f"Could not query standalone clawpatch-supervise state: {exc}") from exc
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 1:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise SafetyError(f"Standalone clawpatch-supervise state query failed: {detail}")
    path = Path(lines[0]).expanduser()
    if not path.is_absolute():
        raise SafetyError("Standalone clawpatch-supervise returned a non-absolute state path.")
    resolved = path.resolve()
    if resolved == resolved_repo or resolved_repo in resolved.parents:
        raise SafetyError("Standalone clawpatch-supervise state must remain outside the target repository.")
    return resolved


def format_release_sweep(report: dict[str, Any]) -> str:
    command = report.get("command")
    rendered = shlex.join(command) if isinstance(command, list) else ""
    if not report.get("apply"):
        return (
            "CLAWPATCH SUPERVISOR: PLAN\n"
            f"standalone: {report.get('repository')} @ {report.get('required_version')}\n"
            f"$ {rendered}\n"
        )
    if report.get("ok"):
        return "CLAWPATCH SUPERVISOR: COMPLETE\n"
    label = "RETRYABLE STOP" if report.get("transient") else "STOPPED"
    return f"CLAWPATCH SUPERVISOR: {label}\nexit code: {report.get('exit_code')}\n"
