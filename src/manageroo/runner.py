from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .errors import SafetyError
from .util import atomic_write_json, redact_argv, redact_text, utc_now


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    cwd: str
    started_at: str
    finished_at: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return asdict(self)


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class CommandRunner:
    """Executes argv directly. shell=True is intentionally unavailable."""

    def __init__(self, log_root: Path | None = None):
        self.log_root = log_root
        if log_root:
            log_root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: int = 1800,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        log_name: str | None = None,
        check: bool = False,
    ) -> CommandResult:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise SafetyError("Commands must be non-empty argv arrays.")
        safe_argv = redact_argv(argv)
        started_at = utc_now()
        process_env = os.environ.copy()
        if env:
            process_env.update({str(k): str(v) for k, v in env.items()})
        try:
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                env=process_env,
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                shell=False,
                check=False,
            )
            result = CommandResult(
                argv=safe_argv,
                cwd=str(cwd),
                started_at=started_at,
                finished_at=utc_now(),
                exit_code=completed.returncode,
                stdout=redact_text(completed.stdout),
                stderr=redact_text(completed.stderr),
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                argv=safe_argv,
                cwd=str(cwd),
                started_at=started_at,
                finished_at=utc_now(),
                exit_code=124,
                stdout=redact_text(_timeout_text(exc.stdout)),
                stderr=redact_text(_timeout_text(exc.stderr)),
                timed_out=True,
            )
        except OSError as exc:
            result = CommandResult(
                argv=safe_argv,
                cwd=str(cwd),
                started_at=started_at,
                finished_at=utc_now(),
                exit_code=127,
                stdout="",
                stderr=redact_text(f"Could not launch command: {exc}"),
                timed_out=False,
            )
        if self.log_root and log_name:
            atomic_write_json(self.log_root / f"{log_name}.json", result.to_dict())
        if check and not result.passed:
            raise subprocess.CalledProcessError(
                result.exit_code, result.argv, result.stdout, result.stderr
            )
        return result
