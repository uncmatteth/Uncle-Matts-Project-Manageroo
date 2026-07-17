from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..branding import FULL_NAME
from ..errors import AgentExecutionError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate
from ..util import atomic_write_json


class CodexAdapter(AgentAdapter):
    """Runs a fresh Codex process for each role.

    The adapter intentionally relies on documented non-interactive primitives:
    a repository working directory, an explicit sandbox, an output schema, and
    an output-last-message file. `doctor` blocks execution when the installed
    CLI does not expose those flags.
    """

    REQUIRED_FLAGS = (
        "--output-schema",
        "--output-last-message",
        "--sandbox",
    )

    def __init__(self, executable: str, runner: CommandRunner, model: str = ""):
        self.executable = executable
        self.runner = runner
        self.model = model

    def doctor(self, cwd: Path) -> dict:
        found = shutil.which(self.executable)
        if not found:
            return {
                "ok": False,
                "adapter": "codex",
                "executable": self.executable,
                "error": "Codex executable not found on PATH.",
            }
        version = self.runner.run([self.executable, "--version"], cwd=cwd, timeout_seconds=30)
        help_result = self.runner.run(
            [self.executable, "exec", "--help"], cwd=cwd, timeout_seconds=30
        )
        missing = [flag for flag in self.REQUIRED_FLAGS if flag not in help_result.stdout]
        return {
            "ok": version.passed and help_result.passed and not missing,
            "adapter": "codex",
            "path": found,
            "version": version.stdout.strip() or version.stderr.strip(),
            "missing_required_flags": missing,
        }

    def run(self, request: AgentRequest) -> AgentResponse:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        packet_text = request.prompt_path.read_text(encoding="utf-8", errors="replace")
        prompt = (
            f"You are a role inside {FULL_NAME}.\n"
            "The following packet is complete and authoritative. Do not rely on prior chat "
            "context. Follow it exactly. Return only JSON conforming to the supplied schema. "
            "Do not commit, push, switch branches, alter .git, or edit controller files.\n\n"
            + packet_text
        )
        argv = [
            self.executable,
            "exec",
            "--json",
            "--sandbox",
            request.sandbox,
            "--output-schema",
            str(request.schema_path),
            "--output-last-message",
            str(request.output_path),
            "-C",
            str(request.cwd),
        ]
        if self.model:
            argv.extend(["--model", self.model])
        argv.append("-")
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            input_text=prompt,
            log_name=f"agent-{request.output_path.parent.name}-{request.output_path.stem}",
        )
        if not result.passed:
            raise AgentExecutionError(
                f"Codex role {request.role!r} failed with exit code {result.exit_code}:\n"
                f"{result.stderr[-4000:]}"
            )
        if not request.output_path.exists():
            raise AgentExecutionError(
                f"Codex did not create its output-last-message file for role {request.role}."
            )
        raw = request.output_path.read_text(encoding="utf-8", errors="replace")
        data = extract_json(raw)
        schema = load_schema(request.schema_path)
        validate(data, schema)
        atomic_write_json(request.output_path.with_suffix(".validated.json"), data)
        return AgentResponse(
            role=request.role,
            data=data,
            raw_text=raw,
            command=argv,
            stdout=result.stdout,
            stderr=result.stderr,
        )
