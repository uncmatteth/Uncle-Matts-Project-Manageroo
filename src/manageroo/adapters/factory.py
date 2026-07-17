from __future__ import annotations

import shutil
from pathlib import Path

from .base import AgentAdapter
from .budget import BudgetedAdapter
from .codex import CodexAdapter
from .generic import GenericAdapter
from .mock import MockAdapter
from .pool import WorkerPoolAdapter
from .transactional import TransactionalAdapter
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


def _build_raw(agent: dict, runner: CommandRunner) -> AgentAdapter:
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
            doctor_argv=list(agent.get("doctor_argv", []) or []),
            required_help_flags=list(agent.get("required_help_flags", []) or []),
        )
    raise ConfigurationError(f"Unknown agent adapter: {adapter}")


def _build_single(agent: dict, runner: CommandRunner) -> AgentAdapter:
    return TransactionalAdapter(_build_raw(agent, runner), runner)


def _build_unbudgeted(config: dict, runner: CommandRunner) -> AgentAdapter:
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


def _budget_state_path(runner: CommandRunner) -> Path | None:
    log_root = getattr(runner, "log_root", None)
    if log_root is None or Path(log_root).name != "logs":
        return None
    return Path(log_root).parent / "controller" / "budget.json"


def build_adapter(config: dict, runner: CommandRunner) -> AgentAdapter:
    inner = _build_unbudgeted(config, runner)
    budget = config.get("budget", {})
    return BudgetedAdapter(
        inner,
        max_total_worker_calls=int(budget.get("max_total_worker_calls", 0) or 0),
        max_runtime_minutes=float(budget.get("max_runtime_minutes", 0) or 0),
        state_path=_budget_state_path(runner),
    )
