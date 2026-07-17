#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(argv: list[str], *, timeout: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=timeout,
        )
        return {
            "argv": argv,
            "exit_code": result.returncode,
            "output": result.stdout,
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
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
    proof = run(prove_argv, timeout=3600)
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

    package = run([sys.executable, "scripts/package_release.py"], timeout=3600)
    report = {
        "ok": package["exit_code"] == 0,
        "stage": "complete" if package["exit_code"] == 0 else "package-release",
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
