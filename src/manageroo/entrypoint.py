from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import shutil
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .branding import PROJECT_DIR
from .clawpatch_release import format_release_sweep, release_sweep
from .cli import main as cli_main
from .cli import parser as cli_parser
from .config import AGENT_PRESETS
from .config_lock import config_mutation_lock
from .discovery_policy import decisions_fully_resolved, render_blocking_questions
from .errors import SafetyError
from .host_skills import format_host_skills, inspect_host_skills
from .prove import LIVE_AGENT_CHOICES, format_product_proof, run_product_proof
from .stack_update import STACK_TOOL_NAMES, apply_stack_updates, format_stack_update, stack_update_plan
from .system_capacity import format_capacity, host_capacity
from .util import atomic_write_json, read_json, sha256_json, utc_now


def _auto_live_agent() -> str | None:
    for name in LIVE_AGENT_CHOICES:
        executable = str(AGENT_PRESETS.get(name, {}).get("executable") or "")
        if executable and shutil.which(executable):
            return name
    return None


def _provider_neutral_argv(argv: list[str]) -> list[str]:
    explicit_agent = any(value == "--agent" or value.startswith("--agent=") for value in argv)
    if argv and argv[0] in {"init", "projects"} and not explicit_agent:
        return [*argv, "--agent", "auto"]
    return argv


def _prove_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo prove",
        description="Run adversarial product certification for the Manageroo control plane.",
    )
    parser.add_argument(
        "--no-regression",
        action="store_true",
        help="Skip source regressions. The proof will return PARTIAL, never COMPLETE.",
    )
    parser.add_argument(
        "--live-agent",
        choices=LIVE_AGENT_CHOICES,
        help=(
            "Use a specific live coding-agent preset. Omit this to let Manageroo "
            "select any installed supported worker."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    selected_agent = args.live_agent or _auto_live_agent()
    report = run_product_proof(
        include_regression=not args.no_regression,
        live_agent=selected_agent,
    )
    report["live_agent_selection"] = (
        "explicit" if args.live_agent else "automatic" if selected_agent else "none-available"
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if selected_agent and not args.live_agent:
            print(f"Auto-selected live agent: {selected_agent}\n")
        print(format_product_proof(report), end="")
    return 0 if report.get("ok") else 2


def _capacity_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo capacity",
        description="Inspect this machine's hardware as informational development-host context.",
    )
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    profile = host_capacity(Path(args.repo))
    rendered = json.dumps(profile, indent=2, sort_keys=True) if args.json else format_capacity(profile)
    print(rendered, end="\n" if args.json else "")
    return 0


def _host_skills_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo host-skills",
        description=(
            "Inspect local agent skill roots without copying, deleting, or claiming ownership of host skills."
        ),
    )
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_host_skills(args.root or None)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_host_skills(report), end="")
    return 0


def _stack_update_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo stack-update",
        description=(
            "Plan or explicitly apply upstream-supported updates for Manageroo's recommended surrounding stack."
        ),
    )
    parser.add_argument(
        "tools",
        nargs="*",
        choices=STACK_TOOL_NAMES,
        help="Optionally limit the operation to one or more named stack tools.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    selected = args.tools or None
    report = apply_stack_updates(selected) if args.apply else stack_update_plan(selected)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_stack_update(report), end="")
    return 0 if report.get("ok") else 2


