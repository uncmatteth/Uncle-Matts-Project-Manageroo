from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .branding import PROJECT_DIR
from .config import load_config
from .errors import MANAGEROOError, SafetyError
from .gates import GateRunner, gates_from_config
from .policy import CommandPolicy
from .runner import CommandRunner
from .util import atomic_write_json, utc_now


MINIMUM_CLAWPATCH_VERSION = (0, 7, 1)
CLAWPATCH_CODEX_RELEASE_TIMEOUT_MS = 1_800_000
LIFECYCLE = (
    "repository/process/Git preflight -> clawpatch status --json -> stale-lock cleanup when proven -> "
    "clawpatch map -> execute only each printed next command -> one fix -> complete project gates -> "
    "exact fixed revalidation -> exact-path commit/push when authorized -> clawpatch next -> final closure"
)
_NEXT_LINE = re.compile(r"(?mi)^\s*(?:[-*]\s*)?next:\s*(.+?)\s*$")
_FINDING_ID = re.compile(r"^fnd_[A-Za-z0-9_.-]+$")


def _release_clawpatch_env(*, trusted_host_codex_sandbox_bypass: bool) -> dict[str, str]:
    child_env = dict(os.environ)
    child_env.setdefault("CLAWPATCH_CODEX_TIMEOUT_MS", str(CLAWPATCH_CODEX_RELEASE_TIMEOUT_MS))
    if trusted_host_codex_sandbox_bypass:
        child_env["CLAWPATCH_CODEX_SANDBOX"] = "bypass"
    return child_env


def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int = 1800,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
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
        return subprocess.CompletedProcess(argv, 124, output + "\nTIMEOUT", None)
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, str(exc), None)


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
        for match in re.finditer(r"(?m)^[ \t]*(\{)", output):
            try:
                candidate, end = decoder.raw_decode(output, match.start(1))
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and not output[end:].strip():
                value = candidate
                break
        if value is None:
            raise SafetyError(f"Clawpatch {command} did not return valid JSON:\n{output[-4000:]}") from exc
    if not isinstance(value, dict):
        raise SafetyError(f"Clawpatch {command} returned an unexpected JSON value.")
    return value


def _next_from_output(output: str) -> str:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict) and isinstance(value.get("next"), str):
        return str(value["next"]).strip()
    matches = _NEXT_LINE.findall(output)
    if not matches:
        return ""
    command = matches[-1].strip()
    if len(command) >= 2 and command[0] == command[-1] and command[0] in {"`", "'", '"'}:
        command = command[1:-1].strip()
    return command


def _command_from_next(command: str) -> list[str]:
    raw = command.strip()
    if not raw:
        raise SafetyError("Clawpatch printed an empty next command.")
    if "<" in raw or ">" in raw:
        raise SafetyError(f"Clawpatch next command contains an unresolved placeholder: {raw}")
    if any(token in raw for token in ("\n", "\r", "\x00", "&&", "||", ";", "|", "$(", "`")):
        raise SafetyError(f"Clawpatch next command is not a single executable command: {raw}")
    try:
        argv = shlex.split(raw, posix=os.name != "nt")
    except ValueError as exc:
        raise SafetyError(f"Clawpatch next command could not be parsed exactly: {raw}") from exc
    if not argv or Path(argv[0].strip('"')).name.lower() not in {"clawpatch", "clawpatch.exe"}:
        raise SafetyError(f"Clawpatch next command is not a Clawpatch command: {raw}")
    argv[0] = argv[0].strip('"')
    if len(argv) < 2:
        raise SafetyError(f"Clawpatch next command has no command verb: {raw}")
    if argv[1] == "triage":
        raise SafetyError("Clawpatch directed triage; Manageroo will not alter a finding status.")
    return argv


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


def _active_clawpatch_processes(repo: Path) -> list[dict[str, Any]]:
    root = repo.resolve()
    found: list[dict[str, Any]] = []
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                if "clawpatch" not in cmdline.lower():
                    continue
                cwd = (entry / "cwd").resolve()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if cwd == root:
                found.append({"pid": int(entry.name), "cwd": str(cwd), "command": cmdline.strip()})
        return found
    result = _run(["ps", "-eo", "pid=,command="], cwd=root, timeout=30)
    if result.returncode:
        raise SafetyError("Could not prove that no other Clawpatch process is active.")
    for line in result.stdout.splitlines():
        if "clawpatch" in line.lower():
            found.append({"pid": line.strip().split(maxsplit=1)[0], "cwd": "unknown", "command": line.strip()})
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
        raise SafetyError("Clawpatch 0.7.1 or newer is required.")
    return text


