from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from hostile_mesh_runtime.client.anthropic_client import TokenUsage
from hostile_mesh_runtime.tools.base import ToolResult


class AgentEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    TEXT_DELTA = "text_delta"
    TEXT_COMPLETE = "text_complete"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    LOOP_DETECTED = "loop_detected"
    CONTEXT_COMPRESSED = "context_compressed"


@dataclass(slots=True)
class AgentEvent:
    type: AgentEventType
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def agent_start(cls, message: str) -> AgentEvent:
        return cls(AgentEventType.AGENT_START, {"message": message})

    @classmethod
    def agent_end(cls, response: str | None, usage: TokenUsage | None) -> AgentEvent:
        # ``TokenUsage`` is a slotted dataclass — no ``__dict__``. Use asdict.
        return cls(
            AgentEventType.AGENT_END,
            {"response": response, "usage": asdict(usage) if usage else None},
        )

    @classmethod
    def agent_error(cls, error: str, details: dict[str, Any] | None = None) -> AgentEvent:
        return cls(AgentEventType.AGENT_ERROR, {"error": error, "details": details or {}})

    @classmethod
    def turn_start(cls, turn: int) -> AgentEvent:
        return cls(AgentEventType.TURN_START, {"turn": turn})

    @classmethod
    def turn_end(cls, turn: int) -> AgentEvent:
        return cls(AgentEventType.TURN_END, {"turn": turn})

    @classmethod
    def text_delta(cls, content: str) -> AgentEvent:
        return cls(AgentEventType.TEXT_DELTA, {"content": content})

    @classmethod
    def text_complete(cls, content: str) -> AgentEvent:
        return cls(AgentEventType.TEXT_COMPLETE, {"content": content})

    @classmethod
    def tool_call_start(cls, call_id: str, name: str, arguments: dict[str, Any]) -> AgentEvent:
        return cls(
            AgentEventType.TOOL_CALL_START,
            {"call_id": call_id, "name": name, "arguments": arguments},
        )

    @classmethod
    def tool_call_complete(cls, call_id: str, name: str, result: ToolResult) -> AgentEvent:
        return cls(
            AgentEventType.TOOL_CALL_COMPLETE,
            {
                "call_id": call_id,
                "name": name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "metadata": result.metadata,
                "diff": result.diff.to_unified_diff() if result.diff else None,
            },
        )

    @classmethod
    def loop_detected(cls, reason: str) -> AgentEvent:
        return cls(AgentEventType.LOOP_DETECTED, {"reason": reason})

    @classmethod
    def context_compressed(cls, summary_chars: int) -> AgentEvent:
        return cls(AgentEventType.CONTEXT_COMPRESSED, {"summary_chars": summary_chars})


__all__ = ["AgentEvent", "AgentEventType"]
