from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError


class ToolKind(str, Enum):
    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    NETWORK = "network"
    MEMORY = "memory"
    COMBAT = "combat"  # Hostile-Mesh specific: probe / exploit / claim / patch


@dataclass(slots=True)
class FileDiff:
    path: Path
    old_content: str
    new_content: str
    is_new_file: bool = False
    is_deletion: bool = False

    def to_unified_diff(self) -> str:
        import difflib

        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)
        if old_lines and not old_lines[-1].endswith("\n"):
            old_lines[-1] += "\n"
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        return "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="/dev/null" if self.is_new_file else str(self.path),
                tofile="/dev/null" if self.is_deletion else str(self.path),
            )
        )


@dataclass(slots=True)
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    diff: FileDiff | None = None
    exit_code: int | None = None

    @classmethod
    def ok(cls, output: str, **kwargs: Any) -> ToolResult:
        return cls(success=True, output=output, **kwargs)

    @classmethod
    def fail(cls, error: str, output: str = "", **kwargs: Any) -> ToolResult:
        return cls(success=False, output=output, error=error, **kwargs)

    def to_model_payload(self) -> str:
        if self.success:
            return self.output or "ok"
        body = self.error or "error"
        if self.output:
            body = f"{body}\n\n{self.output}"
        return body


@dataclass(slots=True)
class ToolInvocation:
    params: dict[str, Any]
    cwd: Path
    agent_id: str


@dataclass(slots=True)
class ToolConfirmation:
    tool_name: str
    params: dict[str, Any]
    description: str
    diff: FileDiff | None = None
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class Tool(abc.ABC):
    """Base class for every tool exposed to the LLM.

    Subclasses declare ``name``, ``description``, ``kind``, and a ``Schema``
    Pydantic model. The registry validates parameters against ``Schema`` *before*
    invoking ``execute``, so malformed model output cannot reach side-effecting
    code paths.
    """

    name: str = "base_tool"
    description: str = "abstract base"
    kind: ToolKind = ToolKind.READ
    Schema: type[BaseModel]

    @property
    def is_mutating(self) -> bool:
        return self.kind in {
            ToolKind.WRITE,
            ToolKind.SHELL,
            ToolKind.NETWORK,
            ToolKind.MEMORY,
            ToolKind.COMBAT,
        }

    def validate(self, params: dict[str, Any]) -> tuple[BaseModel | None, list[str]]:
        try:
            return self.Schema(**params), []
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(p) for p in err.get('loc', []))}: {err.get('msg')}"
                for err in exc.errors()
            ]
            return None, errors

    async def confirmation(self, invocation: ToolInvocation) -> ToolConfirmation | None:
        if not self.is_mutating:
            return None
        return ToolConfirmation(
            tool_name=self.name, params=invocation.params, description=self.description
        )

    @abc.abstractmethod
    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult: ...

    def to_anthropic_schema(self) -> dict[str, Any]:
        json_schema = self.Schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": json_schema.get("properties", {}),
                "required": json_schema.get("required", []),
                "additionalProperties": False,
            },
        }


__all__ = [
    "FileDiff",
    "Tool",
    "ToolConfirmation",
    "ToolInvocation",
    "ToolKind",
    "ToolResult",
]
