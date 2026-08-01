from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .branding import PROJECT_DIR
from .config import load_config
from .errors import MANAGEROOError, SafetyError
from .gates import GateRunner, gates_from_config
from .policy import CommandPolicy
from .runner import CommandRunner
from .util import atomic_write_json, read_json, sha256_file, utc_now


MINIMUM_CLAWPATCH_VERSION = (0, 7, 1)
LIFECYCLE = (
    "clawpatch doctor -> init (when needed) -> map -> review -> "
    "clawpatch next --status open -> show -> fix -> Manageroo gates -> revalidate -> exact-path commit; "
    "repeat -> revalidate --all --status open -> zero-open report -> final gates -> clean Git"
)


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
        raise SafetyError(f"Command failed ({' '.join(argv)}):\n{result.stdout[-6000:]}")
    return result.stdout


def _json_command(
    repo: Path,
    command: str,
    *args: str,
    timeout: int = 1800,
    state_dir: Path | None = None,
    clawpatch_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    state_args = ["--state-dir", str(state_dir)] if state_dir is not None else []
    argv = ["clawpatch", "--json", "--no-input", *state_args, command, *args]
    output = _must_run(argv, cwd=repo, timeout=timeout, env=clawpatch_env)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        value = None
        decoder = json.JSONDecoder()
        for match in re.finditer(r"(?m)^[ \t]*(\{)", output):
            start = match.start(1)
            try:
                candidate, end = decoder.raw_decode(output, start)
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


def _git_root(repo: Path) -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo, timeout=30)
    if result.returncode or not result.stdout.strip():
        raise SafetyError("Clawpatch release sweep requires an existing Git repository.")
    return Path(result.stdout.strip()).resolve()


def _git_text(repo: Path, argv: list[str]) -> str:
    return _must_run(argv, cwd=repo, timeout=120).strip()


def _git_status(repo: Path) -> str:
    return _must_run(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, timeout=60
    )


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
        raise SafetyError("Clawpatch 0.7.1 or newer is required for the JSON release-sweep contract.")
    return text


