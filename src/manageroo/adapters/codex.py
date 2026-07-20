from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..branding import FULL_NAME
from ..errors import AgentExecutionError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate
from ..util import atomic_write_json


_BWRAP_LOOPBACK_FAILURE = "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted"


def _codex_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a Codex structured-output-compatible copy of a JSON schema.

    Codex's strict structured-output path requires every object schema to:
    - explicitly forbid undeclared properties; and
    - list every declared property in ``required``.

    Manageroo keeps its repository-owned schemas as the source of truth and
    only tightens the transient schema passed to Codex. Local validation still
    uses the original schema after the agent returns.
    """

    normalized = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            properties = node.get("properties")
            if node_type == "object" or isinstance(properties, dict):
                node["additionalProperties"] = False
                if isinstance(properties, dict):
                    node["required"] = list(properties.keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized


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

    def _argv(
        self,
        request: AgentRequest,
        codex_schema_path: Path,
        *,
        sandbox: str,
    ) -> list[str]:
        argv = [
            self.executable,
            "exec",
            "--json",
            "--sandbox",
            sandbox,
            "--output-schema",
            str(codex_schema_path),
            "--output-last-message",
            str(request.output_path),
            "-C",
            str(request.cwd),
        ]
        if self.model:
            argv.extend(["--model", self.model])
        argv.append("-")
        return argv

    def _run_codex(
        self,
        request: AgentRequest,
        *,
        prompt: str,
        codex_schema_path: Path,
        sandbox: str,
        log_suffix: str = "",
    ):
        argv = self._argv(request, codex_schema_path, sandbox=sandbox)
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            input_text=prompt,
            log_name=(
                f"agent-{request.output_path.parent.name}-{request.output_path.stem}{log_suffix}"
            ),
        )
        return argv, result

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
        source_schema = load_schema(request.schema_path)
        codex_schema_path = request.output_path.with_suffix(".codex-schema.json")
        atomic_write_json(codex_schema_path, _codex_compatible_schema(source_schema))

        argv, result = self._run_codex(
            request,
            prompt=prompt,
            codex_schema_path=codex_schema_path,
            sandbox=request.sandbox,
        )

        diagnostics = (result.stdout or "") + "\n" + (result.stderr or "")
        if request.sandbox == "workspace-write" and _BWRAP_LOOPBACK_FAILURE in diagnostics:
            # Some Linux hosts cannot initialize Codex's bubblewrap network namespace
            # even though the process itself exits successfully with a blocked result.
            # Retry only this exact host-sandbox initialization failure with Codex's
            # unrestricted sandbox mode. Manageroo's outer TransactionalAdapter still
            # snapshots controller truth, rolls back failed attempts, and validates the
            # final repository diff before work can be accepted.
            for path in (
                request.output_path,
                request.output_path.with_suffix(".validated.json"),
            ):
                if path.is_file() or path.is_symlink():
                    path.unlink()
            argv, result = self._run_codex(
                request,
                prompt=prompt,
                codex_schema_path=codex_schema_path,
                sandbox="danger-full-access",
                log_suffix="-host-sandbox-fallback",
            )

        if not result.passed:
            stdout_tail = (result.stdout or "")[-8000:].strip()
            stderr_tail = (result.stderr or "")[-4000:].strip()
            details = []
            if stdout_tail:
                details.append("stdout:\n" + stdout_tail)
            if stderr_tail:
                details.append("stderr:\n" + stderr_tail)
            if not details:
                details.append("Codex produced no stdout or stderr diagnostics.")
            raise AgentExecutionError(
                f"Codex role {request.role!r} failed with exit code {result.exit_code}:\n"
                + "\n\n".join(details)
            )
        if not request.output_path.exists():
            raise AgentExecutionError(
                f"Codex did not create its output-last-message file for role {request.role}."
            )
        raw = request.output_path.read_text(encoding="utf-8", errors="replace")
        data = extract_json(raw)
        validate(data, source_schema)
        atomic_write_json(request.output_path.with_suffix(".validated.json"), data)
        return AgentResponse(
            role=request.role,
            data=data,
            raw_text=raw,
            command=argv,
            stdout=result.stdout,
            stderr=result.stderr,
        )
