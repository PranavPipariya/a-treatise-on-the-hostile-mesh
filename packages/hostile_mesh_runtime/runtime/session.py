from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hostile_mesh_runtime.client.factory import LLMClient, make_client
from hostile_mesh_runtime.config import RuntimeConfig
from hostile_mesh_runtime.context.compressor import ContextCompressor
from hostile_mesh_runtime.context.conversation import ConversationManager
from hostile_mesh_runtime.context.loop_detector import LoopDetector
from hostile_mesh_runtime.hooks.lifecycle import HookSystem
from hostile_mesh_runtime.safety.permissions import PermissionManager
from hostile_mesh_runtime.tools.registry import ToolRegistry


@dataclass
class Session:
    """All long-lived state owned by a single agent process: client,
    conversation, tools, hooks, permissions, and compactor.

    Sessions are intentionally cheap to construct so the arena can spin up
    many of them in parallel — one per combatant, one per chorus member.
    """

    config: RuntimeConfig
    client: LLMClient
    conversation: ConversationManager
    tools: ToolRegistry
    hooks: HookSystem
    permissions: PermissionManager
    loop_detector: LoopDetector
    compressor: ContextCompressor
    workspace: Path
    turn: int = 0
    _closed: bool = field(default=False, init=False)

    @classmethod
    def create(
        cls,
        config: RuntimeConfig,
        tools: ToolRegistry,
        hooks: HookSystem | None = None,
    ) -> Session:
        client = make_client(config)
        return cls(
            config=config,
            client=client,
            conversation=ConversationManager(),
            tools=tools,
            hooks=hooks or HookSystem(),
            permissions=PermissionManager(auto_approve_kinds=config.auto_approve_kinds),
            loop_detector=LoopDetector(
                max_exact_repeats=config.loop_max_exact_repeats,
                max_cycle_length=config.loop_max_cycle_length,
            ),
            compressor=ContextCompressor(client),
            workspace=config.workspace,
        )

    def increment_turn(self) -> int:
        self.turn += 1
        return self.turn

    async def close(self) -> None:
        if self._closed:
            return
        await self.client.close()
        self._closed = True


__all__ = ["Session"]