def _run_clawpatch(
    repo: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: int = 7200,
) -> subprocess.CompletedProcess[str]:
    _require_no_process(repo)
    return _run(argv, cwd=repo, timeout=timeout, env=env)


def _must_clawpatch(repo: Path, argv: list[str], *, env: dict[str, str], timeout: int = 7200) -> str:
    result = _run_clawpatch(repo, argv, env=env, timeout=timeout)
    if result.returncode:
        raise SafetyError(
            f"phase: Clawpatch command\ncommand: {shlex.join(argv)}\nfinding ID: N/A\n"
            f"exit code: {result.returncode}\nfailed requirement: command must exit 0\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{result.stdout[-6000:]}"
        )
    return result.stdout


def _json_clawpatch(repo: Path, argv: list[str], *, env: dict[str, str], timeout: int = 7200) -> dict[str, Any]:
    output = _must_clawpatch(repo, argv, env=env, timeout=timeout)
    return _parse_json_output(output, command=" ".join(argv[1:]))


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
    result = _run(command, cwd=repo, timeout=3600, env=env)
    if result.returncode:
        requirement = "clawpatch fix validation passed" if result.returncode == 6 else "clawpatch fix exited 0"
        raise SafetyError(
            f"phase: fix\ncommand: {shlex.join(command)}\nfinding ID: {finding_id}\n"
            f"exit code: {result.returncode}\nfailed requirement: {requirement}\n"
            f"changed source paths: {_source_paths(repo) if repo.exists() else []}\n"
            f"output:\n{result.stdout[-6000:]}"
        )
    payload = _parse_json_output(result.stdout, command="fix")
    if payload.get("finding") != finding_id:
        raise SafetyError(f"Clawpatch fix returned the wrong finding; expected {finding_id!r}.")
    patch_attempt = payload.get("patchAttempt")
    if not isinstance(patch_attempt, str) or not patch_attempt.strip():
        raise SafetyError("Clawpatch fix returned no valid patch-attempt ID.")
    payload["patchAttempt"] = patch_attempt.strip()
    return payload


def _patch_attempt(repo: Path, patch_attempt_id: str, finding_id: str) -> dict[str, Any]:
    candidates = [
        repo / ".clawpatch" / "patches" / f"{patch_attempt_id}.json",
        repo / ".git" / "manageroo" / "clawpatch-state" / "patches" / f"{patch_attempt_id}.json",
    ]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise SafetyError(f"Could not read Clawpatch patch-attempt record {patch_attempt_id}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyError(f"Clawpatch patch-attempt record {patch_attempt_id} is malformed.") from exc
    if not isinstance(value, dict) or value.get("patchAttemptId") != patch_attempt_id:
        raise SafetyError(f"Clawpatch patch-attempt record does not match {patch_attempt_id}.")
    finding_ids = value.get("findingIds")
    if not isinstance(finding_ids, list) or finding_id not in finding_ids:
        raise SafetyError(f"Clawpatch patch-attempt record does not belong to {finding_id}.")
    files = value.get("filesChanged")
    if not isinstance(files, list) or any(not isinstance(path, str) or not path for path in files):
        raise SafetyError("Clawpatch patch-attempt filesChanged is malformed.")
    return value


def _validate_attempt_paths(repo: Path, files: list[str]) -> None:
    invalid = []
    for path in files:
        posix = PurePosixPath(path)
        windows = PureWindowsPath(path)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or ".." in posix.parts
            or ".." in windows.parts
            or path == ".clawpatch"
            or path.startswith(".clawpatch/")
        ):
            invalid.append(path)
    if invalid:
        raise SafetyError("Clawpatch patch attempt contains unsafe or state-only paths: " + ", ".join(invalid))
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
    try:
        config = load_config(repo)
        gates = gates_from_config(config)
        if not gates:
            raise SafetyError("The repository has no configured validation gates; complete validation is ambiguous.")
        log_root = repo / PROJECT_DIR / "cache" / "clawpatch-release-logs"
        runner = GateRunner(
            CommandRunner(log_root=log_root),
            CommandPolicy(tuple(config["safety"]["allowed_programs"])),
            log_root,
        )
        return [item.to_dict() for item in runner.run(gates, repo, require_one=True)]
    except MANAGEROOError as exc:
        raise SafetyError(
            f"phase: project validation\ncommand: configured Manageroo gates\nfinding ID: {finding_id}\n"
            f"exit code: nonzero\nfailed requirement: complete repository validation must pass\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{exc}"
        ) from exc