def _changed_paths(repo: Path) -> list[str]:
    commands = (
        ["git", "diff", "--name-only", "--no-renames", "-z"],
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths: set[str] = set()
    for argv in commands:
        output = _must_run(argv, cwd=repo, timeout=120)
        paths.update(value for value in output.split("\0") if value)
    return sorted(paths)


def _validate_fix_paths(paths: list[str]) -> None:
    if not paths:
        raise SafetyError("Clawpatch reported a fix but produced no Git-visible source change.")
    forbidden = (".git/", f"{PROJECT_DIR}/", ".clawpatch/")
    invalid = [path for path in paths if path in {".git", PROJECT_DIR, ".clawpatch"} or path.startswith(forbidden)]
    if invalid:
        raise SafetyError("Clawpatch attempted to modify controller state: " + ", ".join(invalid))


def _path_digests(repo: Path, paths: list[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relative in paths:
        path = repo / relative
        if path.is_symlink():
            digests[relative] = "symlink:" + str(path.readlink())
        elif path.is_file():
            digests[relative] = sha256_file(path)
        elif not path.exists():
            digests[relative] = "deleted"
        else:
            raise SafetyError(f"Clawpatch changed path is not a regular file: {relative}")
    return digests


def _run_manageroo_gates(repo: Path, *, label: str) -> list[dict[str, Any]]:
    config_path = repo / PROJECT_DIR / "config.toml"
    if not config_path.is_file():
        return []
    try:
        config = load_config(repo)
        gates = gates_from_config(config)
        if not gates:
            raise SafetyError("Manageroo is initialized but has no verification gates configured.")
        log_root = repo / PROJECT_DIR / "cache" / "clawpatch-release-logs"
        runner = GateRunner(
            CommandRunner(log_root=log_root),
            CommandPolicy(tuple(config["safety"]["allowed_programs"])),
            log_root,
        )
        return [item.to_dict() for item in runner.run(gates, repo, require_one=True)]
    except MANAGEROOError as exc:
        raise SafetyError(f"Manageroo gates failed during {label}: {exc}") from exc


def _checkpoint_path(repo: Path) -> Path:
    dot_git = repo / ".git"
    if dot_git.is_file():
        marker = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if marker.lower().startswith("gitdir:"):
            git_dir = Path(marker.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = (repo / git_dir).resolve()
            return git_dir / "manageroo" / "clawpatch-release-sweep.json"
    return dot_git / "manageroo" / "clawpatch-release-sweep.json"


def _proof_path(repo: Path) -> Path:
    if (repo / PROJECT_DIR).is_dir():
        return repo / PROJECT_DIR / "cache" / "clawpatch-release-proof.json"
    return _checkpoint_path(repo).with_name("clawpatch-release-proof.json")


def _load_checkpoint(repo: Path) -> dict[str, Any]:
    path = _checkpoint_path(repo)
    if not path.is_file():
        return {}
    try:
        value = read_json(path)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _finding_id(payload: dict[str, Any]) -> str:
    finding = payload.get("finding")
    if finding is None:
        return ""
    if isinstance(finding, str):
        return finding.strip()
    if isinstance(finding, dict):
        return str(finding.get("findingId") or finding.get("id") or "").strip()
    return ""


def _push(repo: Path, branch: str, *, first: bool) -> None:
    if first:
        _must_run(["git", "push", "-u", "origin", branch], cwd=repo, timeout=600)
    else:
        _must_run(["git", "push", "origin", branch], cwd=repo, timeout=600)


def _clawpatch_state_dir(repo: Path) -> Path | None:
    """Keep first-run Clawpatch state outside the source worktree.

    Existing standard or project-configured Clawpatch projects retain their own
    state choice. New projects use a Git-private directory so initialization and
    mapping cannot dirty the release branch before the first finding.
    """
    if (repo / ".clawpatch" / "config.json").is_file() or (repo / "clawpatch.config.json").is_file():
        return None
    return _checkpoint_path(repo).parent / "clawpatch-state"


def _finish_finding(
    repo: Path,
    *,
    finding_id: str,
    paths: list[str],
    checkpoint: dict[str, Any],
    push_mode: str,
    branch: str,
    state_dir: Path | None,
    clawpatch_env: dict[str, str] | None,
) -> dict[str, Any]:
    gate_runs = _run_manageroo_gates(repo, label=finding_id)
    validation = _json_command(
        repo,
        "revalidate",
        "--finding",
        finding_id,
        state_dir=state_dir,
        clawpatch_env=clawpatch_env,
    )
    if str(validation.get("outcome") or "") != "fixed":
        raise SafetyError(
            f"Clawpatch finding {finding_id} did not clear after validation "
            f"(outcome={validation.get('outcome', 'unknown')}). No commit was created."
        )
    _must_run(["git", "add", "--", *paths], cwd=repo, timeout=120)
    staged = _must_run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"],
        cwd=repo,
        timeout=120,
    )
    staged_paths = sorted(path for path in staged.split("\0") if path)
    if staged_paths != sorted(paths):
        raise SafetyError("The staged paths did not exactly match the Clawpatch fix; refusing to commit.")
    _must_run(["git", "commit", "-m", f"clawpatch fix: {finding_id}"], cwd=repo, timeout=300)
    commit = _git_text(repo, ["git", "rev-parse", "HEAD"])
    record = {
        "finding_id": finding_id,
        "paths": paths,
        "commit": commit,
        "validation": validation,
        "gate_runs": gate_runs,
    }
    checkpoint.setdefault("completed", []).append(record)
    checkpoint.update({"phase": "idle", "active_finding": "", "paths": [], "path_digests": {}, "head": commit})
    atomic_write_json(_checkpoint_path(repo), checkpoint)
    if push_mode == "each":
        _push(repo, branch, first=not bool(checkpoint.get("pushed")))
        checkpoint["pushed"] = True
        atomic_write_json(_checkpoint_path(repo), checkpoint)
    return record


def release_sweep(
    repo: Path,
    *,
    apply: bool = False,
    branch: str = "auto",
    push_mode: str = "none",
    review_limit: int = 100,
    jobs: int = 3,
    max_findings: int = 0,
    skip_review: bool = False,
    trusted_host_codex_sandbox_bypass: bool = False,
) -> dict[str, Any]:
    """Run the strict, serial Clawpatch final-release lifecycle.

    Dry-run is the default. Apply mode uses fresh `next` selection, validates each
    fix before an exact-path commit, persists a repository-private checkpoint, and
    proves zero open findings against the final HEAD.
    """
    root = _git_root(repo)
    version = _clawpatch_version(root)
    current_branch = _git_text(root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head = _git_text(root, ["git", "rev-parse", "HEAD"])
    status = _git_status(root)
    clawpatch_env = None
    if trusted_host_codex_sandbox_bypass:
        clawpatch_env = dict(os.environ)
        clawpatch_env["CLAWPATCH_CODEX_SANDBOX"] = "bypass"
    if push_mode not in {"none", "each", "final"}:
        raise SafetyError("push_mode must be one of: none, each, final.")
    if review_limit < 1 or jobs < 1 or max_findings < 0:
        raise SafetyError("review_limit and jobs must be positive; max_findings must be zero or greater.")

    report: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "repo": str(root),
        "clawpatch_version": version,
        "branch": current_branch,
        "git_head_before": head,
        "lifecycle": LIFECYCLE,
        "push_mode": push_mode,
        "trusted_host_codex_sandbox_bypass": trusted_host_codex_sandbox_bypass,
        "results": [],
    }
    if not apply:
        report["clean"] = not bool(status.strip())
        report["planned_branch"] = branch
        return report

    state_dir = _clawpatch_state_dir(root)

    checkpoint = _load_checkpoint(root)
    resumable = (
        checkpoint.get("phase") == "fixed"
        and checkpoint.get("head") == head
        and bool(checkpoint.get("active_finding"))
        and bool(checkpoint.get("paths"))
        and isinstance(checkpoint.get("path_digests"), dict)
    )
    if resumable:
        saved_paths = [str(path) for path in checkpoint["paths"]]
        resumable = (
            _changed_paths(root) == sorted(saved_paths)
            and _path_digests(root, saved_paths) == checkpoint.get("path_digests")
        )
    if status.strip() and not resumable:
        raise SafetyError("Clawpatch release sweep requires a clean working tree before it starts.")

    selected_branch = current_branch
    if not resumable:
        if branch == "auto" and current_branch in {"main", "master", "HEAD"}:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            selected_branch = f"clawpatch/release-sweep-{stamp}"
            _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
        elif branch not in {"auto", "current"}:
            selected_branch = branch
            _must_run(["git", "switch", "-c", selected_branch], cwd=root, timeout=120)
        elif branch == "current" and current_branch == "HEAD":
            raise SafetyError("--branch current cannot be used from a detached HEAD; name a new branch or use auto.")
        if push_mode != "none":
            _must_run(["git", "remote", "get-url", "origin"], cwd=root, timeout=60)

        _json_command(
            root, "doctor", timeout=300, state_dir=state_dir, clawpatch_env=clawpatch_env
        )
        state_project = (state_dir / "project.json") if state_dir is not None else (root / ".clawpatch" / "project.json")
        if not state_project.is_file():
            _json_command(
                root, "init", timeout=300, state_dir=state_dir, clawpatch_env=clawpatch_env
            )
        _json_command(
            root, "map", timeout=1800, state_dir=state_dir, clawpatch_env=clawpatch_env
        )
        if not skip_review:
            _json_command(
                root,
                "review",
                "--limit",
                str(review_limit),
                "--jobs",
                str(jobs),
                timeout=7200,
                state_dir=state_dir,
                clawpatch_env=clawpatch_env,
            )
        checkpoint = {
            "version": 1,
            "repo": str(root),
            "branch": selected_branch,
            "base_head": head,
            "head": _git_text(root, ["git", "rev-parse", "HEAD"]),
            "phase": "idle",
            "active_finding": "",
            "paths": [],
            "path_digests": {},
            "completed": [],
            "pushed": False,
        }
        atomic_write_json(_checkpoint_path(root), checkpoint)
    else:
        selected_branch = str(checkpoint.get("branch") or current_branch)
        paths = [str(path) for path in checkpoint["paths"]]
        _validate_fix_paths(paths)
        report["results"].append(
            _finish_finding(
                root,
                finding_id=str(checkpoint["active_finding"]),
                paths=paths,
                checkpoint=checkpoint,
                push_mode=push_mode,
                branch=selected_branch,
                state_dir=state_dir,
                clawpatch_env=clawpatch_env,
            )
        )

    seen: set[str] = set()
    while max_findings == 0 or len(report["results"]) < max_findings:
        next_payload = _json_command(
            root,
            "next",
            "--status",
            "open",
            timeout=300,
            state_dir=state_dir,
            clawpatch_env=clawpatch_env,
        )
        finding_id = _finding_id(next_payload)
        if not finding_id:
            break
        if finding_id in seen:
            raise SafetyError(f"Clawpatch selected {finding_id} twice without clearing it; stopping.")
        seen.add(finding_id)
        _json_command(
            root,
            "show",
            "--finding",
            finding_id,
            timeout=300,
            state_dir=state_dir,
            clawpatch_env=clawpatch_env,
        )
        if _git_status(root).strip():
            raise SafetyError(f"Working tree became dirty before fixing {finding_id}.")
        checkpoint.update({
            "phase": "starting",
            "active_finding": finding_id,
            "paths": [],
            "path_digests": {},
            "head": _git_text(root, ["git", "rev-parse", "HEAD"]),
        })
        atomic_write_json(_checkpoint_path(root), checkpoint)
        fix = _json_command(
            root,
            "fix",
            "--finding",
            finding_id,
            timeout=3600,
            state_dir=state_dir,
            clawpatch_env=clawpatch_env,
        )
        if str(fix.get("status") or "") != "applied":
            raise SafetyError(f"Clawpatch did not apply finding {finding_id}.")
        paths = _changed_paths(root)
        _validate_fix_paths(paths)
        checkpoint.update({"phase": "fixed", "paths": paths, "path_digests": _path_digests(root, paths)})
        atomic_write_json(_checkpoint_path(root), checkpoint)
        report["results"].append(
            _finish_finding(
                root,
                finding_id=finding_id,
                paths=paths,
                checkpoint=checkpoint,
                push_mode=push_mode,
                branch=selected_branch,
                state_dir=state_dir,
                clawpatch_env=clawpatch_env,
            )
        )

    final_validation = _json_command(
        root,
        "revalidate",
        "--all",
        "--status",
        "open",
        timeout=3600,
        state_dir=state_dir,
        clawpatch_env=clawpatch_env,
    )
    if int(final_validation.get("open") or 0) or int(final_validation.get("uncertain") or 0):
        raise SafetyError("Final Clawpatch revalidation still reports open or uncertain findings.")
    final_report = _json_command(
        root,
        "report",
        "--status",
        "open",
        timeout=300,
        state_dir=state_dir,
        clawpatch_env=clawpatch_env,
    )
    if int(final_report.get("total") or 0) != 0:
        raise SafetyError("Clawpatch still reports open findings after the release sweep.")
    final_gates = _run_manageroo_gates(root, label="final proof")
    if _git_status(root).strip():
        raise SafetyError("The working tree is not clean after the final Clawpatch proof.")
    final_head = _git_text(root, ["git", "rev-parse", "HEAD"])
    if push_mode == "final":
        _push(root, selected_branch, first=not bool(checkpoint.get("pushed")))
        checkpoint["pushed"] = True
    proof = {
        "status": "COMPLETE",
        "completed_at": utc_now(),
        "repo": str(root),
        "branch": selected_branch,
        "git_head": final_head,
        "clawpatch_version": version,
        "open_findings": 0,
        "completed_findings": checkpoint.get("completed", []),
        "final_revalidation": final_validation,
        "final_report": final_report,
        "final_gate_runs": final_gates,
        "pushed": bool(checkpoint.get("pushed")),
        "state_dir": str(state_dir) if state_dir is not None else str(root / ".clawpatch"),
    }
    atomic_write_json(_proof_path(root), proof)
    checkpoint.update({"phase": "complete", "head": final_head, "proof_path": str(_proof_path(root))})
    atomic_write_json(_checkpoint_path(root), checkpoint)
    report.update({
        "branch": selected_branch,
        "git_head": final_head,
        "finding_count": len(report["results"]),
        "open_findings": 0,
        "final_revalidation": final_validation,
        "final_gate_runs": final_gates,
        "proof_path": str(_proof_path(root)),
    })
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
    lines = [
        "CLAWPATCH RELEASE SWEEP: COMPLETE",
        f"Findings fixed and committed: {report.get('finding_count', 0)}",
        f"Open findings: {report.get('open_findings', 0)}",
        f"Final HEAD: {report.get('git_head', '')}",
        f"Proof: {report.get('proof_path', '')}",
    ]
    return "\n".join(lines) + "\n"
