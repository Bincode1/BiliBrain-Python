from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter


@dataclass(frozen=True)
class RuntimeExecRequest:
    workspace_root: Path
    command: str
    cwd: str = "."
    timeout_seconds: int = 30
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: float
    command: str
    cwd: str


class BaseToolRuntime(ABC):
    @abstractmethod
    async def exec(
        self,
        *,
        workspace_root: Path,
        command: str,
        cwd: str = ".",
        timeout_seconds: int = 30,
        env: dict[str, str] | None = None,
    ) -> RuntimeExecResult:
        raise NotImplementedError


@dataclass(frozen=True)
class RuntimeTimer:
    started_at: float = field(default_factory=perf_counter)

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.started_at) * 1000, 3)
