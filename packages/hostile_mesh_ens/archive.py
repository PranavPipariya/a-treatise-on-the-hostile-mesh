from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.config import EnsConfig
from hostile_mesh_ens.resolver import ResolverWriter
from hostile_mesh_ens.signer import SignedClaim, recover_signer
from hostile_mesh_ens.subnames import SubnameRegistrar
from hostile_mesh_ens.wallet import WalletManager

logger = logging.getLogger(__name__)


# Resolver record keys (kept as constants so callers don't typo).
KEY_AXL_PEER = "hm.axl.peer"
KEY_AXL_EPOCH = "hm.axl.epoch"
KEY_AGENT_ROLE = "hm.agent.role"
KEY_AGENT_ARCHETYPE = "hm.agent.archetype"
KEY_AGENT_CAPS = "hm.agent.capabilities"
KEY_AGENT_ADDRESS = "hm.agent.address"
KEY_MATCH_ID = "hm.match.id"
KEY_MATCH_STATE = "hm.match.state"
KEY_EVENT_KIND = "hm.event.kind"
KEY_EVENT_PAYLOAD = "hm.event.payload"
KEY_EVENT_SIGNATURE = "hm.event.signature"
KEY_EVENT_SIGNER = "hm.event.signer"
KEY_EVENT_VERDICT = "hm.event.verdict"
KEY_REPUTATION_SCORE = "hm.reputation.score"
KEY_REPUTATION_WINS = "hm.reputation.wins"


