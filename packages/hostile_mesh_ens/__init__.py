"""ENS Sepolia integration for the Hostile Mesh.

Five concerns, one per module:

- ``wallet``     — per-agent eth-account wallets persisted as encrypted keystores.
- ``chain``      — web3.py connection to Sepolia, contract handles, nonce mgmt.
- ``signer``     — EIP-191 personal_sign + recover.
- ``resolver``   — text records on the ENS PublicResolver.
- ``subnames``   — subname creation via NameWrapper.setSubnodeRecord.
- ``archive``    — high-level: write a match's worth of signed events as
                    subnames + text records, read them back later.

The keys we write live under a configurable parent name
(``HOSTILE_MESH_ENS_PARENT``) so the demo can swap names without rebuilding.

Custom resolver text record namespace
-------------------------------------
``hm.axl.peer``            current per-match AXL peer ID
``hm.axl.epoch``           per-match epoch counter (rotates each match)
``hm.agent.role``          ``combatant`` | ``chorus``
``hm.agent.archetype``     chorus archetype
``hm.agent.capabilities``  JSON array of capability tags
``hm.match.id``            match this record belongs to
``hm.match.state``         ``pending`` | ``running`` | ``finished``
``hm.event.kind``          ``wound`` | ``patch`` | ``failed_claim`` | ``comment``
``hm.event.payload``       canonical JSON payload (signed)
``hm.event.signature``     EIP-191 signature over the payload
``hm.event.signer``        recovered signer address (sanity check)
``hm.event.verdict``       verifier verdict (only on event subnames)
``hm.reputation.score``    cumulative score
``hm.reputation.wins``     total wins
"""

from hostile_mesh_ens.archive import Archive, ArchiveWriteResult
from hostile_mesh_ens.chain import SepoliaChain, SepoliaContracts
from hostile_mesh_ens.config import EnsConfig
from hostile_mesh_ens.resolver import ResolverWriter
from hostile_mesh_ens.signer import SignedClaim, recover_signer, sign_payload
from hostile_mesh_ens.subnames import SubnameRegistrar
from hostile_mesh_ens.wallet import AgentWallet, WalletManager

__all__ = [
    "AgentWallet",
    "Archive",
    "ArchiveWriteResult",
    "EnsConfig",
    "ResolverWriter",
    "SepoliaChain",
    "SepoliaContracts",
    "SignedClaim",
    "SubnameRegistrar",
    "WalletManager",
    "recover_signer",
    "sign_payload",
]
