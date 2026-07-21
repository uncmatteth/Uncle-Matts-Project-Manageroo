from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping, Sequence

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..errors import AgentExecutionError, ConfigurationError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate


PROMPT_TRANSPORTS = {"file_path", "argument", "stdin"}


class GenericAdapter(AgentAdapter):
    """Universal CLI adapter for interchangeable coding-agent workers."""

    def __init__(
        self,
        argv_template: Sequence[str],
        runner: CommandRunner,
        *,
        prompt_transport: str = "file_path",
        sandbox_argv: Mapping[str, Sequence[str]] | None = None,
        doctor_argv: Sequence[str] | None = None,
        required_help_flags: Sequence[str] | None = None,
    ):
        if not argv_template:
            raise ConfigurationError("Generic adapter requires a non-empty argv template.")
        if prompt_transport not in PROMPT_TRANSPORTS:
            choices = ", ".join(sorted(PROMPT_TRANSPORTS))
            raise ConfigurationError(f"Unknown generic prompt transport {prompt_transport!r}. Available: {choices}")
        self.argv_template = list(argv_template)
        self.runner = runner
        self.prompt_transport = prompt_transport
        self.sandbox_argv = {
            str(name): [str(item) for item in values]
            for name, values in (sandbox_argv or {}).items()
        }
        self.doctor_argv = [str(item) for item in (doctor_argv or [])]
        self.required_help_flags = [str(item) for item in (required_help_flags or [])]

    def _protocol_prompt(self, request: AgentRequest) -> tuple[str, Path]:
        prompt_text = request.prompt_path.read_text(encoding="utf-8", errors="replace")
        schema_text = request.schema_path.read_text(encoding="utf-8", errors="replace")
        combined = (
            prompt_text.rstrip()
            + "\n\n# Required output protocol\n\n"
            + "Return exactly one JSON value that validates against this JSON Schema. Do not wrap it in commentary.\n\n```json\n"
            + schema_text.rstrip()
            + "\n```\n"
        )
        protocol_path = request.prompt_path.parent / "protocol-prompt.md"
        protocol_path.write_text(combined, encoding="utf-8", newline="\n")
        return combined, protocol_path

    def _values(self, request: AgentRequest) -> dict[str, str]:
        prompt_text, protocol_path = self._protocol_prompt(request)
        return {
            "prompt": str(protocol_path),
            "prompt_path": str(protocol_path),
            "source_prompt": str(request.prompt_path),
            "prompt_text": prompt_text,
            "schema": str(request.schema_path),
            "output": str(request.output_path),
            "cwd": str(request.cwd),
            "role": request.role,
            "sandbox": request.sandbox,
        }

    def _render(self, request: AgentRequest) -> tuple[list[str], str | None, bool]:
        values = self._values(request)
        template_text = " ".join(self.argv_template)
        argv = [item.format(**values) for item in self.argv_template]
        argv.extend(item.format(**values) for item in self.sandbox_argv.get(request.sandbox, []))
        input_text = values["prompt_text"] if self.prompt_transport == "stdin" else None

        if self.prompt_transport == "file_path":
            if "{prompt}" not in template_text and "{prompt_path}" not in template_text:
                raise ConfigurationError("file_path prompt transport requires {prompt} or {prompt_path} in argv_template.")
        elif self.prompt_transport == "argument" and "{prompt_text}" not in template_text:
            raise ConfigurationError("argument prompt transport requires {prompt_text} in argv_template.")
        return argv, input_text, "{output}" in template_text

    def doctor(self, cwd: Path) -> dict:
        executable = self.argv_template[0]
        found = shutil.which(executable)
        if not found:
            return {
                "ok": False,
                "adapter": "generic",
                "executable": executable,
                "error": f"{executable} executable not found on PATH.",
                "prompt_transport": self.prompt_transport,
                "provider_sandbox_modes": sorted(self.sandbox_argv),
            }
        missing: list[str] = []
        help_exit_code: int | None = None
        if self.doctor_argv:
            result = self.runner.run(self.doctor_argv, cwd=cwd, timeout_seconds=30)
            passed = bool(getattr(result, "passed", False))
            help_exit_code = int(getattr(result, "exit_code", 0 if passed else 1))
            help_text = (getattr(result, "stdout", "") or "") + "\n" + (getattr(result, "stderr", "") or "")
            missing = [flag for flag in self.required_help_flags if flag not in help_text]
            if not passed:
                missing = list(self.required_help_flags) or ["doctor command failed"]
        return {
            "ok": not missing,
            "adapter": "generic",
            "executable": executable,
            "path": found,
            "prompt_transport": self.prompt_transport,
            "provider_sandbox_modes": sorted(self.sandbox_argv),
            "doctor_argv": self.doctor_argv,
            "doctor_exit_code": help_exit_code,
            "missing_required_flags": missing,
            "warning": (
                "Manageroo always verifies worker behavior independently. Provider-level permission enforcement is used only when configured for this worker."
            ),
        }

    @staticmethod
    def _clear_prior_outputs(request: AgentRequest) -> None:
        for path in (request.output_path, request.output_path.with_suffix(".validated.json")):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise AgentExecutionError(f"Could not clear stale generic-worker output before launch: {path}: {exc}") from exc

    def run(self, request: AgentRequest) -> AgentResponse:
        self._clear_prior_outputs(request)
        argv, input_text, expects_output_file = self._render(request)
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            input_text=input_text,
            log_name=f"agent-{request.output_path.parent.name}-{request.output_path.stem}",
        )
        if not result.passed:
            raise AgentExecutionError(f"Generic role {request.role!r} failed: {result.stderr[-4000:]}")
        if expects_output_file:
            if not request.output_path.is_file() or request.output_path.is_symlink():
                raise AgentExecutionError(
                    f"Generic role {request.role!r} was configured for file output but did not create a fresh regular output file."
                )
            raw = request.output_path.read_text(encoding="utf-8", errors="replace")
        else:
            raw = result.stdout or ""
            if not raw.strip():
                raise AgentExecutionError(f"Generic role {request.role!r} produced no current-launch stdout response.")
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
