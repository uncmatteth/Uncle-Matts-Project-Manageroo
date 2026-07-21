from __future__ import annotations

import subprocess
from typing import Any

from .util import redact_argv, redact_text


def _timeout_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def install_stack_doctor_policy(module: Any) -> None:
    if getattr(module, "_manageroo_stack_doctor_policy_installed", False):
        return

    original_run_probe = module.run_probe

    def run_probe(argv: list[str], timeout_seconds: int = 30) -> dict:
        try:
            completed = subprocess.run(
                argv,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                timeout=timeout_seconds,
            )
            return {
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "argv": list(argv),
                "output": completed.stdout or "",
            }
        except subprocess.TimeoutExpired as exc:
            output = _timeout_text(exc.stdout if exc.stdout is not None else exc.output)
            return {
                "ok": False,
                "exit_code": 124,
                "argv": list(argv),
                "output": output + "\nTIMEOUT",
            }
        except OSError as exc:
            return {"ok": False, "exit_code": 127, "argv": list(argv), "output": str(exc)}

    def safe_probe_record(probe: dict | None) -> dict | None:
        if probe is None:
            return None
        record = {
            "ok": bool(probe.get("ok")),
            "exit_code": probe.get("exit_code"),
            "argv": redact_argv([str(item) for item in probe.get("argv", [])]),
        }
        if not probe.get("ok"):
            record["output"] = redact_text(_timeout_text(probe.get("output")))[:2000]
        return record

    module.run_probe = run_probe
    module._safe_probe_record = safe_probe_record
    module._manageroo_stack_doctor_policy_installed = True
