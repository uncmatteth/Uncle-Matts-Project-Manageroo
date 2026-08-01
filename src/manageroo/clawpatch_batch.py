from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .errors import SafetyError

_FINDING_ID_RE = re.compile(r"^id:\s*(fnd_\S+)\s*$", re.MULTILINE)


def _run(argv: list[str], *, cwd: Path, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        error = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(argv, 124, output, error + "\nTIMEOUT")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _diagnostic_output(result: subprocess.CompletedProcess[str], limit: int) -> str:
    output = result.stdout or ""
    if result.stderr:
        if output and not output.endswith("\n"):
            output += "\n"
        output += result.stderr
    return output[-limit:]


def _git_root(repo: Path) -> Path:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=repo, timeout=30)
    if result.returncode:
        raise SafetyError(
            "Clawpatch batch repair requires an existing Git repository.\n"
            + _diagnostic_output(result, 4000)
        )
    return Path(result.stdout.strip()).resolve()


def _git_status(repo: Path) -> str:
    result = _run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, timeout=60)
    if result.returncode:
        raise SafetyError(
            "Could not inspect Git status before Clawpatch batch repair.\n"
            + _diagnostic_output(result, 4000)
        )
    return result.stdout


def _changed_paths(repo: Path) -> list[str]:
    paths: set[str] = set()
    for argv in (
        ["git", "diff", "--name-only", "--no-renames", "-z"],
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        result = _run(argv, cwd=repo, timeout=120)
        if result.returncode:
            raise SafetyError(
                "Could not capture exact Clawpatch fix paths.\n"
                + _diagnostic_output(result, 4000)
            )
        paths.update(path for path in result.stdout.split("\0") if path)
    return sorted(paths)


def _validate_fix_paths(paths: list[str]) -> None:
    if not paths:
        raise SafetyError("Clawpatch fix produced no Git-visible source change.")
    invalid = []
    for relative in paths:
        posix = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or any(part in {"", ".", ".."} for part in posix.parts)
            or posix.parts[0].lower() == ".git"
        ):
            invalid.append(relative)
    if invalid:
        raise SafetyError("Clawpatch produced unsafe changed paths: " + ", ".join(invalid))


