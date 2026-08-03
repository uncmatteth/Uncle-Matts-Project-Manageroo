from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from .branding import PROJECT_DIR
from .config import load_config
from .errors import MANAGEROOError, SafetyError
from .gates import GateRunner, gates_from_config
from .policy import CommandPolicy
from .runner import CommandRunner
from .util import atomic_write_json, utc_now


MINIMUM_CLAWPATCH_VERSION = (0, 7, 2)
CLAWPATCH_CHILD_WATCHDOG_SECONDS = 900
CLAWPATCH_TRANSIENT_MAX_ATTEMPTS = 3
RELEASE_PROGRESS_VERSION = 1
LIFECYCLE = (
    "repository/process/Git preflight -> clawpatch status --json -> stale-lock cleanup when proven -> "
    "clean repository baseline gates -> clawpatch map -> complete review of every pending feature -> "
    "clawpatch next/show -> one fix -> "
    "complete project gates -> exact fixed revalidation -> on retryable failure preserve/reopen/retry "
    "the same finding until fixed or a non-retryable blocker stops it -> exact-path commit/push when authorized -> repeat the "
    "open queue -> final closure"
)
_FINDING_ID = re.compile(r"^fnd_[A-Za-z0-9_.-]+$")
_SUPERVISOR_UPGRADE_PATHS = frozenset(
    {
        "BUILD-VALIDATION.json",
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/ENFORCEMENT_MATRIX.md",
        "docs/EXTERNAL_INTEGRATIONS.md",
        "docs/LIMITATIONS.md",
        "docs/SOLO_OPERATOR_MODE.md",
        "src/manageroo/clawpatch_external.py",
        "src/manageroo/clawpatch_release.py",
        "src/manageroo/runner.py",
        "tests/test_clawpatch_release_sweep.py",
        "tests/test_external_clawpatch_supervisor.py",
        "tests/test_final_clawpatch_regressions.py",
    }
)


class _UnresolvedFinding(SafetyError):
    def __init__(
        self,
        message: str,
        *,
        finding_id: str,
        outcome: str | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.finding_id = finding_id
        self.outcome = outcome
        self.retryable = retryable


class _MissingFinding(SafetyError):
    def __init__(self, message: str, *, finding_id: str) -> None:
        super().__init__(message)
        self.finding_id = finding_id


def _release_clawpatch_env(
    *,
    trusted_host_codex_sandbox_bypass: bool,
    child_timeout_seconds: int = CLAWPATCH_CHILD_WATCHDOG_SECONDS,
) -> dict[str, str]:
    if child_timeout_seconds < 60:
        raise SafetyError("Clawpatch child timeout must be at least 60 seconds.")
    child_env = dict(os.environ)
    child_env["CLAWPATCH_CODEX_TIMEOUT_MS"] = str(child_timeout_seconds * 1_000)
    child_env["MANAGEROO_CLAWPATCH_CHILD_TIMEOUT_SECONDS"] = str(child_timeout_seconds)
    child_env.pop("CLAWPATCH_CODEX_SANDBOX", None)
    if trusted_host_codex_sandbox_bypass:
        child_env["CLAWPATCH_CODEX_SANDBOX"] = "bypass"
    return child_env


def _child_timeout_seconds(env: dict[str, str]) -> int:
    raw = env.get("MANAGEROO_CLAWPATCH_CHILD_TIMEOUT_SECONDS")
    if raw is None:
        return CLAWPATCH_CHILD_WATCHDOG_SECONDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise SafetyError("Manageroo received an invalid Clawpatch child timeout.") from exc
    if value < 60:
        raise SafetyError("Clawpatch child timeout must be at least 60 seconds.")
    return value


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
    kill_process_group: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = _platform_command(argv, platform_name=os.name)
    if kill_process_group:
        result = CommandRunner().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout,
            env=env,
            kill_process_group=True,
        )
        output = result.stdout
        if result.stderr:
            output = output + ("\n" if output else "") + result.stderr
        if result.timed_out:
            output = output + ("\n" if output else "") + "TIMEOUT"
        return subprocess.CompletedProcess(command, result.exit_code, output, None)
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return subprocess.CompletedProcess(command, 124, output + "\nTIMEOUT", None)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, str(exc), None)


def _platform_command(argv: list[str], *, platform_name: str) -> list[str]:
    command = list(argv)
    if platform_name == "nt" and command:
        executable = PureWindowsPath(command[0]).name.lower()
        if executable in {"clawpatch", "clawpatch.exe", "clawpatch.cmd", "clawpatch.bat"}:
            resolved = shutil.which(command[0]) or shutil.which("clawpatch")
            if resolved:
                command[0] = resolved
    return command


def _must_run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
) -> str:
    result = _run(argv, cwd=cwd, timeout=timeout, env=env)
    if result.returncode:
        raise SafetyError(
            f"command: {shlex.join(argv)}\nexit code: {result.returncode}\n"
            f"failed requirement: command must exit 0\noutput:\n{result.stdout[-6000:]}"
        )
    return result.stdout


