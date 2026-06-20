from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, ConfigurationError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate


class GenericAdapter(AgentAdapter):
    """Adapter for a CLI that can accept a prompt file and emit JSON.

    It is detection-based, not a hard sandbox. It is disabled unless the
    operator explicitly supplies an argv template.
    """

    def __init__(self, argv_template: Sequence[str], runner: CommandRunner):
        if not argv_template:
            raise ConfigurationError("Generic adapter requires a non-empty argv template.")
        self.argv_template = list(argv_template)
        self.runner = runner

    def _render(self, request: AgentRequest) -> list[str]:
        values = {
            "prompt": str(request.prompt_path),
            "schema": str(request.schema_path),
            "output": str(request.output_path),
            "cwd": str(request.cwd),
            "role": request.role,
            "sandbox": request.sandbox,
        }
        return [item.format(**values) for item in self.argv_template]

    def doctor(self, cwd: Path) -> dict:
        executable = self.argv_template[0]
        return {
            "ok": shutil.which(executable) is not None,
            "adapter": "generic",
            "executable": executable,
            "warning": "Generic adapters cannot guarantee provider-level sandbox enforcement.",
        }

    def run(self, request: AgentRequest) -> AgentResponse:
        argv = self._render(request)
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            log_name=f"agent-{request.role}",
        )
        if not result.passed:
            raise AgentExecutionError(
                f"Generic role {request.role!r} failed: {result.stderr[-4000:]}"
            )
        raw = (
            request.output_path.read_text(encoding="utf-8", errors="replace")
            if request.output_path.exists()
            else result.stdout
        )
        data = extract_json(raw)
        validate(data, load_schema(request.schema_path))
        return AgentResponse(
            role=request.role,
            data=data,
            raw_text=raw,
            command=argv,
            stdout=result.stdout,
            stderr=result.stderr,
        )
