"""Hostile Mesh agent runtime.

Streaming Anthropic / OpenRouter loop with typed Pydantic tools, context
compression, infinite-loop detection, lifecycle hooks, six-mode permission
engine, and session/checkpoint primitives. Specialised for adversarial
combat agents whose tools include `inspect_self`, `patch_self`, `probe`,
`exploit`, and `claim`.
"""

from hostile_mesh_runtime.config import RuntimeConfig
from hostile_mesh_runtime.runtime.events import AgentEvent, AgentEventType
from hostile_mesh_runtime.runtime.orchestrator import Orchestrator
from hostile_mesh_runtime.runtime.session import Session
from hostile_mesh_runtime.tools.base import (
    Tool,
    ToolInvocation,
    ToolKind,
    ToolResult,
)
from hostile_mesh_runtime.tools.registry import ToolRegistry

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "Orchestrator",
    "RuntimeConfig",
    "Session",
    "Tool",
    "ToolInvocation",
    "ToolKind",
    "ToolRegistry",
    "ToolResult",
]
