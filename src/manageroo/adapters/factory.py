from __future__ import annotations

from .base import AgentAdapter
from .codex import CodexAdapter
from .generic import GenericAdapter
from .mock import MockAdapter
from ..errors import ConfigurationError
from ..runner import CommandRunner


def build_adapter(config: dict, runner: CommandRunner) -> AgentAdapter:
    adapter = config["agent"]["adapter"]
    if adapter == "codex":
        return CodexAdapter(
            executable=config["agent"]["executable"],
            runner=runner,
            model=config["agent"].get("model", ""),
        )
    if adapter == "mock":
        return MockAdapter()
    if adapter == "generic":
        template = config["agent"].get("argv_template", [])
        return GenericAdapter(template, runner)
    raise ConfigurationError(f"Unknown agent adapter: {adapter}")