@dataclass(slots=True)
class ArchiveWriteResult:
    """Status object surfaced into the UI event stream so judges can see
    real chain progress without us ever pretending a write confirmed."""

    status: str  # "submitted" | "confirmed" | "failed" | "not_configured"
    name: str
    operation: str  # e.g. "subname.create" | "resolver.set_many"
    tx_hash: str | None = None
    block_number: int | None = None
    error: str | None = None
    elapsed_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class Archive:
    """High-level orchestration over wallet, resolver, and subname layers.

    Methods correspond 1:1 with combat events the arena emits. Each method
    returns an :class:`ArchiveWriteResult` whose ``status`` faithfully
    reflects what the chain accepted — never optimistically reported.
    """

    def __init__(
        self,
        config: EnsConfig,
        chain: SepoliaChain,
        wallets: WalletManager,
    ) -> None:
        self._config = config
        self._chain = chain
        self._wallets = wallets
        self.resolver = ResolverWriter(chain)
        self.subnames = SubnameRegistrar(chain)

    @property
    def parent(self) -> str:
        return self._config.parent_name

    def name_for_agent(self, agent_id: str) -> str:
        return f"{agent_id}.{self.parent}"

    def name_for_match(self, match_id: str) -> str:
        return f"{match_id}.{self.parent}"

    def name_for_event(self, match_id: str, kind: str, index: int) -> str:
        return f"{kind}-{index}.{match_id}.{self.parent}"

    def name_for_chorus_comment(self, archetype: str, index: int) -> str:
        return f"comment-{index}.{archetype}.chorus.{self.parent}"

    def name_for_spectator(self, match_id: str, grant_id: str) -> str:
        return f"spectator-{grant_id}.{match_id}.{self.parent}"

    # ─── lifecycle ────────────────────────────────────────────────────────
    async def register_agent(
        self,
        agent_id: str,
        *,
        role: str,
        archetype: str = "",
        capabilities: list[str] | None = None,
        peer_id: str = "",
        epoch: int = 0,
    ) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult("not_configured", self.name_for_agent(agent_id), "register_agent")

        wallet = self._wallets.ensure(agent_id)
        agent_name = self.name_for_agent(agent_id)

        # 1) Mint or refresh subnames along the dotted path. ENS labels can't
        # contain dots, so an agent_id like "historian.chorus" needs:
        #     chorus.<parent>           (intermediate)
        #     historian.chorus.<parent> (leaf)
        # Each subname is owned by the registrar so the resolver accepts our
        # setText calls (only the owner can write text records).
        path = agent_id.split(".")
        # Build [..., chorus.parent, parent] — outermost first.
        carrier = self.parent
        for label in reversed(path[1:]):
            sub = await self._safe_subname_create(carrier, label)
            if sub.status == "failed":
                return sub
            carrier = f"{label}.{carrier}"
        leaf_label = path[0]
        subname_tx = await self._safe_subname_create(carrier, leaf_label)
        if subname_tx.status == "failed":
            return subname_tx

        # 2) Set resolver records — agent identity + AXL pointer + signing addr.
        records = {
            KEY_AGENT_ADDRESS: wallet.address,
            KEY_AGENT_ROLE: role,
            KEY_AGENT_ARCHETYPE: archetype,
            KEY_AGENT_CAPS: ",".join(capabilities or []),
            KEY_AXL_PEER: peer_id,
            KEY_AXL_EPOCH: str(epoch),
        }
        return await self._safe_set_many(agent_name, records, op="register_agent")

    async def open_match(self, match_id: str, combatants: list[str]) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult("not_configured", self.name_for_match(match_id), "open_match")

        sub = await self._safe_subname_create(self.parent, match_id)
        if sub.status == "failed":
            return sub
        match_name = self.name_for_match(match_id)
        records = {
            KEY_MATCH_ID: match_id,
            KEY_MATCH_STATE: "running",
            KEY_AGENT_CAPS: ",".join(combatants),
        }
        return await self._safe_set_many(match_name, records, op="open_match")

    async def close_match(self, match_id: str, scores: dict[str, int]) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult("not_configured", self.name_for_match(match_id), "close_match")
        match_name = self.name_for_match(match_id)
        records = {
            KEY_MATCH_STATE: "finished",
            "hm.match.scores": ",".join(f"{k}={v}" for k, v in scores.items()),
        }
        return await self._safe_set_many(match_name, records, op="close_match")

    async def rotate_axl_endpoint(
        self, agent_id: str, *, peer_id: str, epoch: int
    ) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult(
                "not_configured", self.name_for_agent(agent_id), "rotate_axl_endpoint"
            )
        return await self._safe_set_many(
            self.name_for_agent(agent_id),
            {KEY_AXL_PEER: peer_id, KEY_AXL_EPOCH: str(epoch)},
            op="rotate_axl_endpoint",
        )

    # ─── event archive ───────────────────────────────────────────────────
    async def record_event(
        self,
        *,
        match_id: str,
        kind: str,  # wound | patch | failed_claim | comment
        index: int,
        signed: SignedClaim,
        verdict: str,
    ) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult(
                "not_configured", self.name_for_event(match_id, kind, index), "record_event"
            )

        event_name = self.name_for_event(match_id, kind, index)
        sub = await self._safe_subname_create(f"{match_id}.{self.parent}", f"{kind}-{index}")
        if sub.status == "failed":
            return sub

        records = {
            KEY_EVENT_KIND: kind,
            KEY_EVENT_VERDICT: verdict,
            **signed.to_resolver_records(),
        }
        return await self._safe_set_many(event_name, records, op="record_event")

    async def record_chorus_comment(
        self,
        *,
        archetype: str,
        index: int,
        signed: SignedClaim,
    ) -> ArchiveWriteResult:
        if not self._config.chain_available:
            return ArchiveWriteResult(
                "not_configured",
                self.name_for_chorus_comment(archetype, index),
                "record_chorus_comment",
            )

        # Two-level subname: chorus.<parent> first, then comment-K.<archetype>...
        await self._safe_subname_create(self.parent, "chorus")
        await self._safe_subname_create(f"chorus.{self.parent}", archetype)
        await self._safe_subname_create(f"{archetype}.chorus.{self.parent}", f"comment-{index}")

        return await self._safe_set_many(
            self.name_for_chorus_comment(archetype, index),
            {KEY_EVENT_KIND: "comment", **signed.to_resolver_records()},
            op="record_chorus_comment",
        )

    async def grant_spectator(
        self, match_id: str, grant_id: str, expiry_unix: int
    ) -> ArchiveWriteResult:
        """ENS-Most-Creative angle #2: subnames as scoped spectator access tokens.

        Time-bounded subname under the match. Resolver records hold the
        broadcast channel ID and the grant's expiry. The subname itself can
        be owned by an arbitrary spectator address so off-chain readers can
        prove access by signing with that key.
        """
        if not self._config.chain_available:
            return ArchiveWriteResult(
                "not_configured",
                self.name_for_spectator(match_id, grant_id),
                "grant_spectator",
            )

        sub = await self._safe_subname_create(
            f"{match_id}.{self.parent}",
            f"spectator-{grant_id}",
            expiry=expiry_unix,
        )
        if sub.status == "failed":
            return sub

        return await self._safe_set_many(
            self.name_for_spectator(match_id, grant_id),
            {
                "hm.spectator.channel": "chorus",
                "hm.spectator.expiry": str(expiry_unix),
            },
            op="grant_spectator",
        )

    # ─── reads ───────────────────────────────────────────────────────────
    async def read_agent(self, agent_id: str) -> dict[str, str]:
        return await self.resolver.read_records(
            self.name_for_agent(agent_id),
            [
                KEY_AGENT_ROLE,
                KEY_AGENT_ARCHETYPE,
                KEY_AGENT_CAPS,
                KEY_AXL_PEER,
                KEY_AXL_EPOCH,
                KEY_REPUTATION_SCORE,
                KEY_REPUTATION_WINS,
            ],
        )

    async def verify_event_signature(
        self,
        event_name: str,
        expected_signer: str,
    ) -> bool:
        records = await self.resolver.read_records(
            event_name, [KEY_EVENT_PAYLOAD, KEY_EVENT_SIGNATURE]
        )
        payload = records.get(KEY_EVENT_PAYLOAD, "")
        sig = records.get(KEY_EVENT_SIGNATURE, "")
        if not payload or not sig:
            return False
        recovered = recover_signer(payload, sig)
        return recovered.lower() == expected_signer.lower()

    # ─── plumbing ────────────────────────────────────────────────────────
    async def _safe_subname_create(
        self, parent: str, label: str, **kwargs: Any
    ) -> ArchiveWriteResult:
        name = f"{label}.{parent}"
        start = time.monotonic()
        try:
            tx = await self.subnames.create(parent, label, **kwargs)
        except Exception as exc:
            logger.exception("subname.create %s failed", name)
            return ArchiveWriteResult(
                "failed", name, "subname.create", error=str(exc),
                elapsed_s=time.monotonic() - start,
            )
        return await self._await_confirmation(name, "subname.create", tx, start)

    async def _safe_set_many(
        self, name: str, records: dict[str, str], *, op: str
    ) -> ArchiveWriteResult:
        start = time.monotonic()
        try:
            tx = await self.resolver.set_many(name, records)
        except Exception as exc:
            logger.exception("resolver.set_many %s failed", name)
            return ArchiveWriteResult(
                "failed", name, op, error=str(exc), elapsed_s=time.monotonic() - start
            )
        result = await self._await_confirmation(name, op, tx, start)
        result.metadata["records"] = list(records.keys())
        return result

    async def _await_confirmation(
        self, name: str, op: str, tx_hash: str, start: float
    ) -> ArchiveWriteResult:
        try:
            receipt = await asyncio.wait_for(
                self._chain.wait_for_receipt(tx_hash),
                timeout=self._config.confirmation_timeout,
            )
        except asyncio.TimeoutError:
            return ArchiveWriteResult(
                "submitted",
                name,
                op,
                tx_hash=tx_hash,
                error="confirmation timeout",
                elapsed_s=time.monotonic() - start,
            )
        elapsed = time.monotonic() - start
        if receipt is None:
            return ArchiveWriteResult(
                "submitted", name, op, tx_hash=tx_hash, elapsed_s=elapsed
            )
        if receipt["status"] == 0:
            return ArchiveWriteResult(
                "failed", name, op, tx_hash=tx_hash,
                error="reverted", elapsed_s=elapsed,
            )
        return ArchiveWriteResult(
            "confirmed", name, op,
            tx_hash=tx_hash,
            block_number=receipt["blockNumber"],
            elapsed_s=elapsed,
        )


__all__ = [
    "Archive",
    "ArchiveWriteResult",
    "KEY_AGENT_ARCHETYPE",
    "KEY_AGENT_ADDRESS",
    "KEY_AGENT_CAPS",
    "KEY_AGENT_ROLE",
    "KEY_AXL_EPOCH",
    "KEY_AXL_PEER",
    "KEY_EVENT_KIND",
    "KEY_EVENT_PAYLOAD",
    "KEY_EVENT_SIGNATURE",
    "KEY_EVENT_SIGNER",
    "KEY_EVENT_VERDICT",
    "KEY_MATCH_ID",
    "KEY_MATCH_STATE",
    "KEY_REPUTATION_SCORE",
    "KEY_REPUTATION_WINS",
]
