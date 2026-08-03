#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PROOF_TIMEOUT_SECONDS = 14_400
PACKAGE_TIMEOUT_SECONDS = 7_200
PROCESS_TREE_GRACE_SECONDS = 5


def _timeout_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _prefer_output(current: str, candidate: str | bytes | None) -> str:
    replacement = _timeout_output(candidate)
    return replacement if len(replacement) >= len(current) else current


def _taskkill_process_tree(process: subprocess.Popen[str], *, force: bool) -> bool:
    argv = ["taskkill", "/PID", str(process.pid), "/T"]
    if force:
        argv.append("/F")
    try:
        result = subprocess.run(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            timeout=PROCESS_TREE_GRACE_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _signal_process_tree(process: subprocess.Popen[str], *, force: bool) -> None:
    if os.name == "nt":
        signaled = _taskkill_process_tree(process, force=force)
        if not signaled and process.poll() is None:
            (process.kill if force else process.terminate)()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        if process.poll() is None:
            (process.kill if force else process.terminate)()


def run(argv: list[str], *, timeout: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    popen_kwargs: dict = {
        "cwd": ROOT,
        "env": env,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "shell": False,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **popen_kwargs)
    try:
        output, _ = process.communicate(timeout=timeout)
        return {
            "argv": argv,
            "exit_code": process.returncode,
            "output": output,
        }
    except subprocess.TimeoutExpired as exc:
        output = _timeout_output(exc.stdout)
        _signal_process_tree(process, force=False)
        cleanup_finished = False
        try:
            cleanup_output, _ = process.communicate(timeout=PROCESS_TREE_GRACE_SECONDS)
            output = _prefer_output(output, cleanup_output)
            cleanup_finished = True
        except subprocess.TimeoutExpired as cleanup_timeout:
            output = _prefer_output(output, cleanup_timeout.stdout)
        finally:
            # The direct child may exit during the grace period while a descendant
            # ignores termination. Always force the isolated group after grace.
            _signal_process_tree(process, force=True)
        if not cleanup_finished:
            try:
                cleanup_output, _ = process.communicate(timeout=PROCESS_TREE_GRACE_SECONDS)
                output = _prefer_output(output, cleanup_output)
            except subprocess.TimeoutExpired as cleanup_timeout:
                output = _prefer_output(output, cleanup_timeout.stdout)
                process.kill()
                try:
                    process.wait(timeout=PROCESS_TREE_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                if process.stdout is not None:
                    process.stdout.close()
        return {"argv": argv, "exit_code": 124, "output": output + "\nTIMEOUT"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Manageroo product certification and build the local release artifacts. "
            "The release fails closed if any proof, regression, packaging, or smoke lane fails."
        )
    )
    parser.add_argument(
        "--live-agent",
        choices=("codex", "claude-code", "gemini"),
        help="Force one installed live worker. Omit to use Manageroo automatic selection.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one machine-readable release report.",
    )
    args = parser.parse_args()

    prove_argv = [sys.executable, "-m", "manageroo", "prove", "--json"]
    if args.live_agent:
        prove_argv.extend(["--live-agent", args.live_agent])
    proof = run(prove_argv, timeout=PRODUCT_PROOF_TIMEOUT_SECONDS)
    proof_payload = None
    if proof["exit_code"] == 0:
        try:
            proof_payload = json.loads(proof["output"])
        except json.JSONDecodeError:
            proof["exit_code"] = 65
            proof["output"] += "\nProduct proof did not return valid JSON."
    if proof["exit_code"] != 0 or not isinstance(proof_payload, dict) or not proof_payload.get("ok"):
        report = {
            "ok": False,
            "stage": "product-proof",
            "proof": proof_payload,
            "command": proof,
            "release_created": False,
        }
        print(json.dumps(report, indent=2) if args.json else proof["output"], end="")
        return 2

    package = run(
        [sys.executable, "scripts/package_release.py"],
        timeout=PACKAGE_TIMEOUT_SECONDS,
    )
    report = {
        "ok": package["exit_code"] == 0,
        "stage": "complete" if package["exit_code"] == 0 else "packaging",
        "proof": proof_payload,
        "package": package,
        "release_created": package["exit_code"] == 0,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Manageroo product proof: COMPLETE")
        print(package["output"], end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
