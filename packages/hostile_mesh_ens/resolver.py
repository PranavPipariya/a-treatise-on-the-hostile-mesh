from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.namehash import namehash

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TextRecordWrite:
    name: str
    key: str
    tx_hash: str


class ResolverWriter:
    """Writes ENS PublicResolver text records.

    We use ``multicall`` so all of an event's records (payload + signature +
    signer + verdict) settle in a single transaction. This is dramatically
    cheaper and ensures the resolver state stays consistent — judges
    inspecting the chain never see "payload set but no signature" mid-write.
    """

    def __init__(self, chain: SepoliaChain) -> None:
        self._chain = chain

    async def get_text(self, name: str, key: str) -> str:
        node = namehash(name)
        return await self._chain.call(
            self._chain.contracts.public_resolver.functions.text(node, key)
        )

    async def set_text(self, name: str, key: str, value: str) -> str:
        node = namehash(name)
        call = self._chain.contracts.public_resolver.functions.setText(node, key, value)
        return await self._chain.send_tx(call, gas=120_000)

    async def set_many(self, name: str, records: dict[str, str]) -> str:
        """Atomically set multiple text records under one tx via multicall."""
        if not records:
            raise ValueError("records cannot be empty")
        node = namehash(name)
        resolver = self._chain.contracts.public_resolver
        encoded_calls: list[bytes] = []
        # web3.py renamed `encodeABI(fn_name=…)` → `encode_abi(abi_element_identifier=…)` in v7.
        # Support both for now so we don't pin a specific web3 version.
        for key, value in records.items():
            if hasattr(resolver, "encode_abi"):
                encoded_calls.append(
                    resolver.encode_abi(abi_element_identifier="setText", args=[node, key, value])
                )
            else:
                encoded_calls.append(
                    resolver.encodeABI(fn_name="setText", args=[node, key, value])
                )
        call = resolver.functions.multicall(encoded_calls)
        gas = 120_000 + 80_000 * len(records)
        return await self._chain.send_tx(call, gas=gas)

    async def read_records(self, name: str, keys: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in keys:
            try:
                out[key] = await self.get_text(name, key)
            except Exception as exc:  # tolerate per-key read failures
                logger.warning("text(%s, %s) read failed: %s", name, key, exc)
                out[key] = ""
        return out

    async def resolve_addr(self, name: str) -> str | None:
        """Forward-resolve an ENS name to a checksummed Ethereum address.

        Path: registry.resolver(node) -> PublicResolver.addr(node). If neither
        is set, fall back to reading the `hm.agent.address` text record on the
        public resolver — the arena writes that key when minting agent
        subnames, so it's always populated even when the canonical addr record
        isn't.
        """
        from eth_utils import to_checksum_address

        node = namehash(name)
        zero = "0x" + "0" * 40
        try:
            resolver_addr = await self._chain.call(
                self._chain.contracts.registry.functions.resolver(node)
            )
        except Exception as exc:
            logger.warning("registry.resolver(%s) failed: %s", name, exc)
            resolver_addr = zero
        if resolver_addr and resolver_addr.lower() != zero:
            try:
                resolver_contract = self._chain.web3.eth.contract(
                    address=to_checksum_address(resolver_addr),
                    abi=self._chain.contracts.public_resolver.abi,
                )
                addr = await self._chain.call(
                    resolver_contract.functions.addr(node)
                )
                if addr and addr.lower() != zero:
                    return to_checksum_address(addr)
            except Exception as exc:
                logger.warning("resolver.addr(%s) failed: %s", name, exc)
        try:
            text_addr = (await self.get_text(name, "hm.agent.address")).strip()
        except Exception as exc:
            logger.warning("fallback text(%s, hm.agent.address) failed: %s", name, exc)
            return None
        if not text_addr or text_addr.lower() == zero:
            return None
        try:
            return to_checksum_address(text_addr)
        except Exception:
            return None


__all__ = ["ResolverWriter", "TextRecordWrite"]