def _clawpatch_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo clawpatch",
        description=(
            "Plan or invoke the separately installed ClawPatch supervisor."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    release = sub.add_parser(
        "release-sweep",
        description=(
            "Run Clawpatch's complete review and supervised one-finding repair lifecycle; reconcile and retry the same current finding."
        ),
    )
    release.add_argument("--repo", default=".")
    release.add_argument("--apply", action="store_true", help="Execute the sweep. Without this flag, show a read-only plan.")
    release.add_argument(
        "--branch",
        default="auto",
        help="auto creates a release-sweep branch from main/master; current stays on the current branch; any other value creates that branch.",
    )
    release.add_argument("--push", choices=("none", "each", "final"), default="none")
    release.add_argument(
        "--publish-clawpatch-state",
        action="store_true",
        help="Create the separately gated final .clawpatch-only state commit; requires --push each or --push final.",
    )
    release.add_argument(
        "--trusted-host-codex-sandbox-bypass",
        action="store_true",
        help=(
            "Run Clawpatch Codex workers without Codex approvals or sandboxing. "
            "Use only for trusted code on a host that already provides isolation."
        ),
    )
    release.add_argument(
        "--resume-stopped",
        action="store_true",
        help="resume one exact standalone-supervisor checkpoint instead of starting fresh",
    )
    release.add_argument("--timeout-minutes", type=int, default=15)
    release.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "release-sweep":
            report = release_sweep(
                Path(args.repo),
                apply=args.apply,
                branch=args.branch,
                push_mode=args.push,
                publish_clawpatch_state=args.publish_clawpatch_state,
                trusted_host_codex_sandbox_bypass=args.trusted_host_codex_sandbox_bypass,
                fresh=not args.resume_stopped,
                timeout_minutes=args.timeout_minutes,
            )
            formatter = format_release_sweep
        else:
            parser.error("Unknown Clawpatch command.")
    except SafetyError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"CLAWPATCH WORKFLOW: STOPPED\n{exc}")
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(formatter(report), end="")
    return int(report.get("exit_code", 0 if report.get("ok") else 2))


def _run_root(repo: Path, run_id: str) -> Path:
    value = str(run_id).strip()
    candidate = Path(value)
    if not value or candidate.is_absolute() or len(candidate.parts) != 1 or value in {".", ".."}:
        raise SafetyError(f"Invalid run id: {run_id!r}")
    base = repo.expanduser().resolve() / PROJECT_DIR / "runs"
    resolved = (base / value).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise SafetyError(f"Run id escapes repository run directory: {run_id!r}") from exc
    return resolved


def _planning_directory(run_root: Path) -> Path:
    planning = run_root / "artifacts" / "planning"
    for component in (run_root / "artifacts", planning):
        try:
            state = component.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SafetyError(
                f"Cannot validate planning artifact directory: {component}: {exc}"
            ) from exc
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(state.st_mode) or bool(
            getattr(state, "st_file_attributes", 0) & reparse_point
        ):
            raise SafetyError(f"Planning artifact path cannot contain symlinks: {component}")
        if not stat.S_ISDIR(state.st_mode):
            raise SafetyError(
                f"Planning artifact path component is not a directory: {component}"
            )
    resolved = planning.resolve()
    try:
        resolved.relative_to(run_root)
    except ValueError as exc:
        raise SafetyError(f"Planning artifact directory escapes run root: {planning}") from exc
    return planning


def _descriptor_relative_planning_supported() -> bool:
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_dir_fd
        and os.link in os.supports_follow_symlinks
        and os.rename in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


@contextmanager
def _pinned_planning_directory(
    run_root: Path,
) -> Iterator[
    tuple[Path, int, os.stat_result, int, os.stat_result, int]
]:
    planning = _planning_directory(run_root)
    if not _descriptor_relative_planning_supported():
        raise SafetyError(
            "Decision persistence requires descriptor-relative no-follow filesystem access."
        )

    run_descriptor = -1
    artifacts_descriptor = -1
    planning_descriptor = -1
    try:
        run_descriptor = os.open(run_root, _directory_flags())
        artifacts_descriptor = os.open(
            "artifacts",
            _directory_flags(),
            dir_fd=run_descriptor,
        )
        planning_descriptor = os.open(
            planning.name,
            _directory_flags(),
            dir_fd=artifacts_descriptor,
        )
        planning_state = os.fstat(planning_descriptor)
        artifacts_state = os.fstat(artifacts_descriptor)
        _validate_pinned_planning(
            run_root,
            planning,
            planning_descriptor,
            planning_state,
        )
        yield (
            planning,
            planning_descriptor,
            planning_state,
            artifacts_descriptor,
            artifacts_state,
            run_descriptor,
        )
    except SafetyError:
        raise
    except OSError as exc:
        raise SafetyError(
            f"Cannot pin planning artifact directory: {planning}: {exc}"
        ) from exc
    finally:
        for descriptor in (
            planning_descriptor,
            artifacts_descriptor,
            run_descriptor,
        ):
            if descriptor >= 0:
                os.close(descriptor)


