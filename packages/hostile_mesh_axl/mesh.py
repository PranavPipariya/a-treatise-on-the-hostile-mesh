from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from hostile_mesh_axl.client import AxlClient, AxlError
from hostile_mesh_axl.supervisor import AxlNodeProcess

logger = logging.getLogger(__name__)


# ─── Channels ────────────────────────────────────────────────────────────────
# AXL has no native pub/sub. We model two logical channels with envelope
# routing, both backed by per-peer fan-out via /send.
CHANNEL_ARENA = "arena"  # combatants ↔ arena (control plane)
CHANNEL_CHORUS = "chorus"  # arena → all chorus members (broadcast)
CHANNEL_DUEL = "duel"  # combatant ↔ combatant (taunts, claims)


@dataclass(slots=True)
class CombatEnvelope:
    """Wire envelope for every Hostile Mesh AXL message.

    JSON-encoded; the AXL node forwards the raw bytes verbatim. ``id`` lets
    the receiver dedupe replays; ``ts`` lets the UI render lag honestly.
    """

    id: str
    channel: str  # CHANNEL_*
    kind: str  # "match.start", "wound", "patch", "claim", "comment", "topology", ...
    sender: str  # agent_id of the originating node
    sender_ens: str = ""
    sender_peer_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> CombatEnvelope:
        data = json.loads(raw.decode("utf-8"))
        return cls(**data)

    @classmethod
    def new(
        cls,
        channel: str,
        kind: str,
        sender: str,
        payload: dict[str, Any],
        *,
        sender_ens: str = "",
        sender_peer_id: str = "",
    ) -> CombatEnvelope:
        return cls(
            id=uuid.uuid4().hex,
            channel=channel,
            kind=kind,
            sender=sender,
            sender_ens=sender_ens,
            sender_peer_id=sender_peer_id,
            payload=payload,
        )


EnvelopeHandler = Callable[[CombatEnvelope, "MeshNode"], Awaitable[None]]


@dataclass
class MeshNode:
    """One agent's view of the mesh: an AXL process + its async client +
    a long-poll receive task that fans envelopes into a queue.
    """

    agent_id: str
    process: AxlNodeProcess
    client: AxlClient
    inbox: asyncio.Queue[CombatEnvelope] = field(default_factory=asyncio.Queue)
    _recv_task: asyncio.Task[None] | None = None
    _seen_ids: set[str] = field(default_factory=set)

    @property
    def peer_id(self) -> str:
        return self.process.peer_id

    @property
    def api_url(self) -> str:
        return self.process.api_url

    async def start_recv_loop(self, poll_interval: float = 0.25) -> None:
        if self._recv_task:
            return
        self._recv_task = asyncio.create_task(self._recv_loop(poll_interval))

    async def stop(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseException):
                await self._recv_task
            self._recv_task = None
        await self.client.close()

    async def _recv_loop(self, poll_interval: float) -> None:
        backoff = poll_interval
        while True:
            try:
                received = await self.client.recv()
            except AxlError as exc:
                logger.warning("recv loop %s: %s", self.agent_id, exc)
                await asyncio.sleep(min(backoff * 2, 2.0))
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("recv loop %s crashed", self.agent_id)
                await asyncio.sleep(0.5)
                continue

            if received is None:
                await asyncio.sleep(poll_interval)
                continue

            _from_peer, raw = received
            try:
                envelope = CombatEnvelope.from_bytes(raw)
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("recv loop %s: malformed envelope: %s", self.agent_id, exc)
                continue

            if envelope.id in self._seen_ids:
                continue
            self._seen_ids.add(envelope.id)
            if len(self._seen_ids) > 4096:
                self._seen_ids = set(list(self._seen_ids)[-2048:])

            await self.inbox.put(envelope)

    async def iter_envelopes(self) -> AsyncIterator[CombatEnvelope]:
        while True:
            yield await self.inbox.get()


class Mesh:
    """High-level peer-to-peer mesh wrapping a set of AxlNodeProcesses.

    Operations:
      - ``send(sender, recipient, envelope)`` — direct unicast.
      - ``broadcast(sender, channel, envelope)`` — fan out to all members of a channel.
      - ``subscribe(agent_id)`` — read envelopes addressed to this node.

    Membership of channels is configured up-front via ``set_channel_members``.
    """

    def __init__(self, nodes: dict[str, MeshNode]) -> None:
        self._nodes = nodes
        self._channels: dict[str, set[str]] = {
            CHANNEL_ARENA: set(),
            CHANNEL_CHORUS: set(),
            CHANNEL_DUEL: set(),
        }
        self._handlers: list[EnvelopeHandler] = []

    @classmethod
    def from_processes(cls, processes: dict[str, AxlNodeProcess]) -> Mesh:
        nodes = {
            agent_id: MeshNode(
                agent_id=agent_id,
                process=proc,
                client=AxlClient(proc.api_url),
            )
            for agent_id, proc in processes.items()
        }
        return cls(nodes)

    @property
    def nodes(self) -> dict[str, MeshNode]:
        return self._nodes

    def set_channel_members(self, channel: str, agent_ids: list[str]) -> None:
        self._channels.setdefault(channel, set())
        self._channels[channel] = set(agent_ids)

    def register_handler(self, handler: EnvelopeHandler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        for node in self._nodes.values():
            await node.start_recv_loop()
            asyncio.create_task(self._fanout_to_handlers(node))

    async def stop(self) -> None:
        for node in self._nodes.values():
            await node.stop()

    async def send(
        self, sender_id: str, recipient_id: str, envelope: CombatEnvelope
    ) -> dict[str, Any]:
        sender = self._nodes.get(sender_id)
        recipient = self._nodes.get(recipient_id)
        if sender is None or recipient is None:
            raise ValueError(f"unknown agent in send: {sender_id} → {recipient_id}")
        if not recipient.peer_id:
            raise RuntimeError(
                f"recipient {recipient_id!r} has no peer_id yet — supervisor "
                f"did not finish bootstrapping"
            )
        return await sender.client.send(recipient.peer_id, envelope.to_bytes())

    async def broadcast(
        self, sender_id: str, channel: str, envelope: CombatEnvelope
    ) -> list[dict[str, Any]]:
        members = self._channels.get(channel, set())
        receipts: list[dict[str, Any]] = []
        for agent_id in members:
            if agent_id == sender_id:
                continue
            try:
                receipt = await self.send(sender_id, agent_id, envelope)
                receipts.append({"to": agent_id, "ok": True, **receipt})
            except (ValueError, RuntimeError, AxlError) as exc:
                receipts.append({"to": agent_id, "ok": False, "error": str(exc)})
        return receipts

    async def _fanout_to_handlers(self, node: MeshNode) -> None:
        async for envelope in node.iter_envelopes():
            for handler in self._handlers:
                try:
                    await handler(envelope, node)
                except Exception:
                    logger.exception("handler raised on envelope %s", envelope.id)


__all__ = [
    "CHANNEL_ARENA",
    "CHANNEL_CHORUS",
    "CHANNEL_DUEL",
    "CombatEnvelope",
    "EnvelopeHandler",
    "Mesh",
    "MeshNode",
]
