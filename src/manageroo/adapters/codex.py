from __future__ import annotations

import os
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
_DANGER_FALLBACK_ENV = "MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK"


def _codex_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
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


def _danger_fallback_enabled() -> bool:
    return os.environ.get(_DANGER_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class CodexAdapter(AgentAdapter):
    """Runs one fresh Codex process per role.

    Workspace-write is always attempted first. A second danger-full-access launch is permitted
    only when the operator explicitly opted in before launch *and* the first process failed with
    the exact known host bubblewrap initialization error. Successful or unrelated worker output
    can never authorize escalation.
    """

    REQUIRED_FLAGS = ("--output-schema", "--output-last-message", "--sandbox")

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
        help_result = self.runner.run([self.executable, "exec", "--help"], cwd=cwd, timeout_seconds=30)
        missing = [flag for flag in self.REQUIRED_FLAGS if flag not in help_result.stdout]
        return {
            "ok": version.passed and help_result.passed and not missing,
            "adapter": "codex",
            "path": found,
            "version": version.stdout.strip() or version.stderr.strip(),
            "missing_required_flags": missing,
            "danger_full_access_fallback_opted_in": _danger_fallback_enabled(),
            "stderr_triggered_escalation": False,
        }

    def _argv(self, request: AgentRequest, codex_schema_path: Path, *, sandbox: str) -> list[str]:
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

    def _run_codex(self, request: AgentRequest, *, prompt: str, codex_schema_path: Path, sandbox: str):
        argv = self._argv(request, codex_schema_path, sandbox=sandbox)
        result = self.runner.run(
            argv,
            cwd=request.cwd,
            timeout_seconds=request.timeout_seconds,
            input_text=prompt,
            log_name=f"agent-{request.output_path.parent.name}-{request.output_path.stem}",
        )
        return argv, result

    @staticmethod
    def _clear_prior_outputs(request: AgentRequest) -> None:
        for path in (request.output_path, request.output_path.with_suffix(".validated.json")):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise AgentExecutionError(f"Could not clear stale Codex output before launch: {path}: {exc}") from exc

    def run(self, request: AgentRequest) -> AgentResponse:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_prior_outputs(request)
        packet_text = request.prompt_path.read_text(encoding="utf-8", errors="replace")
        prompt = (
            f"You are a role inside {FULL_NAME}.\n"
            "The following packet is complete and authoritative. Do not rely on prior chat context. "
            "Follow it exactly. Return only JSON conforming to the supplied schema. "
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
        if (
            request.sandbox == "workspace-write"
            and not result.passed
            and _BWRAP_LOOPBACK_FAILURE in diagnostics
        ):
            if not _danger_fallback_enabled():
                raise AgentExecutionError(
                    "Codex could not initialize its workspace-write bubblewrap sandbox on this host. "
                    "Manageroo refused to escalate automatically. To explicitly allow one unrestricted "
                    f"retry after this exact host-sandbox initialization failure, set {_DANGER_FALLBACK_ENV}=1 for this run."
                )
            self._clear_prior_outputs(request)
            argv, result = self._run_codex(
                request,
                prompt=prompt,
                codex_schema_path=codex_schema_path,
                sandbox="danger-full-access",
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
                f"Codex role {request.role!r} failed with exit code {result.exit_code}:\n" + "\n\n".join(details)
            )
        if not request.output_path.is_file() or request.output_path.is_symlink():
            raise AgentExecutionError(f"Codex did not create a fresh regular output-last-message file for role {request.role}.")
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
