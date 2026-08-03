from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .clawpatch_release import CLAWPATCH_CHILD_WATCHDOG_SECONDS, release_sweep
from .errors import SafetyError


def _counter(event: dict[str, Any]) -> str:
    current = event.get("current", "?")
    total = event.get("total", "?")
    return f"[{current}/{total}]"


def _render_inspection(event: dict[str, Any]) -> str:
    inspection = event.get("inspection")
    finding = inspection.get("finding") if isinstance(inspection, dict) else None
    if not isinstance(finding, dict):
        return f"{_counter(event)} SHOW {event.get('finding_id', '')}"
    lines = [
        "",
        f"{_counter(event)} SHOW",
        f"$ {event.get('command', '')}",
        f"title: {finding.get('title', '')}",
        f"id: {finding.get('id', '')}",
        f"severity: {finding.get('severity', '')}",
        f"category: {finding.get('category', '')}",
    ]
    evidence = finding.get("evidence")
    if isinstance(evidence, list) and evidence:
        lines.append("evidence:")
        for item in evidence:
            if not isinstance(item, dict):
                continue
            start = item.get("startLine")
            end = item.get("endLine")
            location = str(item.get("path", ""))
            if isinstance(start, int):
                location += f":{start}"
                if isinstance(end, int) and end != start:
                    location += f"-{end}"
            symbol = item.get("symbol")
            if symbol:
                location += f" ({symbol})"
            lines.append(f"- {location}")
    for label, field in (
        ("reproduction", "reproduction"),
        ("recommendation", "recommendation"),
        ("minimum fix scope", "minimumFixScope"),
    ):
        value = finding.get(field)
        if value:
            lines.extend([f"{label}:", str(value)])
    validation = inspection.get("validation") if isinstance(inspection, dict) else None
    if isinstance(validation, list) and validation:
        lines.extend(["validation:", *[f"- {command}" for command in validation]])
    return "\n".join(lines)


def _render_event(event: dict[str, Any]) -> str:
    phase = event.get("phase")
    command_phases = {
        "preflight": "PROCESS PREFLIGHT",
        "status": "STATUS",
        "lock-cleanup": "LOCK CLEANUP",
        "baseline-validation": "BASELINE VALIDATION",
        "map": "MAP",
        "review": "REVIEW",
        "review-verification": "REVIEW VERIFICATION",
        "queue": "QUEUE",
        "show": "SHOW",
        "revalidate": "REVALIDATE",
        "revalidate-escalated": "REVALIDATE ESCALATED",
        "report": "REPORT",
    }
    if phase in command_phases:
        attempt = event.get("attempt")
        maximum = event.get("max_attempts")
        suffix = f" (attempt {attempt}/{maximum})" if attempt and maximum else ""
        return (
            f"\n{_counter(event)} {command_phases[str(phase)]}{suffix}\n"
            f"$ {event.get('command', '')}"
        )
    if phase == "finding":
        return _render_inspection(event)
    if phase == "fix":
        attempt = int(event.get("attempt", 1))
        maximum = event.get("max_attempts")
        if maximum:
            suffix = f" (attempt {attempt}/{maximum})"
        else:
            suffix = f" (attempt {attempt})" if attempt > 1 else ""
        return f"\n{_counter(event)} FIX{suffix}\n$ {event.get('command', '')}"
    if phase == "stopped":
        owned = event.get("owned_paths")
        paths = ", ".join(str(path) for path in owned) if isinstance(owned, list) else ""
        return (
            f"\n{_counter(event)} STOPPED - {event.get('outcome', 'not fixed')}\n"
            f"finding: {event.get('finding_id', '')}\n"
            f"source left in place: {paths or 'none'}"
        )
    if phase == "fixed":
        commit = event.get("commit") or "no source commit required"
        return f"\n{_counter(event)} FIXED\ncommit: {commit}"
    if phase == "continuing":
        commit = event.get("commit") or "no source commit required"
        return (
            f"\n{_counter(event)} OPEN - CONTINUING SAME FINDING\n"
            f"commit: {commit}"
        )
    detail = event.get("detail") or event.get("command") or phase or "working"
    return f"{_counter(event)} {str(detail).upper()}"


