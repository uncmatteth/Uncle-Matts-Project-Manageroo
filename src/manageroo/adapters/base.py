from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class AgentRequest:
    role: str
    prompt_path: Path
    schema_path: Path
    output_path: Path
    cwd: Path
    sandbox: str
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)
    before_launch: Callable[[AgentRequest, bool], AgentRequest] | None = field(
        default=None,
        repr=False,
    )


@dataclass
class AgentResponse:
    role: str
    data: dict[str, Any]
    raw_text: str
    command: list[str]
    stdout: str = ""
    stderr: str = ""


class AgentAdapter(ABC):
    @property
    def requires_host_capability_catalog(self) -> bool:
        """Whether this adapter can auto-load host skills that must be isolated."""
        return False

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResponse:
        raise NotImplementedError

    @abstractmethod
    def doctor(self, cwd: Path) -> dict[str, Any]:
        raise NotImplementedError
