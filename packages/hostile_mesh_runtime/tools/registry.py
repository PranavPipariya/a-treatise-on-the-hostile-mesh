from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hostile_mesh_runtime.hooks.lifecycle import HookSystem
from hostile_mesh_runtime.safety.permissions import (
    ApprovalContext,
    ApprovalDecision,
    PermissionManager,
)
from hostile_mesh_runtime.tools.base import Tool, ToolInvocation, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Typed tool registry. Validates Pydantic schemas, applies approval
    policies, threads lifecycle hooks, and surfaces structured ``ToolResult``s
    to the orchestrator regardless of whether a tool succeeded, failed
    validation, or was rejected by the permission engine.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            logger.warning("overwriting tool %s", tool.name)
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self, allowed: tuple[str, ...] | None = None) -> list[Tool]:
        if allowed is None:
            return list(self._tools.values())
        wanted = set(allowed)
        return [t for t in self._tools.values() if t.name in wanted]

    def schemas(self, allowed: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        return [t.to_anthropic_schema() for t in self.all(allowed)]

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        *,
        agent_id: str,
        cwd: Path,
        hooks: HookSystem,
        permissions: PermissionManager | None = None,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            result = ToolResult.fail(f"unknown tool: {name}", metadata={"tool_name": name})
            await hooks.after_tool(name, params, result)
            return result

        parsed, errs = tool.validate(params)
        if parsed is None:
            result = ToolResult.fail(
                f"invalid parameters: {'; '.join(errs)}",
                metadata={"tool_name": name, "validation_errors": errs},
            )
            await hooks.after_tool(name, params, result)
            return result

        await hooks.before_tool(name, params)
        invocation = ToolInvocation(params=params, cwd=cwd, agent_id=agent_id)

        if permissions is not None and tool.is_mutating:
            confirmation = await tool.confirmation(invocation)
            ctx = ApprovalContext(
                tool_name=name,
                kind=tool.kind,
                params=params,
                affected_paths=confirmation.affected_paths if confirmation else [],
                command=confirmation.command if confirmation else None,
                is_dangerous=confirmation.is_dangerous if confirmation else False,
            )
            decision = permissions.decide(ctx)
            if decision is ApprovalDecision.REJECTED:
                result = ToolResult.fail("rejected by permission engine")
                await hooks.after_tool(name, params, result)
                return result

        try:
            result = await tool.execute(invocation, parsed)
        except Exception as exc:  # surface as structured tool error
            logger.exception("tool %s raised", name)
            result = ToolResult.fail(f"internal error: {exc}", metadata={"tool_name": name})

        await hooks.after_tool(name, params, result)
        return result


__all__ = ["ToolRegistry"]