def main(
    argv: list[str] | None = None,
    *,
    run_sweep: Callable[..., dict[str, Any]] = release_sweep,
    heartbeat_seconds: float = 30,
) -> int:
    parser = argparse.ArgumentParser(
        prog="clawpatch-supervise",
        description="Visibly process ClawPatch's live queue one current finding at a time.",
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--branch", default="current")
    parser.add_argument("--push", choices=("none", "each", "final"), default="each")
    parser.add_argument("--publish-clawpatch-state", action="store_true")
    parser.add_argument("--trusted-host-codex-sandbox-bypass", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=CLAWPATCH_CHILD_WATCHDOG_SECONDS // 60,
    )
    args = parser.parse_args(argv)
    if args.timeout_minutes < 1:
        parser.error("--timeout-minutes must be at least 1")
    watchdog_seconds = args.timeout_minutes * 60

    state: dict[str, Any] = {
        "phase": "starting",
        "current": "?",
        "total": "?",
        "finding_id": "",
        "changed": time.monotonic(),
    }
    state_lock = threading.Lock()
    stopped = threading.Event()

    def display(event: dict[str, Any]) -> None:
        with state_lock:
            for key in ("command", "finding_id", "attempt", "max_attempts"):
                state.pop(key, None)
            state.update(event)
            state["changed"] = time.monotonic()
        print(_render_event(event), flush=True)

    def heartbeat() -> None:
        while not stopped.wait(heartbeat_seconds):
            with state_lock:
                snapshot = dict(state)
            elapsed = int(time.monotonic() - float(snapshot["changed"]))
            phase = str(snapshot.get("phase", "working"))
            attempt = snapshot.get("attempt")
            maximum = snapshot.get("max_attempts")
            attempt_text = f" attempt {attempt}/{maximum}" if attempt and maximum else ""
            if attempt and not maximum:
                attempt_text = f" attempt {attempt}"
            finding = f" {snapshot['finding_id']}" if snapshot.get("finding_id") else ""
            lines = [
                f"{_counter(snapshot)} still running: {phase}{attempt_text}{finding}",
                f"({elapsed}s in this displayed phase; child watchdog is "
                f"{watchdog_seconds}s)",
            ]
            if snapshot.get("command"):
                lines.append(f"$ {snapshot['command']}")
            print("\n".join(lines), flush=True)

    thread = None
    if heartbeat_seconds > 0:
        thread = threading.Thread(target=heartbeat, name="clawpatch-supervise-heartbeat", daemon=True)
        thread.start()

    print(
        f"ClawPatch external supervisor: repo={Path(args.repo).resolve()} "
        f"branch={args.branch} push={args.push} fresh={args.fresh} "
        f"timeout={args.timeout_minutes}m",
        flush=True,
    )
    try:
        report = run_sweep(
            Path(args.repo),
            apply=True,
            branch=args.branch,
            push_mode=args.push,
            publish_clawpatch_state=args.publish_clawpatch_state,
            trusted_host_codex_sandbox_bypass=args.trusted_host_codex_sandbox_bypass,
            fresh=args.fresh,
            child_timeout_seconds=watchdog_seconds,
            progress=display,
            integration_mode="external",
        )
    except SafetyError as exc:
        print(f"\nSTOPPED: {exc}", flush=True)
        return 2
    except KeyboardInterrupt:
        print("\nINTERRUPTED: stopped safely; use --fresh to start a new run.", flush=True)
        return 130
    finally:
        stopped.set()
        if thread is not None:
            thread.join(timeout=1)

    print(
        "\nCOMPLETE: "
        f"fixed={report.get('finding_count', 0)} "
        f"open={report.get('open_findings', '?')} "
        f"head={report.get('git_head', '')}",
        flush=True,
    )
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
