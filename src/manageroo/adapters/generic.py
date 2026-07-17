from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, ConfigurationError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate


PROMPT_TRANSPORTS = {"file_path", "argument", "stdin"}


class GenericAdapter(AgentAdapter):
    """Universal CLI adapter for interchangeable coding-agent workers.

    Manageroo owns the worker protocol. A configured CLI only needs a deterministic
    prompt transport and a response containing schema-valid JSON. Provider-specific
    behavior stays in configuration rather than in the controller's completion rules.
    """

    def __init__(
        self,
        argv_template: Sequence[str],
        runner: CommandRunner,
        *,
        prompt_transport: str = "file_path",
    ):
        if not argv_template:
            raise ConfigurationError("Generic adapter requires a non-empty argv template.")
        if prompt_transport not in PROMPT_TRANSPORTS:
            choices = ", ".join(sorted(PROMPT_TRANSPORTS))
            raise ConfigurationError(
                f"Unknown generic prompt transport {prompt_transport!r}. Available: {choices}"
            )
        self.argv_template = list(argv_template)
        self.runner = runner
        self.prompt_transport = prompt_transport

    def _values(self, request: AgentRequest) -> dict[str, str]:
        prompt_text = request.prompt_path.read_text(encoding="utf-8", errors="replace")
        return {
            "prompt": str(request.prompt_path),
            "prompt_path": str(request.prompt_path),
            "prompt_text": prompt_text,
            "schema": str(request.schema_path),
            "output": str(request.output_path),
            "cwd": str(request.cwd),
            "role": request.role,
            "sandbox": request.sandbox,
        }

    def _render(self, request: AgentRequest) -> tuple[list[str], str | None]:
        values = self._values(request)
        argv = [item.format(**values) for item in self.argv_template]
        input_text = values["prompt_text"] if self.prompt_transport == "stdin" else None

        rendered = "\n".join(argv)
        if self.prompt_transport == "file_path":
            if values["prompt"] not in argv and "{prompt}" not in " ".join(self.argv_template) and "{prompt_path}" not in " ".join(self.argv_template):
                raise ConfigurationError(
                    "file_path prompt transport requires {prompt} or {prompt_path} in argv_template."
                )
        elif self.prompt_transport == "argument":
            if values["prompt_text"] not in rendered and "{prompt_text}" not in " ".join(self.argv_template):
                raise ConfigurationError(
                    "argument prompt transport requires {prompt_text} in argv_template."
                )
        return argv, input_text

    def doctor(self, cwd: Path) -> dict:
        executable = self.argv_template[0]
        return {
            "ok": shutil.which(executable) is not None,
            "adapter": "generic",
            "executable": executable,
            "prompt_transport": self.prompt_transport,
            "warning": "Generic adapters cannot guarantee provider-level sandbox enforcement.",
        }

    def run(self, request: AgentRequest) -> AgentResponse:
        argv, input_text = self._render(request)
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            input_text=input_text,
            log_name=f"agent-{request.output_path.stem}",
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