def _parse_json_output(output: str, *, command: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        value = None
        decoder = json.JSONDecoder()
        candidates: list[dict[str, Any]] = []
        for match in re.finditer(r"(?m)^[ \t]*(\{)", output):
            try:
                candidate, _end = decoder.raw_decode(output, match.start(1))
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                candidates.append(candidate)
        if len(candidates) == 1:
            value = candidates[0]
        elif len(candidates) > 1:
            raise SafetyError(
                f"Clawpatch {command} returned multiple ambiguous JSON objects:\n{output[-4000:]}"
            ) from exc
        if value is None:
            raise SafetyError(f"Clawpatch {command} did not return valid JSON:\n{output[-4000:]}") from exc
    if not isinstance(value, dict):
        raise SafetyError(f"Clawpatch {command} returned an unexpected JSON value.")
    return value


def _git_root(repo: Path) -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise SafetyError("Clawpatch release sweep requires an existing Git repository.")
    return Path(result.stdout.strip()).resolve()


def _git_text(repo: Path, argv: list[str]) -> str:
    return _must_run(argv, cwd=repo, timeout=600).strip()


def _require_branch(repo: Path, expected: str, *, phase: str) -> None:
    current = _git_text(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if current != expected:
        raise SafetyError(
            f"Git branch changed during Clawpatch {phase}; expected {expected!r}, found {current!r}."
        )


def _status_paths(repo: Path) -> list[str]:
    output = _must_run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--no-renames", "-z"],
        cwd=repo,
        timeout=120,
    )
    paths: list[str] = []
    for record in output.split("\0"):
        if not record:
            continue
        if len(record) < 4:
            raise SafetyError("Git returned malformed status output.")
        paths.append(record[3:])
    return sorted(set(paths))


def _source_paths(repo: Path) -> list[str]:
    return [path for path in _status_paths(repo) if path != ".clawpatch" and not path.startswith(".clawpatch/")]


def _command_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _is_clawpatch_argv(argv: list[str]) -> bool:
    if not argv:
        return False
    commands = {
        "clawpatch",
        "clawpatch.exe",
        "clawpatch.cmd",
        "clawpatch.bat",
        "clawpatch-supervise",
        "clawpatch-supervise.exe",
    }
    first = _command_name(argv[0])
    if first in commands:
        return True
    interpreters = {
        "node",
        "node.exe",
        "bun",
        "bun.exe",
        "python",
        "python.exe",
        "python3",
        "python3.exe",
    }
    if first not in interpreters:
        return False
    if len(argv) >= 3 and argv[1] == "-m":
        return argv[2] == "manageroo.clawpatch_external"
    script = next((value for value in argv[1:4] if not value.startswith("-")), "")
    return _command_name(script) in commands


def _active_clawpatch_processes(repo: Path) -> list[dict[str, Any]]:
    root = repo.resolve()
    found: list[dict[str, Any]] = []
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                argv = [
                    value.decode("utf-8", "replace")
                    for value in (entry / "cmdline").read_bytes().split(b"\0")
                    if value
                ]
                if not _is_clawpatch_argv(argv):
                    continue
                cmdline = " ".join(argv)
                cwd = (entry / "cwd").resolve()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if cwd == root:
                found.append({"pid": int(entry.name), "cwd": str(cwd), "command": cmdline.strip()})
        return found
    if os.name == "nt":
        return _windows_clawpatch_processes(root)
    result = _run(["ps", "-eo", "pid=,command="], cwd=root, timeout=30)
    if result.returncode:
        raise SafetyError("Could not prove that no other Clawpatch process is active.")
    for line in result.stdout.splitlines():
        if "clawpatch" in line.lower():
            found.append({"pid": line.strip().split(maxsplit=1)[0], "cwd": "unknown", "command": line.strip()})
    return found


def _windows_clawpatch_processes(root: Path) -> list[dict[str, Any]]:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        raise SafetyError("Could not inspect live Clawpatch processes on Windows.")
    script = (
        "$rows = Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $PID -and $_.CommandLine -and "
        "$_.CommandLine -match '(?i)(^|[\\\\/\\s])clawpatch(?:\\.cmd|\\.exe|\\.js)?(?:\\s|$)' }; "
        "$rows | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    result = _run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=root,
        timeout=30,
    )
    if result.returncode:
        raise SafetyError("Could not inspect live Clawpatch processes on Windows.")
    if not result.stdout.strip():
        return []
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SafetyError("Windows returned malformed Clawpatch process data.") from exc
    rows = parsed if isinstance(parsed, list) else [parsed]
    found: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise SafetyError("Windows returned malformed Clawpatch process data.")
        found.append(
            {
                "pid": row.get("ProcessId"),
                "cwd": "unknown; Windows process inspection is conservative",
                "command": str(row.get("CommandLine") or "").strip(),
            }
        )
    return found


def _require_no_process(repo: Path) -> None:
    active = _active_clawpatch_processes(repo)
    if active:
        raise SafetyError(f"A Clawpatch process is already active for this repository: {active}")


def _version_tuple(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise SafetyError(f"Could not read the installed Clawpatch version from: {text.strip()!r}")
    return tuple(int(value) for value in match.groups())


def _clawpatch_version(repo: Path) -> str:
    if not shutil.which("clawpatch"):
        raise SafetyError("Clawpatch is not installed or is not available on PATH.")
    text = _must_run(["clawpatch", "--version"], cwd=repo, timeout=30).strip()
    if _version_tuple(text) < MINIMUM_CLAWPATCH_VERSION:
        raise SafetyError("Clawpatch 0.7.2 or newer is required.")
    return text


def _run_clawpatch(
    repo: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    _require_no_process(repo)
    resolved_timeout = _child_timeout_seconds(env) if timeout is None else timeout
    return _run(
        argv,
        cwd=repo,
        timeout=resolved_timeout,
        env=env,
        kill_process_group=True,
    )


def _must_clawpatch(
    repo: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    phase: str | None = None,
    current: int | str = "?",
    total: int | str = "?",
    finding_id: str = "",
) -> str:
    resolved_timeout = _child_timeout_seconds(env) if timeout is None else timeout
    command_phase = phase or _clawpatch_command_phase(argv)
    for attempt in range(1, CLAWPATCH_TRANSIENT_MAX_ATTEMPTS + 1):
        if progress is not None:
            progress(
                {
                    "phase": command_phase,
                    "current": current,
                    "total": total,
                    "finding_id": finding_id,
                    "command": shlex.join(argv),
                    "attempt": attempt,
                    "max_attempts": CLAWPATCH_TRANSIENT_MAX_ATTEMPTS,
                }
            )
        result = _run_clawpatch(repo, argv, env=env, timeout=resolved_timeout)
        if not result.returncode:
            return result.stdout
        output = result.stdout or ""
        if (
            result.returncode == 1
            and len(argv) >= 4
            and argv[1] == "show"
            and "finding not found:" in output.casefold()
        ):
            try:
                missing_id = argv[argv.index("--finding") + 1]
            except (ValueError, IndexError) as exc:
                raise SafetyError("Clawpatch show reported a missing finding without an ID.") from exc
            raise _MissingFinding(
                f"Clawpatch finding no longer exists: {missing_id}",
                finding_id=missing_id,
            )
        if result.returncode == 124:
            raise SafetyError(
                f"phase: Clawpatch command\ncommand: {shlex.join(argv)}\nfinding ID: "
                f"{finding_id or 'N/A'}\nexit code: 124\nfailed requirement: the "
                f"{resolved_timeout}-second child watchdog expired; timed-out commands are not retried\n"
                f"changed source paths: {_source_paths(repo)}\noutput:\n{output[-6000:]}"
            )
        if result.returncode in {1, 5, 6} and attempt < CLAWPATCH_TRANSIENT_MAX_ATTEMPTS:
            time.sleep(2 ** (attempt - 1))
            continue
        raise SafetyError(
            f"phase: Clawpatch command\ncommand: {shlex.join(argv)}\nfinding ID: "
            f"{finding_id or 'N/A'}\n"
            f"exit code: {result.returncode}\nfailed requirement: command must exit 0 "
            f"after {attempt} attempts\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{output[-6000:]}"
        )
    raise AssertionError("bounded Clawpatch retry loop exited unexpectedly")


def _clawpatch_command_phase(argv: list[str]) -> str:
    command = argv[1] if len(argv) > 1 else "clawpatch"
    if command == "clean-locks":
        return "lock-cleanup"
    if command == "review" and "--dry-run" in argv:
        return "review-verification"
    if command == "next":
        return "queue"
    return command


def _json_clawpatch(
    repo: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    phase: str | None = None,
    current: int | str = "?",
    total: int | str = "?",
    finding_id: str = "",
) -> dict[str, Any]:
    output = _must_clawpatch(
        repo,
        argv,
        env=env,
        timeout=timeout,
        progress=progress,
        phase=phase,
        current=current,
        total=total,
        finding_id=finding_id,
    )
    return _parse_json_output(output, command=" ".join(argv[1:]))


def _next_finding(
    repo: Path,
    *,
    env: dict[str, str],
    progress: Callable[[dict[str, Any]], None] | None = None,
    current: int | str = "?",
    total: int | str = "?",
) -> tuple[str | None, dict[str, Any]]:
    payload = _json_clawpatch(
        repo,
        ["clawpatch", "next", "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    finding = payload.get("finding")
    if finding is None:
        return None, payload
    if not isinstance(finding, dict):
        raise SafetyError("Clawpatch next returned a malformed finding value.")
    finding_id = finding.get("id")
    if not isinstance(finding_id, str) or not _FINDING_ID.fullmatch(finding_id):
        raise SafetyError("Clawpatch next returned no valid finding ID.")
    if finding.get("status") != "open":
        raise SafetyError(f"Clawpatch next returned non-open finding {finding_id}.")
    expected_next = f"clawpatch show --finding {finding_id}"
    if payload.get("next") != expected_next:
        raise SafetyError(
            f"Clawpatch next returned an unexpected inspection command for {finding_id}."
        )
    return finding_id, payload


def _show_finding(
    repo: Path,
    finding_id: str,
    *,
    env: dict[str, str],
    required_status: str | None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    current: int | str = "?",
    total: int | str = "?",
) -> dict[str, Any]:
    payload = _json_clawpatch(
        repo,
        ["clawpatch", "show", "--finding", finding_id, "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
        finding_id=finding_id,
    )
    finding = payload.get("finding")
    if not isinstance(finding, dict) or finding.get("id") != finding_id:
        raise SafetyError(f"Clawpatch show returned the wrong finding for {finding_id}.")
    if required_status is not None and finding.get("status") != required_status:
        raise SafetyError(
            f"Clawpatch show requires {finding_id} to have status {required_status!r}."
        )
    validation = payload.get("validation")
    if not isinstance(validation, list) or any(not isinstance(item, str) for item in validation):
        raise SafetyError(f"Clawpatch show returned malformed validation data for {finding_id}.")
    patch_attempts = payload.get("patchAttempts")
    if not isinstance(patch_attempts, list):
        raise SafetyError(f"Clawpatch show returned malformed patch attempts for {finding_id}.")
    return payload


def _finding_from_fix_argv(argv: list[str]) -> str:
    if len(argv) < 2 or argv[1] != "fix":
        raise SafetyError("Expected Clawpatch to direct a fix command.")
    try:
        value = argv[argv.index("--finding") + 1]
    except (ValueError, IndexError) as exc:
        raise SafetyError("Clawpatch fix command did not name a finding.") from exc
    if not _FINDING_ID.fullmatch(value):
        raise SafetyError(f"Clawpatch fix command returned an invalid finding ID: {value!r}")
    return value


def _with_json(argv: list[str]) -> list[str]:
    return list(argv) if "--json" in argv else [*argv, "--json"]


def _fix_command(repo: Path, argv: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    finding_id = _finding_from_fix_argv(argv)
    command = _with_json(argv)
    result = _run_clawpatch(
        repo,
        command,
        env=env or dict(os.environ),
    )
    if result.returncode:
        requirement = "clawpatch fix validation passed" if result.returncode == 6 else "clawpatch fix exited 0"
        message = (
            f"phase: fix\ncommand: {shlex.join(command)}\nfinding ID: {finding_id}\n"
            f"exit code: {result.returncode}\nfailed requirement: {requirement}\n"
            f"changed source paths: {_source_paths(repo) if repo.exists() else []}\n"
            f"output:\n{result.stdout[-6000:]}"
        )
        retry_outcomes = {
            1: "provider-failed",
            5: "provider-quota",
            6: "fix-validation-failed",
            124: "timeout",
        }
        if result.returncode in retry_outcomes:
            raise _UnresolvedFinding(
                message,
                finding_id=finding_id,
                outcome=retry_outcomes[result.returncode],
                retryable=result.returncode not in {1, 5, 124},
            )
        raise SafetyError(message)
    payload = _parse_json_output(result.stdout, command="fix")
    if payload.get("finding") != finding_id:
        raise SafetyError(f"Clawpatch fix returned the wrong finding; expected {finding_id!r}.")
    if payload.get("status") != "applied":
        raise SafetyError(f"Clawpatch fix did not apply a validated patch for {finding_id}.")
    patch_attempt = payload.get("patchAttempt")
    if not isinstance(patch_attempt, str) or not patch_attempt.strip():
        raise SafetyError("Clawpatch fix returned no valid patch-attempt ID.")
    payload["patchAttempt"] = patch_attempt.strip()
    return payload


def _patch_attempt_from_show(
    show_payload: dict[str, Any], patch_attempt_id: str, finding_id: str
) -> dict[str, Any]:
    patch_attempts = show_payload.get("patchAttempts")
    if not isinstance(patch_attempts, list):
        raise SafetyError(f"Clawpatch show returned no patch-attempt list for {finding_id}.")
    value = next(
        (
            candidate
            for candidate in patch_attempts
            if isinstance(candidate, dict) and candidate.get("patchAttemptId") == patch_attempt_id
        ),
        None,
    )
    if not isinstance(value, dict):
        raise SafetyError(f"Could not read Clawpatch patch-attempt record {patch_attempt_id}.")
    finding_ids = value.get("findingIds")
    if not isinstance(finding_ids, list) or finding_id not in finding_ids:
        raise SafetyError(f"Clawpatch patch-attempt record does not belong to {finding_id}.")
    files = value.get("filesChanged")
    if not isinstance(files, list) or any(not isinstance(path, str) or not path for path in files):
        raise SafetyError("Clawpatch patch-attempt filesChanged is malformed.")
    return value


def _validate_attempt_paths(repo: Path, files: list[str]) -> None:
    _validate_attempt_paths_syntax(files)
    current = _source_paths(repo)
    if sorted(files) != current:
        raise SafetyError(
            "Changed source paths do not exactly match the current Clawpatch patch attempt; "
            f"attempt={sorted(files)!r}, current={current!r}."
        )


def _run_project_gates(repo: Path, *, finding_id: str) -> list[dict[str, Any]]:
    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.is_file():
        raise SafetyError("The repository has no Manageroo gate configuration; complete validation is ambiguous.")
    gates = []
    log_root = repo / PROJECT_DIR / "cache" / "clawpatch-release-logs"
    try:
        config = load_config(repo)
        gates = gates_from_config(config)
        if not gates:
            raise SafetyError("The repository has no configured validation gates; complete validation is ambiguous.")
        runner = GateRunner(
            CommandRunner(log_root=log_root),
            CommandPolicy(tuple(config["safety"]["allowed_programs"])),
            log_root,
        )
        return [item.to_dict() for item in runner.run(gates, repo, require_one=True)]
    except MANAGEROOError as exc:
        diagnostics = []
        for gate in gates:
            log_path = log_root / f"gate-{gate.id}.json"
            try:
                result = json.loads(log_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            exit_code = result.get("exit_code")
            timed_out = result.get("timed_out") is True
            if exit_code == 0 and not timed_out:
                continue
            output = "\n".join(
                value for value in (result.get("stdout"), result.get("stderr"))
                if isinstance(value, str) and value
            )
            diagnostics.append(
                f"gate: {gate.id}\ncommand: {shlex.join(gate.argv)}\n"
                f"exit code: {exit_code}\noutput:\n{output[-6000:]}"
            )
        detail = "\n\n".join(diagnostics) or str(exc)
        raise SafetyError(
            f"phase: project validation\ncommand: configured Manageroo gates\nfinding ID: {finding_id}\n"
            f"exit code: nonzero\nfailed requirement: complete repository validation must pass\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{detail}"
        ) from exc


def _source_state_fingerprint(repo: Path) -> dict[str, Any]:
    paths = _source_paths(repo)
    diff = _must_run(
        ["git", "diff", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--", *paths],
        cwd=repo,
        timeout=120,
    ) if paths else ""
    untracked = sorted(
        path
        for path in _must_run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", *paths],
            cwd=repo,
            timeout=120,
        ).split("\0")
        if path
    ) if paths else []
    untracked_hashes = {
        path: _git_text(repo, ["git", "hash-object", "--no-filters", "--", path])
        for path in untracked
    }
    return {"paths": paths, "diff": diff, "untracked": untracked_hashes}


def _revalidation_payload(
    repo: Path,
    finding_id: str,
    *,
    env: dict[str, str],
    progress: Callable[[dict[str, Any]], None] | None = None,
    phase: str = "revalidate",
    current: int | str = "?",
    total: int | str = "?",
) -> tuple[list[str], dict[str, Any], str]:
    argv = ["clawpatch", "revalidate", "--finding", finding_id, "--json"]
    payload = _json_clawpatch(
        repo,
        argv,
        env=env,
        progress=progress,
        phase=phase,
        current=current,
        total=total,
        finding_id=finding_id,
    )
    outcome = payload.get("outcome")
    if payload.get("finding") != finding_id or outcome not in {
        "fixed",
        "open",
        "uncertain",
        "false-positive",
    }:
        raise SafetyError(
            f"phase: revalidation\ncommand: {shlex.join(argv)}\nfinding ID: {finding_id}\n"
            "exit code: 0\nfailed requirement: matching finding and a documented outcome\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{json.dumps(payload, sort_keys=True)}"
        )
    return argv, payload, str(outcome)


def _revalidate(
    repo: Path,
    finding_id: str,
    *,
    env: dict[str, str],
    expected_paths: list[str],
    progress: Callable[[dict[str, Any]], None] | None = None,
    current: int | str = "?",
    total: int | str = "?",
) -> dict[str, Any]:
    if sorted(expected_paths) != _source_paths(repo):
        raise SafetyError(
            "Revalidation source paths no longer match the validated Clawpatch patch attempt."
        )
    before = _source_state_fingerprint(repo)
    argv, payload, outcome = _revalidation_payload(
        repo,
        finding_id,
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    if outcome == "uncertain" and env.get("CLAWPATCH_CODEX_SANDBOX") in {None, "read-only"}:
        escalated_env = dict(env)
        escalated_env["CLAWPATCH_CODEX_SANDBOX"] = "workspace-write"
        _argv, escalated, escalated_outcome = _revalidation_payload(
            repo,
            finding_id,
            env=escalated_env,
            progress=progress,
            phase="revalidate-escalated",
            current=current,
            total=total,
        )
        after = _source_state_fingerprint(repo)
        if after != before:
            raise _UnresolvedFinding(
                f"phase: revalidation\ncommand: {shlex.join(argv)}\nfinding ID: {finding_id}\n"
                "exit code: 0\nfailed requirement: workspace-write revalidation must not alter source\n"
                f"changed source paths: {_source_paths(repo)}",
                finding_id=finding_id,
                outcome="revalidation-mutated-source",
                retryable=False,
            )
        payload = dict(escalated)
        payload["managerooSandboxEscalated"] = True
        payload["managerooInitialOutcome"] = outcome
        outcome = escalated_outcome
    if outcome != "fixed":
        raise _UnresolvedFinding(
            f"phase: revalidation\ncommand: {shlex.join(argv)}\nfinding ID: {finding_id}\n"
            f"exit code: 0\nfailed requirement: exact lowercase outcome fixed; received {outcome}\n"
            f"changed source paths: {_source_paths(repo)}\n"
            f"output:\n{json.dumps(payload, sort_keys=True)}",
            finding_id=finding_id,
            outcome=str(outcome),
            retryable=outcome == "open",
        )
    return payload


def _preserve_unresolved_source(repo: Path, finding_id: str, reason: str) -> dict[str, Any]:
    paths = _source_paths(repo)
    if not paths:
        return {"created": False, "ref": "", "sha": "", "paths": []}
    message = f"manageroo clawpatch unresolved {finding_id}: {reason}"
    _must_run(
        ["git", "stash", "push", "--include-untracked", "--message", message, "--", *paths],
        cwd=repo,
        timeout=300,
    )
    if _source_paths(repo):
        raise SafetyError(f"Could not preserve and clear unresolved source changes for {finding_id}.")
    identity = _git_text(repo, ["git", "stash", "list", "-1", "--format=%gd|%H"])
    ref, separator, sha = identity.partition("|")
    if not separator or not ref or not sha:
        raise SafetyError(f"Could not verify the preserved Git stash for {finding_id}.")
    return {"created": True, "ref": ref, "sha": sha, "paths": paths, "message": message}


def _retry_attempt_fingerprint(
    repo: Path,
    *,
    message: str,
    outcome: str,
    preserved: dict[str, Any],
) -> str:
    patch_text = ""
    if preserved.get("created"):
        ref = str(preserved.get("ref") or "")
        if not re.fullmatch(r"stash@\{\d+\}", ref):
            raise SafetyError("Cannot fingerprint an invalid preserved Clawpatch stash reference.")
        patch_text = _must_run(
            ["git", "stash", "show", "--patch", "--include-untracked", "--binary", ref],
            cwd=repo,
            timeout=120,
        )
    evidence = {
        "outcome": outcome,
        "failure": " ".join(message.split()),
        "paths": sorted(str(path) for path in (preserved.get("paths") or [])),
        "patch": patch_text,
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_retry_progress(previous: str, current: str, finding_id: str) -> None:
    if previous and previous == current:
        raise SafetyError(
            f"Clawpatch repeated the identical source repair and identical failure for {finding_id}. "
            "The finding remains open; Manageroo stopped instead of repeating a no-progress loop."
        )


def _latest_preserved_source(repo: Path, finding_id: str) -> dict[str, Any]:
    output = _git_text(repo, ["git", "stash", "list", "--format=%gd%x09%H%x09%gs"])
    marker = f"manageroo clawpatch unresolved {finding_id}:"
    for line in output.splitlines():
        ref, separator, remainder = line.partition("\t")
        sha, second_separator, subject = remainder.partition("\t")
        if not separator or not second_separator or marker not in subject:
            continue
        paths = sorted(
            path
            for path in _must_run(
                ["git", "stash", "show", "--name-only", "--format=", ref],
                cwd=repo,
                timeout=120,
            ).splitlines()
            if path
        )
        return {"created": True, "ref": ref, "sha": sha, "paths": paths, "message": subject}
    return {"created": False, "ref": "", "sha": "", "paths": []}


def _retry_failure_context(message: str, preserved: dict[str, Any]) -> str:
    if not preserved.get("created"):
        return message
    ref = str(preserved.get("ref") or "")
    paths = preserved.get("paths") or []
    return (
        f"{message}\nPrevious Clawpatch-owned source attempt is preserved at {ref}. "
        f"Its changed paths were: {', '.join(str(path) for path in paths)}. "
        f"Inspect it read-only with git stash show --patch {ref}; use that evidence "
        "to avoid repeating the same incomplete repair, but do not apply it blindly."
    )


def _release_progress_path(repo: Path) -> Path:
    return repo / PROJECT_DIR / "cache" / "clawpatch-release-progress.json"


def _write_release_progress(
    repo: Path,
    *,
    finding_id: str,
    branch: str,
    head_before: str,
    retry_count: int,
    phase: str,
    last_stash_ref: str = "",
    last_stash_paths: list[str] | None = None,
    last_attempt_fingerprint: str = "",
) -> dict[str, Any]:
    if not _FINDING_ID.fullmatch(finding_id):
        raise SafetyError(f"Cannot checkpoint invalid Clawpatch finding ID {finding_id!r}.")
    stash_paths = list(last_stash_paths or [])
    if (
        not branch
        or not head_before
        or retry_count < 0
        or not phase
        or (last_stash_ref and not re.fullmatch(r"stash@\{\d+\}", last_stash_ref))
        or any(not isinstance(path, str) or not path for path in stash_paths)
        or (
            last_attempt_fingerprint
            and not re.fullmatch(r"[0-9a-f]{64}", last_attempt_fingerprint)
        )
    ):
        raise SafetyError("Cannot checkpoint malformed Clawpatch release progress.")
    progress = {
        "version": RELEASE_PROGRESS_VERSION,
        "repo": str(repo.resolve()),
        "finding_id": finding_id,
        "branch": branch,
        "head_before": head_before,
        "retry_count": retry_count,
        "last_stash_ref": last_stash_ref,
        "last_stash_paths": stash_paths,
        "last_attempt_fingerprint": last_attempt_fingerprint,
        "phase": phase,
        "updated_at": utc_now(),
    }
    atomic_write_json(_release_progress_path(repo), progress)
    return progress


def _load_release_progress(repo: Path) -> dict[str, Any] | None:
    path = _release_progress_path(repo)
    if not path.is_file():
        return None
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyError(f"Clawpatch release progress is unreadable: {path}") from exc
    if not isinstance(progress, dict):
        raise SafetyError("Clawpatch release progress is malformed.")
    progress = dict(progress)
    legacy_cycle_count = progress.pop("cycle_count", 1)
    progress.setdefault("last_stash_ref", "")
    progress.setdefault("last_stash_paths", [])
    progress.setdefault("last_attempt_fingerprint", "")
    required_strings = ("repo", "finding_id", "branch", "head_before", "phase", "updated_at")
    if (
        progress.get("version") != RELEASE_PROGRESS_VERSION
        or any(not isinstance(progress.get(field), str) or not progress[field] for field in required_strings)
        or not _FINDING_ID.fullmatch(str(progress.get("finding_id", "")))
        or isinstance(progress.get("retry_count"), bool)
        or not isinstance(progress.get("retry_count"), int)
        or progress["retry_count"] < 0
        or isinstance(legacy_cycle_count, bool)
        or not isinstance(legacy_cycle_count, int)
        or legacy_cycle_count < 1
        or not isinstance(progress.get("last_stash_ref"), str)
        or (
            bool(progress.get("last_stash_ref"))
            and not re.fullmatch(r"stash@\{\d+\}", str(progress["last_stash_ref"]))
        )
        or not isinstance(progress.get("last_stash_paths"), list)
        or any(
            not isinstance(path, str) or not path
            for path in progress.get("last_stash_paths", [])
        )
        or not isinstance(progress.get("last_attempt_fingerprint"), str)
        or (
            bool(progress.get("last_attempt_fingerprint"))
            and not re.fullmatch(r"[0-9a-f]{64}", str(progress["last_attempt_fingerprint"]))
        )
    ):
        raise SafetyError("Clawpatch release progress is malformed.")
    if legacy_cycle_count > 1:
        progress["retry_count"] += (legacy_cycle_count - 1) * 3
    if progress["phase"] in {"fix-attempts-exhausted", "fix-cycle-recovery"}:
        progress["phase"] = "retry"
    if Path(progress["repo"]).resolve() != repo.resolve():
        raise SafetyError("Clawpatch release progress belongs to a different repository.")
    return progress


def _checkpoint_can_follow_supervisor_upgrade(
    repo: Path,
    progress: dict[str, Any],
) -> bool:
    if progress.get("phase") not in {
        "fix",
        "retry",
        "fix-attempts-exhausted",
        "fix-cycle-recovery",
        "no-progress-blocked",
    }:
        return False
    finding_id = progress.get("finding_id")
    old_head = progress.get("head_before")
    if not isinstance(finding_id, str) or not isinstance(old_head, str):
        return False
    current_head = _git_text(repo, ["git", "rev-parse", "HEAD"])
    ancestor = _run(
        ["git", "merge-base", "--is-ancestor", old_head, current_head],
        cwd=repo,
        timeout=60,
    )
    if ancestor.returncode:
        return False
    changed_output = _must_run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", f"{old_head}..{current_head}"],
        cwd=repo,
        timeout=60,
    )
    changed_paths = {line.strip() for line in changed_output.splitlines() if line.strip()}
    if not changed_paths or not changed_paths.issubset(_SUPERVISOR_UPGRADE_PATHS):
        return False
    finding_path = repo / ".clawpatch" / "findings" / f"{finding_id}.json"
    try:
        finding = json.loads(finding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    evidence = finding.get("evidence") if isinstance(finding, dict) else None
    if not isinstance(evidence, list):
        return False
    evidence_paths = {
        item["path"]
        for item in evidence
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    return changed_paths.isdisjoint(evidence_paths)


def _clear_release_progress(repo: Path) -> None:
    _release_progress_path(repo).unlink(missing_ok=True)


def _committed_clawpatch_config(repo: Path) -> str | None:
    current = repo / ".clawpatch" / "config.json"
    if current.is_file():
        return current.read_text(encoding="utf-8")
    result = _run(
        ["git", "show", "HEAD:.clawpatch/config.json"],
        cwd=repo,
        timeout=60,
    )
    return result.stdout if result.returncode == 0 and result.stdout.strip() else None


def _fresh_checkpoint_owned_paths(repo: Path, source_changes: list[str]) -> list[str]:
    checkpoint = _load_release_progress(repo)
    if checkpoint is None or checkpoint.get("phase") != "fix":
        return []
    current_branch = _git_text(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if checkpoint["branch"] != current_branch:
        return []
    current_head = _git_text(repo, ["git", "rev-parse", "HEAD"])
    if checkpoint["head_before"] != current_head and not _checkpoint_can_follow_supervisor_upgrade(
        repo, checkpoint
    ):
        return []
    finding_id = str(checkpoint["finding_id"])
    finding_path = repo / ".clawpatch" / "findings" / f"{finding_id}.json"
    try:
        finding = json.loads(finding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    evidence = finding.get("evidence") if isinstance(finding, dict) else None
    if not isinstance(evidence, list):
        return []
    owned_paths = {
        item["path"]
        for item in evidence
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    changed = set(source_changes)
    if not changed or not changed.issubset(owned_paths):
        return []
    _validate_attempt_paths_syntax(sorted(changed))
    return sorted(changed)


def _validate_attempt_paths_syntax(paths: list[str]) -> None:
    invalid = []
    for path in paths:
        posix = PurePosixPath(path)
        windows = PureWindowsPath(path)
        if (
            not path
            or posix.is_absolute()
            or windows.is_absolute()
            or ".." in posix.parts
            or ".." in windows.parts
            or path == ".clawpatch"
            or path.startswith(".clawpatch/")
        ):
            invalid.append(path)
    if invalid:
        raise SafetyError(
            "Clawpatch patch attempt contains unsafe or state-only paths: " + ", ".join(invalid)
        )


def _discard_checkpoint_owned_source(repo: Path, paths: list[str]) -> None:
    tracked: list[str] = []
    untracked: list[str] = []
    for path in paths:
        output = _must_run(
            ["git", "ls-tree", "--name-only", "-z", "HEAD", "--", path],
            cwd=repo,
            timeout=60,
        )
        if path in output.split("\0"):
            tracked.append(path)
        else:
            untracked.append(path)
    if tracked:
        _must_run(
            ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", *tracked],
            cwd=repo,
            timeout=120,
        )
    for path in untracked:
        candidate = repo / path
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink()
            continue
        if candidate.exists():
            raise SafetyError(
                f"A fresh Clawpatch run cannot safely discard non-file path {path!r}."
            )
    remaining = _source_paths(repo)
    if remaining:
        raise SafetyError(
            "A fresh Clawpatch run could not verify exact cleanup of the interrupted repair: "
            + ", ".join(remaining)
        )


def _prepare_fresh_release(
    repo: Path,
    *,
    env: dict[str, str],
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Delete only Clawpatch run state, preserve project configuration, and initialize again."""
    _require_no_process(repo)
    state_root = repo / ".clawpatch"
    if state_root.is_symlink() or state_root.resolve().parent != repo.resolve():
        raise SafetyError("The .clawpatch state path is not a safe repository-owned directory.")
    source_changes = _source_paths(repo)
    if source_changes:
        checkpoint_owned = _fresh_checkpoint_owned_paths(repo, source_changes)
        if checkpoint_owned != source_changes:
            raise SafetyError(
                "A fresh Clawpatch run refuses unrelated source changes: "
                + ", ".join(source_changes)
            )
        if progress is not None:
            progress(
                {
                    "phase": "fresh-discard",
                    "current": "?",
                    "total": "?",
                    "command": "discard exact interrupted Clawpatch finding files",
                    "attempt": 1,
                    "max_attempts": 1,
                }
            )
        _discard_checkpoint_owned_source(repo, checkpoint_owned)
    config_text = _committed_clawpatch_config(repo)
    if state_root.exists():
        if not state_root.is_dir():
            raise SafetyError("The .clawpatch state path is not a directory.")
        shutil.rmtree(state_root)
    _clear_release_progress(repo)
    (repo / PROJECT_DIR / "cache" / "clawpatch-release-proof.json").unlink(missing_ok=True)
    if progress is not None:
        progress(
            {
                "phase": "fresh",
                "current": "?",
                "total": "?",
                "command": "clawpatch init --json",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    _json_clawpatch(
        repo,
        ["clawpatch", "init", "--json"],
        env=env,
        progress=None,
    )
    if config_text is not None:
        config_path = state_root / "config.json"
        config_path.write_text(config_text, encoding="utf-8")


def _reopen_current_finding(
    repo: Path,
    finding_id: str,
    *,
    env: dict[str, str],
    failure: str = "",
    progress: Callable[[dict[str, Any]], None] | None = None,
    current_number: int | str = "?",
    total: int | str = "?",
) -> dict[str, Any]:
    current = _show_finding(
        repo,
        finding_id,
        env=env,
        required_status=None,
        progress=progress,
        current=current_number,
        total=total,
    )
    finding = current["finding"]
    status = finding.get("status") if isinstance(finding, dict) else None
    if status not in {"open", "uncertain", "fixed"}:
        raise SafetyError(
            f"Clawpatch retry recovery cannot reopen {finding_id} from status {status!r}."
        )
    evidence = " ".join(failure.split())[:1500]
    note = (
        f"Manageroo retry recovery evidence: {evidence}"
        if evidence
        else "Manageroo retry recovery: the previous Clawpatch-owned repair did not reach fixed."
    )
    payload = _json_clawpatch(
        repo,
        [
            "clawpatch",
            "triage",
            "--finding",
            finding_id,
            "--status",
            "open",
            "--note",
            note,
            "--json",
        ],
        env=env,
        progress=progress,
        current=current_number,
        total=total,
        finding_id=finding_id,
    )
    if payload.get("finding") != finding_id or payload.get("status") != "open":
        raise SafetyError(f"Clawpatch did not reopen {finding_id} for retry.")
    current_id, _queue = _next_finding(
        repo,
        env=env,
        progress=progress,
        current=current_number,
        total=total,
    )
    if current_id != finding_id:
        raise SafetyError(
            f"Clawpatch retry recovery expected {finding_id} to remain current, found {current_id!r}."
        )
    return _show_finding(
        repo,
        finding_id,
        env=env,
        required_status="open",
        progress=progress,
        current=current_number,
        total=total,
    )


def _commit_attempt(repo: Path, finding_id: str, files: list[str], *, branch: str) -> str:
    if not files:
        return ""
    _require_branch(repo, branch, phase="source commit")
    _validate_attempt_paths(repo, files)
    _must_run(["git", "add", "--", *files], cwd=repo, timeout=120)
    staged = _must_run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"], cwd=repo, timeout=120
    )
    staged_paths = sorted(path for path in staged.split("\0") if path)
    reported_paths = set(files)
    if any(path not in reported_paths or path.startswith(".clawpatch/") for path in staged_paths):
        raise SafetyError("The staged paths do not exactly match the current Clawpatch patch attempt.")
    if _source_paths(repo) != staged_paths:
        raise SafetyError("The staged repair does not contain every current source change.")
    if not staged_paths:
        return ""
    _must_run(["git", "diff", "--cached", "--check"], cwd=repo, timeout=120)
    _require_branch(repo, branch, phase="source commit")
    _must_run(["git", "commit", "-m", f"clawpatch fix: {finding_id}"], cwd=repo, timeout=300)
    commit = _git_text(repo, ["git", "rev-parse", "HEAD"])
    committed = _git_text(repo, ["git", "show", "--pretty=", "--name-only", "--no-renames", commit]).splitlines()
    if sorted(path for path in committed if path) != staged_paths:
        raise SafetyError("The resulting commit does not contain exactly the verified source repair.")
    return commit


def _push_and_verify(repo: Path, branch: str, *, first: bool) -> None:
    _require_branch(repo, branch, phase="push")
    argv = ["git", "push", "-u", "origin", branch] if first else ["git", "push", "origin", branch]
    _must_run(argv, cwd=repo, timeout=600)
    local = _git_text(repo, ["git", "rev-parse", "HEAD"])
    remote_line = _git_text(repo, ["git", "ls-remote", "origin", f"refs/heads/{branch}"])
    remote = remote_line.split()[0] if remote_line else ""
    if remote != local:
        raise SafetyError(f"Live remote branch SHA {remote!r} does not equal local HEAD {local!r}.")


def _publish_final_state(repo: Path, *, branch: str) -> str:
    state_paths = [path for path in _status_paths(repo) if path == ".clawpatch" or path.startswith(".clawpatch/")]
    if not state_paths:
        return ""
    _require_branch(repo, branch, phase="state publication")
    _must_run(["git", "add", "-A", "--", *state_paths], cwd=repo, timeout=120)
    staged = sorted(
        path
        for path in _must_run(
            ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"], cwd=repo, timeout=120
        ).split("\0")
        if path
    )
    if staged != sorted(state_paths) or any(not path.startswith(".clawpatch/") for path in staged):
        raise SafetyError("Final state commit is not exactly limited to authorized .clawpatch paths.")
    _must_run(["git", "commit", "-m", "clawpatch state: final closure"], cwd=repo, timeout=300)
    return _git_text(repo, ["git", "rev-parse", "HEAD"])


def _execute_fix(
    repo: Path,
    finding_id: str,
    *,
    inspected: dict[str, Any],
    env: dict[str, str],
    push_mode: str,
    branch: str,
    pushed: bool,
    progress: Callable[[dict[str, Any]], None] | None = None,
    current: int | str = "?",
    total: int | str = "?",
) -> tuple[dict[str, Any], bool]:
    if _source_paths(repo):
        raise SafetyError("Pre-existing source changes block the current Clawpatch fix.")
    argv = ["clawpatch", "fix", "--finding", finding_id]
    head_before = _git_text(repo, ["git", "rev-parse", "HEAD"])
    _require_no_process(repo)
    fixed = _fix_command(repo, argv, env=env)
    post_fix_show = _show_finding(repo, finding_id, env=env, required_status="uncertain")
    patch = _patch_attempt_from_show(post_fix_show, str(fixed["patchAttempt"]), finding_id)
    files = [str(path) for path in patch["filesChanged"]]
    _validate_attempt_paths(repo, files)
    try:
        gate_runs = _run_project_gates(repo, finding_id=finding_id)
    except SafetyError as exc:
        raise _UnresolvedFinding(
            str(exc),
            finding_id=finding_id,
            outcome="project-gates-failed",
        ) from exc
    _validate_attempt_paths(repo, files)
    validation = _revalidate(
        repo,
        finding_id,
        env=env,
        expected_paths=files,
        progress=progress,
        current=current,
        total=total,
    )
    commit = _commit_attempt(repo, finding_id, files, branch=branch)
    if push_mode == "each" and commit:
        _push_and_verify(repo, branch, first=not pushed)
        pushed = True
    return {
        "finding_id": finding_id,
        "inspection": inspected,
        "head_before": head_before,
        "patch_attempt": fixed["patchAttempt"],
        "files_changed": files,
        "gate_runs": gate_runs,
        "revalidation": validation,
        "commit": commit,
    }, pushed


def _required_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SafetyError(f"Clawpatch returned a missing or malformed {field!r} value.")
    return value


def _review_completion(
    repo: Path,
    *,
    env: dict[str, str],
    review_limit: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    payload = _json_clawpatch(
        repo,
        [
            "clawpatch",
            "review",
            "--limit",
            str(max(review_limit, 1)),
            "--dry-run",
            "--json",
        ],
        env=env,
        progress=progress,
    )
    if payload.get("dryRun") is not True or _required_int(payload, "wouldReview") != 0:
        raise SafetyError("Clawpatch still has pending or errored features requiring review.")
    return payload


def _review_all_features(
    repo: Path,
    *,
    env: dict[str, str],
    mapped_features: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if mapped_features < 0:
        raise SafetyError("Clawpatch map returned a negative feature count.")
    review_limit = max(mapped_features, 1)
    review = _json_clawpatch(
        repo,
        ["clawpatch", "review", "--limit", str(review_limit), "--json"],
        env=env,
        progress=progress,
    )
    reviewed = _required_int(review, "reviewed")
    findings = _required_int(review, "findings")
    if reviewed < 0 or reviewed > mapped_features or findings < 0:
        raise SafetyError("Clawpatch review returned impossible completion counts.")
    completion = _review_completion(
        repo,
        env=env,
        review_limit=review_limit,
        progress=progress,
    )
    return {"review": review, "completion": completion}


def _final_closure(
    repo: Path,
    *,
    env: dict[str, str],
    push_mode: str,
    branch: str,
    pushed: bool,
    publish_clawpatch_state: bool,
    review_limit: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
    current: int | str = "?",
    total: int | str = "?",
) -> dict[str, Any]:
    _require_no_process(repo)
    review_completion = _review_completion(
        repo,
        env=env,
        review_limit=review_limit,
        progress=progress,
    )
    all_validation = _json_clawpatch(
        repo,
        ["clawpatch", "revalidate", "--all", "--status", "open", "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    report = _json_clawpatch(
        repo,
        ["clawpatch", "report", "--status", "open", "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    if report.get("total") != 0 or report.get("items") != []:
        raise SafetyError("Final Clawpatch report is not exactly total=0 and items=[].")
    uncertain_report = _json_clawpatch(
        repo,
        ["clawpatch", "report", "--status", "uncertain", "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    if uncertain_report.get("total") != 0 or uncertain_report.get("items") != []:
        raise SafetyError("Final Clawpatch report still contains uncertain findings.")
    status = _json_clawpatch(
        repo,
        ["clawpatch", "status", "--json"],
        env=env,
        progress=progress,
        current=current,
        total=total,
    )
    for field in ("openFindings", "activeLocks", "lockFiles"):
        if _required_int(status, field) != 0:
            raise SafetyError(f"Final Clawpatch status requires {field}=0.")
    final_gates = _run_project_gates(repo, finding_id="N/A")
    if _source_paths(repo):
        raise SafetyError(f"Final closure found uncommitted source changes: {_source_paths(repo)}")
    state_commit = ""
    state_paths = [path for path in _status_paths(repo) if path == ".clawpatch" or path.startswith(".clawpatch/")]
    if state_paths and publish_clawpatch_state:
        if push_mode == "none":
            raise SafetyError("Publishing final Clawpatch state requires explicit --push each or --push final authorization.")
        state_commit = _publish_final_state(repo, branch=branch)
    if push_mode == "final" or state_commit:
        _push_and_verify(repo, branch, first=not pushed)
        pushed = True
    if _status_paths(repo):
        raise SafetyError(
            "Final authorized Git worktree is not clean. Manageroo will not auto-publish or discard Clawpatch state: "
            + ", ".join(_status_paths(repo))
        )
    _require_no_process(repo)
    return {
        "all_revalidation": all_validation,
        "review_completion": review_completion,
        "report": report,
        "uncertain_report": uncertain_report,
        "status": status,
        "gate_runs": final_gates,
        "pushed": pushed,
        "state_commit": state_commit,
    }


def release_sweep(
    repo: Path,
    *,
    apply: bool = False,
    branch: str = "auto",
    push_mode: str = "none",
    publish_clawpatch_state: bool = False,
    trusted_host_codex_sandbox_bypass: bool = False,
    fresh: bool = False,
    child_timeout_seconds: int = CLAWPATCH_CHILD_WATCHDOG_SECONDS,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Automate Clawpatch's documented one-finding workflow without automatic triage."""
    root = _git_root(repo)
    if progress is not None:
        progress(
            {
                "phase": "preflight",
                "current": "?",
                "total": "?",
                "command": "clawpatch --version",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    version = _clawpatch_version(root)
    current_branch = _git_text(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head_before = _git_text(root, ["git", "rev-parse", "HEAD"])
    if push_mode not in {"none", "each", "final"}:
        raise SafetyError("push_mode must be one of: none, each, final.")
    report: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "repo": str(root),
        "branch": current_branch,
        "git_head_before": head_before,
        "clawpatch_version": version,
        "lifecycle": LIFECYCLE,
        "push_mode": push_mode,
        "publish_clawpatch_state": publish_clawpatch_state,
        "results": [],
        "false_positives": [],
        "retries": [],
        "stale_refreshes": [],
    }
    if not apply:
        report["planned_branch"] = branch
        return report

    _require_no_process(root)
    env = _release_clawpatch_env(
        trusted_host_codex_sandbox_bypass=trusted_host_codex_sandbox_bypass,
        child_timeout_seconds=child_timeout_seconds,
    )
    if fresh:
        _prepare_fresh_release(root, env=env, progress=progress)
    durable_progress = _load_release_progress(root)
    preexisting_source = _source_paths(root)
    if durable_progress is not None:
        if durable_progress["branch"] != current_branch:
            raise SafetyError(
                "Interrupted Clawpatch release progress is bound to branch "
                f"{durable_progress['branch']!r}, not {current_branch!r}."
            )
        if durable_progress["head_before"] != head_before:
            if _checkpoint_can_follow_supervisor_upgrade(root, durable_progress):
                durable_progress = _write_release_progress(
                    root,
                    finding_id=str(durable_progress["finding_id"]),
                    branch=str(durable_progress["branch"]),
                    head_before=head_before,
                    retry_count=int(durable_progress["retry_count"]),
                    phase=str(durable_progress["phase"]),
                    last_stash_ref=str(durable_progress.get("last_stash_ref", "")),
                    last_stash_paths=list(durable_progress.get("last_stash_paths", [])),
                    last_attempt_fingerprint=str(
                        durable_progress.get("last_attempt_fingerprint", "")
                    ),
                )
            else:
                subject = _git_text(root, ["git", "show", "-s", "--format=%s", "HEAD"])
                expected = f"clawpatch fix: {durable_progress['finding_id']}"
                if preexisting_source or subject != expected:
                    raise SafetyError(
                        "Interrupted Clawpatch release progress no longer matches the current Git HEAD."
                    )
                _clear_release_progress(root)
                durable_progress = None
    if preexisting_source and durable_progress is None:
        raise SafetyError("Clawpatch release sweep found pre-existing source changes: " + ", ".join(preexisting_source))
    selected_branch = current_branch
    if durable_progress is not None and branch not in {"auto", "current", current_branch}:
        raise SafetyError(
            "Cannot create a different branch while resuming interrupted Clawpatch release progress."
        )
    if durable_progress is None and branch == "auto" and current_branch in {"main", "master", "HEAD"}:
        selected_branch = "clawpatch/release-sweep-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
    elif durable_progress is None and branch not in {"auto", "current"}:
        selected_branch = branch
        _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
    elif branch == "current" and current_branch == "HEAD":
        raise SafetyError("--branch current cannot be used from a detached HEAD.")
    if push_mode != "none":
        _must_run(["git", "remote", "get-url", "origin"], cwd=root, timeout=60)

    status = _json_clawpatch(
        root,
        ["clawpatch", "status", "--json"],
        env=env,
        progress=progress,
    )
    if _required_int(status, "activeLocks") or _required_int(status, "lockFiles"):
        _require_no_process(root)
        _json_clawpatch(
            root,
            ["clawpatch", "clean-locks", "--stale-only", "--json"],
            env=env,
            progress=progress,
        )

    if durable_progress is not None and preexisting_source:
        interrupted_id = str(durable_progress["finding_id"])
        try:
            _show_finding(
                root,
                interrupted_id,
                env=env,
                required_status=None,
                progress=progress,
            )
        except _MissingFinding as exc:
            raise SafetyError(
                f"Interrupted Clawpatch finding {interrupted_id} no longer exists, but "
                "source edits remain. Manageroo kept the checkpoint and will not discard "
                "or relabel the interrupted repair."
            ) from exc
        _preserve_unresolved_source(
            root,
            interrupted_id,
            "controller-interrupted",
        )
        preexisting_source = _source_paths(root)

    if progress is not None:
        progress(
            {
                "phase": "baseline-validation",
                "current": "?",
                "total": "?",
                "command": "configured Manageroo gates",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    _run_project_gates(root, finding_id="baseline-preflight")

    mapped = _json_clawpatch(
        root,
        ["clawpatch", "map", "--json"],
        env=env,
        progress=progress,
    )
    mapped_features = _required_int(mapped, "features")
    review = _review_all_features(
        root,
        env=env,
        mapped_features=mapped_features,
        progress=progress,
    )
    report["map"] = mapped
    report["review"] = review
    open_findings = status.get("openFindings")
    reviewed_findings = review.get("review", {}).get("findings", 0)
    total_findings = (
        open_findings + reviewed_findings
        if isinstance(open_findings, int) and not isinstance(open_findings, bool)
        else reviewed_findings
    )
    if not isinstance(total_findings, int) or isinstance(total_findings, bool) or total_findings < 0:
        raise SafetyError("Clawpatch returned an invalid open-finding count for progress reporting.")
    current_finding = 0

    pushed = False
    recovered_finding: tuple[str, dict[str, Any], dict[str, Any]] | None = None
    refreshed_missing_ids: set[str] = set()
    if durable_progress is not None:
        recovery_id = str(durable_progress["finding_id"])
        try:
            recovery_show = _show_finding(
                root,
                recovery_id,
                env=env,
                required_status=None,
                progress=progress,
                total=total_findings,
            )
        except _MissingFinding as exc:
            if preexisting_source:
                raise SafetyError(
                    f"Interrupted Clawpatch finding {recovery_id} no longer exists, but "
                    "source edits remain. Manageroo kept the checkpoint and will not discard "
                    "or relabel the interrupted repair."
                ) from exc
            _clear_release_progress(root)
            durable_progress = None
            recovery_show = None
        if recovery_show is None:
            durable_progress = None
        else:
            recovery_status = recovery_show["finding"].get("status")
        if recovery_show is not None and recovery_status == "false-positive":
            report["false_positives"].append(
                {
                    "finding_id": recovery_id,
                    "inspection": recovery_show,
                    "outcome": "false-positive",
                    "recovered_after_interruption": True,
                }
            )
            _clear_release_progress(root)
            durable_progress = None
        elif recovery_show is not None:
            recovery_preserved = {
                "created": bool(durable_progress.get("last_stash_ref")),
                "ref": durable_progress.get("last_stash_ref", ""),
                "paths": durable_progress.get("last_stash_paths", []),
            }
            if not recovery_preserved["created"]:
                recovery_preserved = _latest_preserved_source(root, recovery_id)
            recovered_inspection = _reopen_current_finding(
                root,
                recovery_id,
                env=env,
                failure=_retry_failure_context(
                    "Manageroo resumed the same interrupted Clawpatch finding.",
                    recovery_preserved,
                ),
                progress=progress,
                total=total_findings,
            )
            recovered_finding = (
                recovery_id,
                {"recovered_after_interruption": True},
                recovered_inspection,
            )

    while True:
        if recovered_finding is not None:
            finding_id, queue, inspected = recovered_finding
            recovered_finding = None
        else:
            finding_id, queue = _next_finding(
                root,
                env=env,
                progress=progress,
                current=current_finding + 1,
                total=total_findings,
            )
            if finding_id is None:
                break
            try:
                inspected = _show_finding(
                    root,
                    finding_id,
                    env=env,
                    required_status="open",
                    progress=progress,
                    current=current_finding + 1,
                    total=total_findings,
                )
            except _MissingFinding as exc:
                if _source_paths(root):
                    raise SafetyError(
                        f"Clawpatch selected stale finding {finding_id}, but source changes exist; "
                        "Manageroo will not remap over them."
                    ) from exc
                if finding_id in refreshed_missing_ids:
                    raise SafetyError(
                        f"Clawpatch still selected missing finding {finding_id} after one live-state refresh."
                    ) from exc
                refreshed_missing_ids.add(finding_id)
                if progress is not None:
                    progress(
                        {
                            "phase": "stale-refresh",
                            "current": current_finding + 1,
                            "total": total_findings,
                            "finding_id": finding_id,
                            "command": "clawpatch map --json; clawpatch review",
                        }
                    )
                refreshed_map = _json_clawpatch(
                    root,
                    ["clawpatch", "map", "--json"],
                    env=env,
                    progress=progress,
                )
                refreshed_feature_count = _required_int(refreshed_map, "features")
                refreshed_review = _review_all_features(
                    root,
                    env=env,
                    mapped_features=refreshed_feature_count,
                    progress=progress,
                )
                report["stale_refreshes"].append(
                    {
                        "missing_finding_id": finding_id,
                        "map": refreshed_map,
                        "review": refreshed_review,
                    }
                )
                continue
        current_finding += 1
        if progress is not None:
            progress(
                {
                    "phase": "finding",
                    "current": current_finding,
                    "total": total_findings,
                    "finding_id": finding_id,
                    "command": f"clawpatch show --finding {finding_id}",
                    "inspection": inspected,
                }
            )
        retry_count = (
            int(durable_progress["retry_count"])
            if durable_progress is not None and durable_progress["finding_id"] == finding_id
            else 0
        )
        last_attempt_fingerprint = (
            str(durable_progress.get("last_attempt_fingerprint", ""))
            if durable_progress is not None and durable_progress["finding_id"] == finding_id
            else ""
        )
        if durable_progress is not None and durable_progress.get("phase") == "no-progress-blocked":
            raise SafetyError(
                f"Clawpatch previously repeated the identical repair and failure for {finding_id}. "
                "The finding remains open; start a fresh run only after the inputs or tooling change."
            )
        while True:
            attempt_head = _git_text(root, ["git", "rev-parse", "HEAD"])
            _write_release_progress(
                root,
                finding_id=finding_id,
                branch=selected_branch,
                head_before=attempt_head,
                retry_count=retry_count,
                phase="fix",
                last_attempt_fingerprint=last_attempt_fingerprint,
            )
            if progress is not None:
                progress(
                    {
                        "phase": "fix",
                        "current": current_finding,
                        "total": total_findings,
                        "finding_id": finding_id,
                        "retry": retry_count,
                        "attempt": retry_count + 1,
                        "command": f"clawpatch fix --finding {finding_id}",
                    }
                )
            try:
                record, pushed = _execute_fix(
                    root,
                    finding_id,
                    inspected=inspected,
                    env=env,
                    push_mode=push_mode,
                    branch=selected_branch,
                    pushed=pushed,
                    progress=progress,
                    current=current_finding,
                    total=total_findings,
                )
            except _UnresolvedFinding as exc:
                reason = exc.outcome or "fix-validation-failed"
                preserved = _preserve_unresolved_source(root, finding_id, reason)
                failed_record = {
                    "finding_id": finding_id,
                    "inspection": inspected,
                    "outcome": exc.outcome,
                    "error": str(exc),
                    "preserved_source": preserved,
                }
                if exc.outcome == "false-positive":
                    report["false_positives"].append(failed_record)
                    _clear_release_progress(root)
                    durable_progress = None
                    break
                if not exc.retryable:
                    blocked_phase = (
                        "revalidation-blocked"
                        if reason.startswith("revalidation") or reason == "uncertain"
                        else "infrastructure-blocked"
                    )
                    _write_release_progress(
                        root,
                        finding_id=finding_id,
                        branch=selected_branch,
                        head_before=attempt_head,
                        retry_count=retry_count,
                        phase=blocked_phase,
                        last_stash_ref=str(preserved.get("ref") or ""),
                        last_stash_paths=list(preserved.get("paths") or []),
                    )
                    if progress is not None:
                        progress(
                            {
                                "phase": "stopped",
                                "current": current_finding,
                                "total": total_findings,
                                "finding_id": finding_id,
                                "outcome": exc.outcome,
                                "detail": f"{reason} stopped; no automatic retry",
                            }
                        )
                    preserved_ref = preserved.get("ref") or "no source changes"
                    raise SafetyError(
                        f"Clawpatch stopped on {reason!r} for {finding_id}. Manageroo preserved "
                        f"any repair at {preserved_ref}, did not triage the finding, and will not "
                        "retry an infrastructure or revalidation failure automatically.\n"
                        f"{exc}"
                    ) from exc
                retry_count += 1
                failed_record["retry_count"] = retry_count
                report["retries"].append(failed_record)
                if progress is not None:
                    progress(
                        {
                            "phase": "retry",
                            "current": current_finding,
                            "total": total_findings,
                            "finding_id": finding_id,
                            "retry": retry_count,
                            "outcome": exc.outcome,
                            "error": str(exc),
                        }
                    )
                preserved_ref = preserved.get("ref") or "no source changes"
                preserved_paths = preserved.get("paths") or []
                failure_context = _retry_failure_context(str(exc), preserved)
                attempt_fingerprint = _retry_attempt_fingerprint(
                    root,
                    message=str(exc),
                    outcome=reason,
                    preserved=preserved,
                )
                _write_release_progress(
                    root,
                    finding_id=finding_id,
                    branch=selected_branch,
                    head_before=attempt_head,
                    retry_count=retry_count,
                    phase="retry",
                    last_stash_ref=str(preserved.get("ref") or ""),
                    last_stash_paths=list(preserved_paths),
                    last_attempt_fingerprint=attempt_fingerprint,
                )
                inspected = _reopen_current_finding(
                    root,
                    finding_id,
                    env=env,
                    failure=failure_context,
                    progress=progress,
                    current_number=current_finding,
                    total=total_findings,
                )
                try:
                    _require_retry_progress(
                        last_attempt_fingerprint,
                        attempt_fingerprint,
                        finding_id,
                    )
                except SafetyError:
                    _write_release_progress(
                        root,
                        finding_id=finding_id,
                        branch=selected_branch,
                        head_before=attempt_head,
                        retry_count=retry_count,
                        phase="no-progress-blocked",
                        last_stash_ref=str(preserved.get("ref") or ""),
                        last_stash_paths=list(preserved_paths),
                        last_attempt_fingerprint=attempt_fingerprint,
                    )
                    if progress is not None:
                        progress(
                            {
                                "phase": "stopped",
                                "current": current_finding,
                                "total": total_findings,
                                "finding_id": finding_id,
                                "outcome": "no-progress",
                                "detail": "identical repair and identical failure repeated",
                            }
                        )
                    raise
                last_attempt_fingerprint = attempt_fingerprint
                time.sleep(min(2 ** min(max(retry_count - 1, 0), 6), 60))
                durable_progress = _load_release_progress(root)
                continue
            _clear_release_progress(root)
            durable_progress = None
            record["queue"] = queue
            report["results"].append(record)
            if progress is not None:
                progress(
                    {
                        "phase": "fixed",
                        "current": current_finding,
                        "total": total_findings,
                        "finding_id": finding_id,
                        "commit": record.get("commit", ""),
                    }
                )
            break

    closure = _final_closure(
        root,
        env=env,
        push_mode=push_mode,
        branch=selected_branch,
        pushed=pushed,
        publish_clawpatch_state=publish_clawpatch_state,
        review_limit=max(mapped_features, 1),
        progress=progress,
        current=current_finding,
        total=total_findings,
    )
    final_head = _git_text(root, ["git", "rev-parse", "HEAD"])
    proof = {
        "status": "COMPLETE",
        "completed_at": utc_now(),
        "repo": str(root),
        "branch": selected_branch,
        "git_head": final_head,
        "clawpatch_version": version,
        "open_findings": 0,
        "completed_findings": report["results"],
        "false_positives": report["false_positives"],
        "final_closure": closure,
    }
    proof_path = root / PROJECT_DIR / "cache" / "clawpatch-release-proof.json"
    atomic_write_json(proof_path, proof)
    report.update(
        {
            "branch": selected_branch,
            "git_head": final_head,
            "finding_count": len(report["results"]),
            "false_positive_count": len(report["false_positives"]),
            "unresolved_count": 0,
            "open_findings": 0,
            "final_closure": closure,
            "proof_path": str(proof_path),
        }
    )
    return report


def format_release_sweep(report: dict[str, Any]) -> str:
    if not report.get("apply"):
        return (
            "CLAWPATCH RELEASE SWEEP PLAN\n"
            f"Repo: {report['repo']}\n"
            f"Clawpatch: {report['clawpatch_version']}\n"
            f"Lifecycle: {report['lifecycle']}\n"
            "No repository changes were made. Run again with --apply to execute.\n"
        )
    return (
        "CLAWPATCH RELEASE SWEEP: COMPLETE\n"
        f"Findings fixed and committed: {report.get('finding_count', 0)}\n"
        f"Open findings: {report.get('open_findings', 0)}\n"
        f"Final HEAD: {report.get('git_head', '')}\n"
        f"Proof: {report.get('proof_path', '')}\n"
    )
