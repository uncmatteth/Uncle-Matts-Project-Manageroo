#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from manageroo.install_status import summarize_external_tools  # noqa: E402


def _gitnexus_record(lock: dict) -> dict | None:
    for item in lock.get("external_tools", []):
        if isinstance(item, dict) and item.get("name") == "gitnexus":
            return item
    return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def finalize(prefix: Path) -> dict:
    lock_path = prefix.expanduser().resolve() / "install-lock.json"
    if not lock_path.is_file():
        return {"ok": True, "skipped": True, "reason": "install-lock.json is not present yet"}

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    record = _gitnexus_record(lock)
    if not record:
        return {"ok": True, "skipped": True, "reason": "GitNexus was not part of this installation"}

    installed = bool(record.get("installed") or record.get("path"))
    if not installed:
        return {"ok": True, "skipped": True, "reason": "GitNexus is not installed"}
    if record.get("configured") is True:
        return {"ok": True, "skipped": True, "reason": "GitNexus is already configured"}

    executable = shutil.which("gitnexus") or record.get("path")
    if not executable:
        record["configured"] = False
        record["next_commands"] = ["gitnexus setup"]
        record["setup_result"] = {
            "ok": False,
            "error": "GitNexus was recorded as installed but no executable is visible on PATH.",
        }
        lock["stack_summary"] = summarize_external_tools(lock.get("external_tools", []))
        _write_json_atomic(lock_path, lock)
        return {"ok": False, "error": record["setup_result"]["error"]}

    result = subprocess.run(
        [str(executable), "setup"],
        cwd=str(Path.home()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        timeout=600,
    )
    output = (result.stdout or "")[-8000:]
    configured = result.returncode == 0
    record["configured"] = configured
    record["setup_result"] = {
        "ok": configured,
        "exit_code": result.returncode,
        "argv": [str(executable), "setup"],
        "output": output,
    }
    record["next_commands"] = [] if configured else ["gitnexus setup"]
    record["reason"] = (
        "GitNexus setup completed during Manageroo installation."
        if configured
        else "GitNexus installed, but setup did not complete successfully."
    )
    lock["stack_summary"] = summarize_external_tools(lock.get("external_tools", []))
    _write_json_atomic(lock_path, lock)
    return {"ok": configured, "configured": configured, "exit_code": result.returncode, "output": output}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Finish GitNexus setup when Manageroo selected and installed GitNexus."
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        default=Path.home() / ".local" / "share" / "manageroo",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = finalize(args.prefix)
    except subprocess.TimeoutExpired:
        result = {"ok": False, "error": "gitnexus setup timed out after 600 seconds"}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("skipped"):
        print(f"GITNEXUS: {result.get('reason', 'skipped')}")
    elif result.get("ok"):
        print("GITNEXUS: setup complete")
    else:
        print(f"GITNEXUS: setup failed: {result.get('error') or 'see setup output'}", file=sys.stderr)
        output = str(result.get("output") or "").strip()
        if output:
            print(output, file=sys.stderr)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