def _validate_pinned_planning(
    run_root: Path,
    planning: Path,
    planning_descriptor: int | None,
    expected: os.stat_result,
) -> None:
    try:
        _planning_directory(run_root)
        current = planning.lstat()
        opened = (
            expected
            if planning_descriptor is None
            else os.fstat(planning_descriptor)
        )
    except OSError as exc:
        raise SafetyError(
            f"Planning artifact directory changed during decision persistence: {planning}: {exc}"
        ) from exc
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
        or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        raise SafetyError(
            f"Planning artifact directory changed during decision persistence: {planning}"
        )


def _republish_pinned_artifacts(
    run_descriptor: int,
    artifacts_descriptor: int,
    artifacts_expected: os.stat_result,
    planning_descriptor: int,
    planning_expected: os.stat_result,
    planning: Path,
    blocking_decisions_sha256: str,
) -> None:
    claimed_name = f".artifacts.answer-{secrets.token_hex(16)}"
    claimed = False
    try:
        os.rename(
            "artifacts",
            claimed_name,
            src_dir_fd=run_descriptor,
            dst_dir_fd=run_descriptor,
        )
        claimed = True
        current_artifacts = os.stat(
            claimed_name,
            dir_fd=run_descriptor,
            follow_symlinks=False,
        )
        opened_artifacts = os.fstat(artifacts_descriptor)
        current_planning = os.stat(
            planning.name,
            dir_fd=artifacts_descriptor,
            follow_symlinks=False,
        )
        opened_planning = os.fstat(planning_descriptor)
        if (
            not stat.S_ISDIR(current_artifacts.st_mode)
            or not stat.S_ISDIR(opened_artifacts.st_mode)
            or not stat.S_ISDIR(current_planning.st_mode)
            or not stat.S_ISDIR(opened_planning.st_mode)
            or (current_artifacts.st_dev, current_artifacts.st_ino)
            != (artifacts_expected.st_dev, artifacts_expected.st_ino)
            or (opened_artifacts.st_dev, opened_artifacts.st_ino)
            != (artifacts_expected.st_dev, artifacts_expected.st_ino)
            or (current_planning.st_dev, current_planning.st_ino)
            != (planning_expected.st_dev, planning_expected.st_ino)
            or (opened_planning.st_dev, opened_planning.st_ino)
            != (planning_expected.st_dev, planning_expected.st_ino)
        ):
            raise SafetyError(
                f"Planning artifact directory changed during decision persistence: {planning}"
            )
        blocking = planning / "blocking-decisions.json"
        try:
            blocking_payload = _read_json_at(
                planning_descriptor,
                blocking.name,
                blocking,
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SafetyError(
                f"Blocking decision artifact is unreadable: {blocking}: {exc}"
            ) from exc
        if not _blocking_decisions_payload_matches(
            blocking_payload,
            blocking_decisions_sha256,
        ):
            raise SafetyError(
                f"Blocking decision artifact changed during decision persistence: {blocking}"
            )
        os.rename(
            claimed_name,
            "artifacts",
            src_dir_fd=run_descriptor,
            dst_dir_fd=run_descriptor,
        )
        claimed = False
        os.fsync(run_descriptor)
        published = os.stat(
            "artifacts",
            dir_fd=run_descriptor,
            follow_symlinks=False,
        )
        published_planning = os.stat(
            planning.name,
            dir_fd=artifacts_descriptor,
            follow_symlinks=False,
        )
        opened_planning = os.fstat(planning_descriptor)
        if (
            not stat.S_ISDIR(published.st_mode)
            or not stat.S_ISDIR(published_planning.st_mode)
            or not stat.S_ISDIR(opened_planning.st_mode)
            or (published.st_dev, published.st_ino)
            != (artifacts_expected.st_dev, artifacts_expected.st_ino)
            or (published_planning.st_dev, published_planning.st_ino)
            != (planning_expected.st_dev, planning_expected.st_ino)
            or (opened_planning.st_dev, opened_planning.st_ino)
            != (planning_expected.st_dev, planning_expected.st_ino)
        ):
            raise SafetyError(
                f"Planning artifact directory changed during decision persistence: {planning}"
            )
    except SafetyError:
        raise
    except OSError as exc:
        raise SafetyError(
            f"Cannot publish decision artifacts safely: {planning}: {exc}"
        ) from exc
    finally:
        if claimed:
            try:
                os.stat(
                    "artifacts",
                    dir_fd=run_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                try:
                    os.rename(
                        claimed_name,
                        "artifacts",
                        src_dir_fd=run_descriptor,
                        dst_dir_fd=run_descriptor,
                    )
                    os.fsync(run_descriptor)
                except OSError as exc:
                    raise SafetyError(
                        f"Cannot restore decision artifacts safely: {planning}: {exc}"
                    ) from exc
            except OSError as exc:
                raise SafetyError(
                    f"Cannot inspect decision artifacts during restoration: {planning}: {exc}"
                ) from exc
            else:
                raise SafetyError(
                    f"Cannot restore decision artifacts because the path was replaced: {planning}"
                )


def _read_json_at(directory_descriptor: int, name: str, path: Path) -> Any:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        opened = os.fstat(descriptor)
        current = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_nlink != 1
            or current.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise SafetyError(f"Blocking decision artifact is unsafe: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
        latest = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (latest.st_dev, latest.st_ino) != (opened.st_dev, opened.st_ino):
            raise SafetyError(f"Blocking decision artifact changed while reading: {path}")
        return payload
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _blocking_decisions_payload_matches(payload: Any, expected_sha256: str) -> bool:
    if not isinstance(payload, dict):
        return False
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        return False
    decisions, error = _validated_decisions(decisions)
    return error is None and sha256_json({"decisions": decisions}) == expected_sha256


def _restore_claimed_blocking_decisions(
    directory_descriptor: int,
    claimed_name: str,
    path: Path,
    expected_sha256: str,
) -> bool:
    try:
        os.link(
            claimed_name,
            path.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileExistsError:
        replacement = os.stat(
            path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(replacement.st_mode) or replacement.st_nlink != 1:
            raise SafetyError(
                f"Blocking decision artifact changed unsafely during persistence: {path}"
            )
        try:
            replacement_payload = _read_json_at(
                directory_descriptor,
                path.name,
                path,
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            replacement_payload = None
        os.unlink(claimed_name, dir_fd=directory_descriptor)
        os.fsync(directory_descriptor)
        return _blocking_decisions_payload_matches(
            replacement_payload,
            expected_sha256,
        )
    except OSError as exc:
        raise SafetyError(
            f"Cannot restore blocking decision artifact safely: {path}: {exc}"
        ) from exc

    claimed = os.stat(
        claimed_name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    restored = os.stat(
        path.name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISREG(claimed.st_mode)
        or not stat.S_ISREG(restored.st_mode)
        or claimed.st_nlink != 2
        or restored.st_nlink != 2
        or (claimed.st_dev, claimed.st_ino) != (restored.st_dev, restored.st_ino)
    ):
        raise SafetyError(
            f"Blocking decision artifact changed unsafely during persistence: {path}"
        )
    os.unlink(claimed_name, dir_fd=directory_descriptor)
    latest = os.stat(
        path.name,
        dir_fd=directory_descriptor,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISREG(latest.st_mode)
        or latest.st_nlink != 1
        or (latest.st_dev, latest.st_ino) != (restored.st_dev, restored.st_ino)
    ):
        raise SafetyError(
            f"Blocking decision artifact changed during restoration: {path}"
        )
    os.fsync(directory_descriptor)
    return True


@contextmanager
def _claimed_blocking_decisions(
    directory_descriptor: int,
    path: Path,
    expected_sha256: str,
) -> Iterator[str]:
    claimed_name = f".{path.name}.answer-{secrets.token_hex(16)}"
    try:
        os.rename(
            path.name,
            claimed_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise SafetyError(
            f"Cannot claim blocking decision artifact safely: {path}: {exc}"
        ) from exc
    try:
        yield claimed_name
    finally:
        try:
            restored = _restore_claimed_blocking_decisions(
                directory_descriptor,
                claimed_name,
                path,
                expected_sha256,
            )
        except SafetyError:
            raise
        except OSError as exc:
            raise SafetyError(
                f"Cannot restore blocking decision artifact safely: {path}: {exc}"
            ) from exc
        if not restored:
            raise SafetyError(
                f"Blocking decision artifact changed during decision persistence: {path}"
            )


def _atomic_write_json_at(
    directory_descriptor: int,
    name: str,
    data: Any,
    *,
    replace: bool = True,
) -> None:
    temporary_name = f".{name}.{secrets.token_hex(16)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    replaced = False
    completed = False
    temporary_exists = False
    try:
        descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=directory_descriptor,
        )
        temporary_exists = True
        payload = (
            json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Decision artifact write made no progress.")
            remaining = remaining[written:]
        os.fsync(descriptor)
        written_state = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = -1
        if replace:
            os.rename(
                temporary_name,
                name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            replaced = True
            temporary_exists = False
        else:
            os.link(
                temporary_name,
                name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            replaced = True
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            temporary_exists = False
        current = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino)
            != (written_state.st_dev, written_state.st_ino)
        ):
            raise SafetyError(f"Decision artifact changed during replacement: {name}")
        os.fsync(directory_descriptor)
        completed = True
    except SafetyError:
        raise
    except OSError as exc:
        raise SafetyError(f"Cannot write decision artifact safely: {name}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
        if replaced and not completed:
            try:
                os.unlink(name, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass


def _path_exists_at(directory_descriptor: int | None, name: str, path: Path) -> bool:
    if directory_descriptor is None:
        return path.exists()
    try:
        state = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(state.st_mode) or state.st_nlink != 1:
        raise SafetyError(f"Decision artifact is unsafe: {path}")
    return True


def _remove_resolution(
    planning_descriptor: int | None,
    resolved: Path,
) -> None:
    try:
        if planning_descriptor is None:
            resolved.unlink()
        else:
            os.unlink(resolved.name, dir_fd=planning_descriptor)
    except FileNotFoundError:
        pass


def _blocking_decisions_from_directory(
    run_root: Path,
    planning: Path,
    planning_descriptor: int | None,
    *,
    artifact_name: str = "blocking-decisions.json",
) -> list[object]:
    if decisions_fully_resolved(run_root):
        return []
    path = planning / "blocking-decisions.json"
    if not _path_exists_at(planning_descriptor, artifact_name, path):
        return []
    try:
        payload = (
            read_json(path)
            if planning_descriptor is None
            else _read_json_at(planning_descriptor, artifact_name, path)
        )
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SafetyError(f"Blocking decision artifact is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SafetyError(f"Blocking decision artifact must contain a JSON object: {path}")
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise SafetyError(f"Blocking decision artifact field 'decisions' must be an array: {path}")
    return decisions


def _blocking_decisions(run_root: Path) -> list[object]:
    planning = _planning_directory(run_root)
    return _blocking_decisions_from_directory(run_root, planning, None)


def _blocking_decisions_match(
    run_root: Path,
    planning: Path,
    planning_descriptor: int | None,
    expected_sha256: str,
    *,
    artifact_name: str = "blocking-decisions.json",
) -> bool:
    decisions = _blocking_decisions_from_directory(
        run_root,
        planning,
        planning_descriptor,
        artifact_name=artifact_name,
    )
    decisions, error = _validated_decisions(decisions)
    return error is None and sha256_json({"decisions": decisions}) == expected_sha256


def _validated_decisions(decisions: list[object]) -> tuple[list[dict], str | None]:
    validated: list[dict] = []
    for index, decision in enumerate(decisions, 1):
        if not isinstance(decision, dict):
            return [], f"Decision {index} is not an object."
        decision_id = str(decision.get("id") or "").strip()
        options_value = decision.get("options")
        if not decision_id:
            return [], f"Decision {index} has no id."
        if not isinstance(options_value, list) or not options_value:
            return [], f"Decision {decision_id!r} has no selectable options."
        options = [str(item).strip() for item in options_value if str(item).strip()]
        if not options:
            return [], f"Decision {decision_id!r} has no selectable options."
        item = dict(decision)
        item["options"] = options
        validated.append(item)
    return validated, None


def _decisions_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="manageroo decisions",
        description="Show or answer high-impact product decisions that Manageroo could not safely infer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("show", "answer"):
        item = sub.add_parser(command)
        item.add_argument("run_id")
        item.add_argument("--repo", default=".")
        if command == "show":
            item.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_root = _run_root(Path(args.repo), args.run_id)
    except SafetyError as exc:
        parser.error(str(exc))
    try:
        decisions = _blocking_decisions(run_root)
    except SafetyError as exc:
        error = f"Cannot read blocking decisions: {exc}"
        if args.command == "show" and args.json:
            print(json.dumps({"ok": False, "error": error}, indent=2))
        else:
            print(error, file=sys.stderr)
        return 2

    decisions, validation_error = _validated_decisions(decisions)
    if validation_error:
        error = f"Cannot read blocking decisions: {validation_error}"
        if args.command == "show" and args.json:
            print(json.dumps({"ok": False, "error": error}, indent=2))
        else:
            print(error, file=sys.stderr)
        return 2

    if not decisions:
        if args.command == "show" and args.json:
            print(json.dumps({"run_id": args.run_id, "decisions": []}, indent=2))
        else:
            print("No unresolved blocking decisions were found for that run.")
        return 1

    if args.command == "show":
        if args.json:
            print(json.dumps({"run_id": args.run_id, "decisions": decisions}, indent=2))
        else:
            _planning_directory(run_root)
            markdown = render_blocking_questions(run_root)
            text = markdown.read_text(encoding="utf-8") if markdown else "No blocking questions found."
            print(text, end="")
        return 0

    blocking_decisions_sha256 = sha256_json({"decisions": decisions})
    answers: list[dict[str, str]] = []
    for index, decision in enumerate(decisions, 1):
        question = str(decision.get("question") or f"Decision {index}")
        why = str(decision.get("why") or "")
        options = [str(item) for item in decision["options"]]
        recommended = str(decision.get("recommended") or "")
        print(f"\n{index}. {question}")
        if why:
            print(f"Why: {why}")
        for option_index, option in enumerate(options, 1):
            marker = " (recommended)" if recommended and option == recommended else ""
            print(f"  {option_index}) {option}{marker}")
        while True:
            suffix = f" [{options.index(recommended) + 1}]" if recommended in options else ""
            raw = input(f"Choose 1-{len(options)}{suffix}: ").strip()
            if not raw and recommended in options:
                chosen = recommended
                break
            try:
                selected = int(raw)
            except ValueError:
                selected = 0
            if 1 <= selected <= len(options):
                chosen = options[selected - 1]
                break
            print("Choose one of the numbered options.")
        answers.append({"id": str(decision.get("id") or ""), "chosen": chosen})

    try:
        with _pinned_planning_directory(run_root) as (
            planning,
            planning_descriptor,
            planning_state,
            artifacts_descriptor,
            artifacts_state,
            run_descriptor,
        ):
            resolved = planning / "resolved-decisions.json"
            lock_target = run_root / "artifacts" / "resolved-decisions.json"
            with config_mutation_lock(lock_target):
                _validate_pinned_planning(
                    run_root,
                    planning,
                    planning_descriptor,
                    planning_state,
                )
                if _path_exists_at(
                    planning_descriptor,
                    resolved.name,
                    resolved,
                ):
                    print(
                        "Decision answers were not saved because another decision answer "
                        "session already saved a resolution for this run.",
                        file=sys.stderr,
                    )
                    return 2
                if not _blocking_decisions_match(
                    run_root,
                    planning,
                    planning_descriptor,
                    blocking_decisions_sha256,
                ):
                    print(
                        "Decision answers were not saved because the blocking decisions "
                        "changed while answers were being entered. Review the current "
                        "decisions and answer again.",
                        file=sys.stderr,
                    )
                    return 2
                payload = {
                    "run_id": args.run_id,
                    "answered_at": utc_now(),
                    "blocking_decisions_sha256": blocking_decisions_sha256,
                    "answers": answers,
                }
                _validate_pinned_planning(
                    run_root,
                    planning,
                    planning_descriptor,
                    planning_state,
                )
                if not _blocking_decisions_match(
                    run_root,
                    planning,
                    planning_descriptor,
                    blocking_decisions_sha256,
                ):
                    print(
                        "Decision answers were not saved because the blocking decisions "
                        "changed while answers were being entered. Review the current "
                        "decisions and answer again.",
                        file=sys.stderr,
                    )
                    return 2
                resolution_written = False
                try:
                    blocking = planning / "blocking-decisions.json"
                    with _claimed_blocking_decisions(
                        planning_descriptor,
                        blocking,
                        blocking_decisions_sha256,
                    ) as claimed_name:
                        if not _blocking_decisions_match(
                            run_root,
                            planning,
                            planning_descriptor,
                            blocking_decisions_sha256,
                            artifact_name=claimed_name,
                        ):
                            print(
                                "Decision answers were not saved because the blocking decisions "
                                "changed while answers were being entered. Review the current "
                                "decisions and answer again.",
                                file=sys.stderr,
                            )
                            return 2
                        try:
                            blocking_payload = _read_json_at(
                                planning_descriptor,
                                claimed_name,
                                blocking,
                            )
                        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                            raise SafetyError(
                                f"Blocking decision artifact is unreadable: {blocking}: {exc}"
                            ) from exc
                        if not _blocking_decisions_payload_matches(
                            blocking_payload,
                            blocking_decisions_sha256,
                        ):
                            print(
                                "Decision answers were not saved because the blocking decisions "
                                "changed while answers were being entered. Review the current "
                                "decisions and answer again.",
                                file=sys.stderr,
                            )
                            return 2
                        _atomic_write_json_at(
                            planning_descriptor,
                            resolved.name,
                            payload,
                            replace=False,
                        )
                        resolution_written = True
                        _atomic_write_json_at(
                            planning_descriptor,
                            blocking.name,
                            blocking_payload,
                            replace=False,
                        )
                        _validate_pinned_planning(
                            run_root,
                            planning,
                            planning_descriptor,
                            planning_state,
                        )
                    _validate_pinned_planning(
                        run_root,
                        planning,
                        planning_descriptor,
                        planning_state,
                    )
                except BaseException:
                    if resolution_written:
                        _remove_resolution(planning_descriptor, resolved)
                    raise
            try:
                _validate_pinned_planning(
                    run_root,
                    planning,
                    planning_descriptor,
                    planning_state,
                )
                _republish_pinned_artifacts(
                    run_descriptor,
                    artifacts_descriptor,
                    artifacts_state,
                    planning_descriptor,
                    planning_state,
                    planning,
                    blocking_decisions_sha256,
                )
            except BaseException:
                if resolution_written:
                    _remove_resolution(planning_descriptor, resolved)
                raise
    except SafetyError as exc:
        print(f"Cannot save decision answers: {exc}", file=sys.stderr)
        return 2
    repo = Path(args.repo).expanduser().resolve()
    print(f"\nSaved {len(answers)} decision answer(s).")
    print("Next: " + shlex.join(["manageroo", "run", "--continue", args.run_id, "--repo", str(repo), "--apply"]))
    return 0


def _root_help() -> str:
    base = cli_parser().format_help().rstrip()
    return (
        base
        + "\n\nProduct certification:\n"
        + "  prove                 Run adversarial end-to-end Manageroo product proof.\n"
        + "                        Uses any available supported live coding agent.\n"
        + "\nDiscovery and host context:\n"
        + "  capacity              Inspect host CPU, RAM, GPU/VRAM, and disk as context only.\n"
        + "  decisions             Show or answer high-impact questions surfaced during a run.\n"
        + "  host-skills           Inspect host skills without modifying or owning them.\n"
        + "\nCommand-owned repair automation:\n"
        + "  clawpatch release-sweep  Invoke the standalone ClawPatch supervisor adapter.\n"
        + "                            Preserve, reconcile, and retry the same current finding.\n"
        + "                            Dry-run by default; --apply mutates; --push is always explicit.\n"
        + "                        Cross-platform; one commit per successful fix by default.\n"
        + "\nRecommended stack maintenance:\n"
        + "  stack-update          Dry-run upstream-supported updates; optionally name tools; pass --apply explicitly.\n"
    )


def main() -> int:
    from .entrypoint_policy import install_entrypoint_policy

    install_entrypoint_policy(sys.modules[__name__])
    argv = sys.argv[1:]
    if argv and argv[0] == "prove":
        return _prove_main(argv[1:])
    if argv and argv[0] == "capacity":
        return _capacity_main(argv[1:])
    if argv and argv[0] == "host-skills":
        return _host_skills_main(argv[1:])
    if argv and argv[0] == "decisions":
        return _decisions_main(argv[1:])
    if argv and argv[0] == "clawpatch":
        return _clawpatch_main(argv[1:])
    if argv and argv[0] == "stack-update":
        return _stack_update_main(argv[1:])
    if argv in (["--help"], ["-h"]):
        print(_root_help(), end="")
        return 0
    return cli_main(_provider_neutral_argv(argv))
