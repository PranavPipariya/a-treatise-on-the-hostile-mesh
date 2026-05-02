from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ─── Sepolia ENS deployment (canonical addresses) ─────────────────────────────
# Source: https://docs.ens.domains/learn/deployments/  (ens.txt §Deployments)
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
SEPOLIA_PUBLIC_RESOLVER = "0x8FADE66B79cC9f707aB26799354482EB93a5B7dD"
SEPOLIA_NAME_WRAPPER = "0x0635513f179D50A207757E05759CbD106d7dFcE8"
SEPOLIA_REVERSE_REGISTRAR = "0xCF75B92126B02C9811d8c632144288a3eb84afC8"

DEFAULT_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
DEFAULT_PARENT = "hostilemesh.eth"


@dataclass(slots=True)
class EnsConfig:
    """Static config for the ENS Sepolia layer.

    All fields default from environment variables so any process spawned by
    the arena (combatant, chorus, target) inherits a coherent view of the
    chain without hand-passing config around.
    """

    rpc_url: str = DEFAULT_RPC
    chain_id: int = SEPOLIA_CHAIN_ID
    parent_name: str = DEFAULT_PARENT
    registrar_privkey: str = ""  # 0x… of the wallet that owns the parent
    keystore_dir: Path = field(default_factory=lambda: Path("./.keystore"))
    keystore_passphrase: str = ""

    registry_address: str = SEPOLIA_ENS_REGISTRY
    public_resolver_address: str = SEPOLIA_PUBLIC_RESOLVER
    name_wrapper_address: str = SEPOLIA_NAME_WRAPPER
    reverse_registrar_address: str = SEPOLIA_REVERSE_REGISTRAR

    request_timeout: float = 30.0
    confirmation_blocks: int = 1
    confirmation_timeout: float = 90.0

    @classmethod
    def from_env(cls) -> EnsConfig:
        return cls(
            rpc_url=os.getenv("HOSTILE_MESH_SEPOLIA_RPC", DEFAULT_RPC),
            chain_id=int(os.getenv("HOSTILE_MESH_SEPOLIA_CHAIN_ID", SEPOLIA_CHAIN_ID)),
            parent_name=os.getenv("HOSTILE_MESH_ENS_PARENT", DEFAULT_PARENT),
            registrar_privkey=os.getenv("HOSTILE_MESH_REGISTRAR_PRIVKEY", "").strip(),
            keystore_dir=Path(os.getenv("HOSTILE_MESH_KEYSTORE_DIR", "./.keystore")),
            keystore_passphrase=os.getenv("HOSTILE_MESH_KEYSTORE_PASSPHRASE", ""),
        )

    @property
    def chain_available(self) -> bool:
        """True if a registrar key was supplied — meaning we can actually
        write to the chain. When False, every chain-mutating op turns into
        a structured ``ArchiveWriteResult(status='not_configured')`` so the
        UI can render it as ``failed`` rather than fake confirmations."""
        return bool(self.registrar_privkey)


__all__ = [
    "DEFAULT_PARENT",
    "DEFAULT_RPC",
    "EnsConfig",
    "SEPOLIA_CHAIN_ID",
    "SEPOLIA_ENS_REGISTRY",
    "SEPOLIA_NAME_WRAPPER",
    "SEPOLIA_PUBLIC_RESOLVER",
    "SEPOLIA_REVERSE_REGISTRAR",
]