def _revalidate(repo: Path, finding_id: str, *, env: dict[str, str]) -> dict[str, Any]:
    argv = ["clawpatch", "revalidate", "--finding", finding_id, "--json"]
    payload = _json_clawpatch(repo, argv, env=env, timeout=3600)
    if payload.get("finding") != finding_id or payload.get("outcome") != "fixed":
        raise SafetyError(
            f"phase: revalidation\ncommand: {shlex.join(argv)}\nfinding ID: {finding_id}\n"
            "exit code: 0\nfailed requirement: matching finding and exact lowercase outcome fixed\n"
            f"changed source paths: {_source_paths(repo)}\noutput:\n{json.dumps(payload, sort_keys=True)}"
        )
    return payload


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
    if staged_paths != sorted(files) or any(path.startswith(".clawpatch/") for path in staged_paths):
        raise SafetyError("The staged paths do not exactly match the current Clawpatch patch attempt.")
    _must_run(["git", "diff", "--cached", "--check"], cwd=repo, timeout=120)
    _require_branch(repo, branch, phase="source commit")
    _must_run(["git", "commit", "-m", f"clawpatch fix: {finding_id}"], cwd=repo, timeout=300)
    commit = _git_text(repo, ["git", "rev-parse", "HEAD"])
    committed = _git_text(repo, ["git", "show", "--pretty=", "--name-only", "--no-renames", commit]).splitlines()
    if sorted(path for path in committed if path) != sorted(files):
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
    tracked = set(
        path
        for path in _must_run(["git", "ls-files", "-z", "--", ".clawpatch"], cwd=repo, timeout=120).split("\0")
        if path
    )
    untracked = sorted(set(state_paths) - tracked)
    if untracked:
        raise SafetyError(
            "Final Clawpatch state includes untracked paths; state publication covers tracked state only: "
            + ", ".join(untracked)
        )
    _must_run(["git", "add", "--", *state_paths], cwd=repo, timeout=120)
    staged = sorted(
        path
        for path in _must_run(
            ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"], cwd=repo, timeout=120
        ).split("\0")
        if path
    )
    if staged != sorted(state_paths) or any(not path.startswith(".clawpatch/") for path in staged):
        raise SafetyError("Final state commit is not exactly limited to tracked .clawpatch paths.")
    _must_run(["git", "commit", "-m", "clawpatch state: final closure"], cwd=repo, timeout=300)
    return _git_text(repo, ["git", "rev-parse", "HEAD"])


