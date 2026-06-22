from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentRequest:
    role: str
    prompt_path: Path
    schema_path: Path
    output_path: Path
    cwd: Path
    sandbox: str
    timeout_seconds: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    role: str
    data: dict[str, Any]
    raw_text: str
    command: list[str]
    stdout: str = ""
    stderr: str = ""


class AgentAdapter(ABC):
    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResponse:
        raise NotImplementedError

    @abstractmethod
    def doctor(self, cwd: Path) -> dict[str, Any]:
        raise NotImplementedError
