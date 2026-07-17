from __future__ import annotations

import shutil

from .base import AgentAdapter
from .codex import CodexAdapter
from .generic import GenericAdapter
from .mock import MockAdapter
from .pool import WorkerPoolAdapter
from ..config import agent_preset
from ..errors import ConfigurationError
from ..runner import CommandRunner


def _generic_sandbox_argv(agent: dict) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    read_only = list(agent.get("sandbox_read_only_argv", []) or [])
    workspace_write = list(agent.get("sandbox_workspace_write_argv", []) or [])
    if read_only:
        mapping["read-only"] = read_only
    if workspace_write:
        mapping["workspace-write"] = workspace_write
    return mapping


def _build_single(agent: dict, runner: CommandRunner) -> AgentAdapter:
    adapter = agent["adapter"]
    if adapter == "codex":
        return CodexAdapter(
            executable=agent["executable"],
            runner=runner,
            model=agent.get("model", ""),
        )
    if adapter == "mock":
        return MockAdapter()
    if adapter == "generic":
        return GenericAdapter(
            list(agent.get("argv_template", []) or []),
            runner,
            prompt_transport=agent.get("prompt_transport", "file_path"),
            sandbox_argv=_generic_sandbox_argv(agent),
        )
    raise ConfigurationError(f"Unknown agent adapter: {adapter}")


def build_adapter(config: dict, runner: CommandRunner) -> AgentAdapter:
    agent = config["agent"]
    if agent["adapter"] != "auto":
        return _build_single(agent, runner)

    candidate_names = list(agent.get("candidates", []) or ["codex", "claude-code", "gemini"])
    workers: list[tuple[str, AgentAdapter]] = []
    for name in candidate_names:
        candidate = agent_preset(str(name))
        executable = str(candidate.get("executable") or "")
        if not executable or shutil.which(executable) is None:
            continue
        workers.append((str(name), _build_single(candidate, runner)))
    return WorkerPoolAdapter(workers)
