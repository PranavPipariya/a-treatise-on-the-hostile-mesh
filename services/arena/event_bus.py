from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArenaEventType(str, Enum):
    """Every event emitted by the arena to the UI / clients.

    Names are stable so the UI can switch on them. The shape inside ``data``
    is documented in ``docs/event-schema.md``.
    """

    MATCH_OPENING = "match.opening"
    MATCH_STARTED = "match.started"
    MATCH_FINISHED = "match.finished"
    MATCH_ABORTED = "match.aborted"

    NODE_SPAWNED = "axl.node.spawned"
    NODE_READY = "axl.node.ready"
    TOPOLOGY_UPDATED = "axl.topology"

    ENS_WRITE_SUBMITTED = "ens.write.submitted"
    ENS_WRITE_CONFIRMED = "ens.write.confirmed"
    ENS_WRITE_FAILED = "ens.write.failed"
    ENS_NOT_CONFIGURED = "ens.not_configured"

    BUG_SEEDED = "bug.seeded"
    AGENT_THOUGHT = "agent.thought"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"

    PROBE = "combat.probe"
    EXPLOIT_ATTEMPT = "combat.exploit.attempt"
    EXPLOIT_VERIFIED = "combat.exploit.verified"
    EXPLOIT_FAILED = "combat.exploit.failed"

    PATCH_SUBMITTED = "combat.patch.submitted"
    PATCH_APPLIED = "combat.patch.applied"
    PATCH_REJECTED = "combat.patch.rejected"
    PATCH_BROKE_SERVICE = "combat.patch.broke_service"

    CHORUS_COMMENT = "chorus.comment"
    COMBATANT_CLAIM = "combatant.claim"
    SCORE_UPDATED = "score.updated"

    PAYOUT = "combat.payout"
    PAYOUT_FAILED = "combat.payout.failed"

    LOG = "log"


@dataclass(slots=True)
class ArenaEvent:
    type: ArenaEventType
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    match_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "ts": self.ts,
            "match_id": self.match_id,
            "data": self.data,
        }


class ArenaEventBus:
    """Fan-out async event bus.

    Every subscriber gets its own queue + ring-buffered backlog so a slow
    SSE client doesn't block the arena loop. The backlog is intentionally
    small (last 256 events) — judges joining mid-match see context, but
    we don't pretend to be a durable log.
    """

    def __init__(self, backlog: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[ArenaEvent]] = set()
        self._backlog: deque[ArenaEvent] = deque(maxlen=backlog)
        self._lock = asyncio.Lock()

    @property
    def backlog(self) -> list[ArenaEvent]:
        return list(self._backlog)

    async def publish(self, event: ArenaEvent) -> None:
        async with self._lock:
            self._backlog.append(event)
            dead: list[asyncio.Queue[ArenaEvent]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)

    async def subscribe(self) -> AsyncIterator[ArenaEvent]:
        queue: asyncio.Queue[ArenaEvent] = asyncio.Queue(maxsize=512)
        async with self._lock:
            for event in self._backlog:
                queue.put_nowait(event)
            self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)


__all__ = ["ArenaEvent", "ArenaEventBus", "ArenaEventType"]