def _git_blob_oid(data: bytes, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _path_digests(repo: Path, paths: list[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    object_format = ""
    for relative in paths:
        path = repo / relative
        if path.is_symlink():
            if not object_format:
                result = _run(["git", "rev-parse", "--show-object-format"], cwd=repo, timeout=60)
                if result.returncode or result.stdout.strip() not in {"sha1", "sha256"}:
                    raise SafetyError(
                        "Could not determine the Git object format for Clawpatch staging.\n"
                        + _diagnostic_output(result, 4000)
                    )
                object_format = result.stdout.strip()
            digests[relative] = _git_blob_oid(os.fsencode(path.readlink()), object_format)
        elif path.is_file():
            result = _run(
                ["git", "hash-object", f"--path={relative}", "--", relative],
                cwd=repo,
                timeout=120,
            )
            if result.returncode or not result.stdout.strip():
                raise SafetyError(
                    f"Could not snapshot Clawpatch content for {relative}.\n"
                    + _diagnostic_output(result, 4000)
                )
            digests[relative] = result.stdout.strip()
        elif not path.exists():
            digests[relative] = "deleted"
        else:
            raise SafetyError(f"Clawpatch changed path is not a regular file: {relative}")
    return digests


def _staged_paths(repo: Path) -> list[str]:
    result = _run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "-z"],
        cwd=repo,
        timeout=120,
    )
    if result.returncode:
        raise SafetyError(
            "Could not inspect staged Clawpatch paths.\n" + _diagnostic_output(result, 4000)
        )
    return sorted(path for path in result.stdout.split("\0") if path)


def _staged_path_digests(repo: Path, paths: list[str]) -> dict[str, str]:
    result = _run(["git", "ls-files", "--stage", "-z", "--", *paths], cwd=repo, timeout=120)
    if result.returncode:
        raise SafetyError(
            "Could not inspect staged Clawpatch content.\n" + _diagnostic_output(result, 4000)
        )
    entries: dict[str, str] = {}
    for entry in (value for value in result.stdout.split("\0") if value):
        metadata, separator, relative = entry.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0" or relative in entries:
            raise SafetyError("Git returned an unexpected staged entry for Clawpatch repair.")
        entries[relative] = fields[1]
    return {relative: entries.get(relative, "deleted") for relative in paths}


def open_finding_ids(repo: Path) -> tuple[list[str], str]:
    """Return exactly the finding IDs Clawpatch currently reports as open."""
    root = _git_root(repo)
    if not shutil.which("clawpatch"):
        raise SafetyError("Clawpatch is not installed or is not available on PATH.")
    report = _run(["clawpatch", "report", "--status", "open"], cwd=root, timeout=300)
    if report.returncode:
        raise SafetyError(
            "Could not read open Clawpatch findings:\n" + _diagnostic_output(report, 4000)
        )
    ids: list[str] = []
    seen: set[str] = set()
    for finding_id in _FINDING_ID_RE.findall(report.stdout):
        if finding_id not in seen:
            seen.add(finding_id)
            ids.append(finding_id)
    return ids, report.stdout


def batch_fix_open_findings(
    repo: Path,
    *,
    apply: bool = False,
    limit: int = 0,
    commit_each: bool = True,
) -> dict[str, Any]:
    """Apply Clawpatch fixes one open finding at a time with fail-closed Git boundaries.

    This is the cross-platform native equivalent of shell/PowerShell loops. Manageroo
    asks Clawpatch itself for only `open` findings, fixes them serially, and optionally
    creates one controller-owned Git commit per successful fix. The operation stops at
    the first failed fix, empty fix, dirty boundary, staging failure, or commit failure.
    """
    root = _git_root(repo)
    ids, report_text = open_finding_ids(root)
    if limit > 0:
        ids = ids[:limit]

    plan = {
        "repo": str(root),
        "apply": apply,
        "commit_each": commit_each,
        "finding_count": len(ids),
        "finding_ids": ids,
        "report": report_text,
        "results": [],
        "ok": True,
        "stopped_at": "",
    }
    if not apply or not ids:
        return plan

    initial_status = _git_status(root)
    if initial_status.strip():
        raise SafetyError(
            "Clawpatch batch repair requires a clean working tree before it starts. "
            "Commit or stash existing changes first."
        )

    for finding_id in ids:
        before = _git_status(root)
        if before.strip():
            raise SafetyError(
                f"Working tree became dirty before starting {finding_id}; refusing to mix fixes."
            )

        fix = _run(["clawpatch", "fix", "--finding", finding_id], cwd=root)
        record: dict[str, Any] = {
            "finding_id": finding_id,
            "fix_exit_code": fix.returncode,
            "fix_output": _diagnostic_output(fix, 8000),
            "committed": False,
            "commit": "",
        }
        if fix.returncode:
            record["ok"] = False
            record["error"] = "clawpatch fix failed"
            plan["results"].append(record)
            plan["ok"] = False
            plan["stopped_at"] = finding_id
            break

        fix_paths = _changed_paths(root)
        if not fix_paths:
            record["ok"] = False
            record["error"] = "clawpatch fix reported success but produced no Git-visible change"
            plan["results"].append(record)
            plan["ok"] = False
            plan["stopped_at"] = finding_id
            break
        _validate_fix_paths(fix_paths)
        fix_digests = _path_digests(root, fix_paths)
        changed = _git_status(root)
        record["git_status_after_fix"] = changed

        if commit_each:
            add = _run(["git", "add", "--", *fix_paths], cwd=root, timeout=120)
            if add.returncode:
                record["ok"] = False
                record["error"] = "exact-path git add failed"
                record["git_output"] = _diagnostic_output(add, 4000)
                plan["results"].append(record)
                plan["ok"] = False
                plan["stopped_at"] = finding_id
                break

            staged_paths = _staged_paths(root)
            if staged_paths != fix_paths:
                record["ok"] = False
                record["error"] = "staged paths did not exactly match the Clawpatch fix snapshot"
                plan["results"].append(record)
                plan["ok"] = False
                plan["stopped_at"] = finding_id
                break
            if _staged_path_digests(root, fix_paths) != fix_digests:
                record["ok"] = False
                record["error"] = "staged content did not match the Clawpatch fix snapshot"
                plan["results"].append(record)
                plan["ok"] = False
                plan["stopped_at"] = finding_id
                break

            commit = _run(
                ["git", "commit", "-m", f"clawpatch fix: {finding_id}"],
                cwd=root,
                timeout=300,
            )
            if commit.returncode:
                record["ok"] = False
                record["error"] = "git commit failed"
                record["git_output"] = _diagnostic_output(commit, 4000)
                plan["results"].append(record)
                plan["ok"] = False
                plan["stopped_at"] = finding_id
                break
            head = _run(["git", "rev-parse", "HEAD"], cwd=root, timeout=60)
            record["committed"] = True
            record["commit"] = head.stdout.strip() if head.returncode == 0 else ""
        record["ok"] = True
        plan["results"].append(record)

    plan["completed_count"] = sum(1 for item in plan["results"] if item.get("ok"))
    plan["remaining_unprocessed"] = max(0, len(ids) - len(plan["results"]))
    return plan


def format_batch_fix(report: dict[str, Any]) -> str:
    if not report.get("apply"):
        lines = [
            "CLAWPATCH OPEN-FINDING REPAIR PLAN",
            f"Repo: {report['repo']}",
            f"Open findings selected: {report['finding_count']}",
        ]
        for finding_id in report.get("finding_ids", []):
            lines.append(f"- {finding_id}")
        if report.get("finding_ids"):
            lines.append("Run again with --apply to fix them serially and commit each successful fix.")
        else:
            lines.append("No open Clawpatch findings were reported.")
        return "\n".join(lines) + "\n"

    lines = [
        "CLAWPATCH OPEN-FINDING REPAIR: " + ("COMPLETE" if report.get("ok") else "STOPPED"),
        f"Completed: {report.get('completed_count', 0)} / {report.get('finding_count', 0)}",
    ]
    for item in report.get("results", []):
        label = "OK" if item.get("ok") else "STOP"
        suffix = f" commit={item.get('commit')}" if item.get("commit") else ""
        lines.append(f"{label} {item['finding_id']}{suffix}")
        if item.get("error"):
            lines.append(f"  {item['error']}")
    if report.get("stopped_at"):
        lines.append(f"Stopped at: {report['stopped_at']}. Inspect `git status` before continuing.")
    return "\n".join(lines) + "\n"
