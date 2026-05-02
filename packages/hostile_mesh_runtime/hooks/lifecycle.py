from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from hostile_mesh_runtime.tools.base import ToolResult

logger = logging.getLogger(__name__)


BeforeAgent = Callable[[str], Awaitable[None]]
AfterAgent = Callable[[str, str | None], Awaitable[None]]
BeforeTool = Callable[[str, dict[str, Any]], Awaitable[None]]
AfterTool = Callable[[str, dict[str, Any], ToolResult], Awaitable[None]]


@dataclass
class HookSystem:
    """Async lifecycle hooks used by the arena to forward agent events into
    its event bus and into AXL broadcast channels.
    """

    before_agent_hooks: list[BeforeAgent] = field(default_factory=list)
    after_agent_hooks: list[AfterAgent] = field(default_factory=list)
    before_tool_hooks: list[BeforeTool] = field(default_factory=list)
    after_tool_hooks: list[AfterTool] = field(default_factory=list)

    def on_before_agent(self, fn: BeforeAgent) -> None:
        self.before_agent_hooks.append(fn)

    def on_after_agent(self, fn: AfterAgent) -> None:
        self.after_agent_hooks.append(fn)

    def on_before_tool(self, fn: BeforeTool) -> None:
        self.before_tool_hooks.append(fn)

    def on_after_tool(self, fn: AfterTool) -> None:
        self.after_tool_hooks.append(fn)

    async def before_agent(self, message: str) -> None:
        for fn in self.before_agent_hooks:
            try:
                await fn(message)
            except Exception:
                logger.exception("before_agent hook failed")

    async def after_agent(self, message: str, response: str | None) -> None:
        for fn in self.after_agent_hooks:
            try:
                await fn(message, response)
            except Exception:
                logger.exception("after_agent hook failed")

    async def before_tool(self, name: str, params: dict[str, Any]) -> None:
        for fn in self.before_tool_hooks:
            try:
                await fn(name, params)
            except Exception:
                logger.exception("before_tool hook failed")

    async def after_tool(self, name: str, params: dict[str, Any], result: ToolResult) -> None:
        for fn in self.after_tool_hooks:
            try:
                await fn(name, params, result)
            except Exception:
                logger.exception("after_tool hook failed")


__all__ = ["HookSystem"]
