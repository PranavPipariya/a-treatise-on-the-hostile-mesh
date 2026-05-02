from __future__ import annotations

import logging

from eth_utils import to_checksum_address

from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.namehash import namehash

logger = logging.getLogger(__name__)


# Default fuses: PARENT_CANNOT_CONTROL is OFF so the registrar can update the
# subname (rotate endpoints, append events). For long-lived archive entries
# we burn CANNOT_TRANSFER instead; for ephemeral records we burn nothing.
NO_FUSES = 0
FUSE_CANNOT_TRANSFER = 0x4

DEFAULT_TTL = 0
PERMANENT_EXPIRY = 0xFFFFFFFFFFFFFFFF  # max uint64


class SubnameRegistrar:
    """Wraps NameWrapper.setSubnodeRecord to mint subnames under our parent.

    Subname taxonomy used by Hostile Mesh:

      <agent>.<parent>                       — combatant / chorus identity
      match-N.<parent>                       — match container
      wound-K.match-N.<parent>               — verified wound event
      patch-K.match-N.<parent>               — applied patch event
      failed-K.match-N.<parent>              — publicly committed failed exploit
      comment-K.<chorus-role>.<parent>       — chorus commentary
      spectator-<id>.match-N.<parent>        — time-bounded spectator grant

    Every subname is created with the registrar wallet as owner, the
    PublicResolver wired up, and the resolver text records set in the same
    multicall when convenient.
    """

    def __init__(self, chain: SepoliaChain) -> None:
        self._chain = chain

    async def create(
        self,
        parent_name: str,
        label: str,
        *,
        owner: str | None = None,
        resolver: str | None = None,
        fuses: int = NO_FUSES,
        expiry: int = PERMANENT_EXPIRY,
        ttl: int = DEFAULT_TTL,
    ) -> str:
        """Create or update ``label.parent_name`` and return the tx hash.

        If the subname already exists, ``setSubnodeRecord`` re-registers it
        with the supplied parameters (idempotent for our use case).
        """
        parent_node = namehash(parent_name)
        owner_addr = to_checksum_address(owner or self._chain.registrar_address)
        resolver_addr = to_checksum_address(
            resolver or self._chain.config.public_resolver_address
        )
        call = self._chain.contracts.name_wrapper.functions.setSubnodeRecord(
            parent_node,
            label,
            owner_addr,
            resolver_addr,
            ttl,
            fuses,
            expiry,
        )
        return await self._chain.send_tx(call, gas=400_000)

    async def is_wrapped(self, parent_name: str) -> bool:
        node = namehash(parent_name)
        return await self._chain.call(
            self._chain.contracts.name_wrapper.functions.isWrapped(node)
        )

    async def owner_of(self, name: str) -> str:
        node = namehash(name)
        return await self._chain.call(
            self._chain.contracts.name_wrapper.functions.ownerOf(node)
        )


__all__ = [
    "DEFAULT_TTL",
    "FUSE_CANNOT_TRANSFER",
    "NO_FUSES",
    "PERMANENT_EXPIRY",
    "SubnameRegistrar",
]