def _execute_fix(
    repo: Path,
    argv: list[str],
    *,
    env: dict[str, str],
    push_mode: str,
    branch: str,
    pushed: bool,
) -> tuple[dict[str, Any], bool]:
    if _source_paths(repo):
        raise SafetyError("Pre-existing source changes block the current Clawpatch fix.")
    finding_id = _finding_from_fix_argv(argv)
    head_before = _git_text(repo, ["git", "rev-parse", "HEAD"])
    _require_no_process(repo)
    fixed = _fix_command(repo, argv, env=env)
    patch = _patch_attempt(repo, str(fixed["patchAttempt"]), finding_id)
    files = [str(path) for path in patch["filesChanged"]]
    _validate_attempt_paths(repo, files)
    gate_runs = _run_project_gates(repo, finding_id=finding_id)
    _validate_attempt_paths(repo, files)
    validation = _revalidate(repo, finding_id, env=env)
    commit = _commit_attempt(repo, finding_id, files, branch=branch)
    if push_mode == "each" and commit:
        _push_and_verify(repo, branch, first=not pushed)
        pushed = True
    return {
        "finding_id": finding_id,
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
        raise SafetyError(f"Clawpatch status returned a missing or malformed {field!r} value.")
    return value


def _final_closure(
    repo: Path,
    *,
    env: dict[str, str],
    push_mode: str,
    branch: str,
    pushed: bool,
    publish_clawpatch_state: bool,
) -> dict[str, Any]:
    _require_no_process(repo)
    all_validation = _json_clawpatch(
        repo, ["clawpatch", "revalidate", "--all", "--status", "open", "--json"], env=env, timeout=3600
    )
    report = _json_clawpatch(repo, ["clawpatch", "report", "--status", "open", "--json"], env=env)
    if report.get("total") != 0 or report.get("items") != []:
        raise SafetyError("Final Clawpatch report is not exactly total=0 and items=[].")
    status = _json_clawpatch(repo, ["clawpatch", "status", "--json"], env=env)
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
        "report": report,
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
) -> dict[str, Any]:
    """Run Clawpatch as a fail-closed interpreter of its own printed next commands."""
    root = _git_root(repo)
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
    }
    if not apply:
        report["planned_branch"] = branch
        return report

    _require_no_process(root)
    preexisting_source = _source_paths(root)
    if preexisting_source:
        raise SafetyError("Clawpatch release sweep found pre-existing source changes: " + ", ".join(preexisting_source))

    selected_branch = current_branch
    if branch == "auto" and current_branch in {"main", "master", "HEAD"}:
        selected_branch = "clawpatch/release-sweep-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
    elif branch not in {"auto", "current"}:
        selected_branch = branch
        _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
    elif branch == "current" and current_branch == "HEAD":
        raise SafetyError("--branch current cannot be used from a detached HEAD.")
    if push_mode != "none":
        _must_run(["git", "remote", "get-url", "origin"], cwd=root, timeout=60)

    env = _release_clawpatch_env(
        trusted_host_codex_sandbox_bypass=trusted_host_codex_sandbox_bypass
    )
    status = _json_clawpatch(root, ["clawpatch", "status", "--json"], env=env)
    if _required_int(status, "activeLocks") or _required_int(status, "lockFiles"):
        _require_no_process(root)
        _json_clawpatch(root, ["clawpatch", "clean-locks", "--json"], env=env)

    output = _must_clawpatch(root, ["clawpatch", "map"], env=env, timeout=1800)
    next_text = _next_from_output(output)
    if not next_text:
        next_text = "clawpatch next"

    review_seen = False
    pushed = False
    while True:
        argv = _command_from_next(next_text)
        verb = argv[1]
        if verb == "review":
            if review_seen:
                raise SafetyError("Clawpatch directed a second review; Manageroo will not independently restart review.")
            review_seen = True
            output = _must_clawpatch(root, argv, env=env, timeout=7200)
        elif verb == "fix":
            record, pushed = _execute_fix(
                root,
                argv,
                env=env,
                push_mode=push_mode,
                branch=selected_branch,
                pushed=pushed,
            )
            report["results"].append(record)
            output = json.dumps(record["revalidation"])
        elif verb in {"next", "show", "report", "status", "map"}:
            output = _must_clawpatch(root, argv, env=env, timeout=1800)
        else:
            raise SafetyError(f"Clawpatch directed unsupported command {shlex.join(argv)}; stopping without substitution.")

        printed = _next_from_output(output)
        if printed:
            next_text = printed
            continue
        if verb == "report" and "--status" in argv and "open" in argv:
            closure = _final_closure(
                root,
                env=env,
                push_mode=push_mode,
                branch=selected_branch,
                pushed=pushed,
                publish_clawpatch_state=publish_clawpatch_state,
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
                "final_closure": closure,
            }
            proof_path = root / PROJECT_DIR / "cache" / "clawpatch-release-proof.json"
            atomic_write_json(proof_path, proof)
            report.update(
                {
                    "branch": selected_branch,
                    "git_head": final_head,
                    "finding_count": len(report["results"]),
                    "open_findings": 0,
                    "final_closure": closure,
                    "proof_path": str(proof_path),
                }
            )
            return report
        next_text = "clawpatch next"


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
