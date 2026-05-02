"""One-shot helper: register the static identity records under the configured
ENS parent for combatants, chorus members, and the chorus root.

Run once per fresh `HOSTILE_MESH_ENS_PARENT`. Subsequent matches re-write
per-match records on top of these foundations.

Usage:
    . .venv/bin/activate
    python scripts/register_ens.py
"""

from __future__ import annotations

import asyncio
import sys

from hostile_mesh_ens.archive import Archive
from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.config import EnsConfig
from hostile_mesh_ens.wallet import WalletManager

COMBATANTS = ("nightshade", "ironbark")
CHORUS = ("historian", "analyst", "loyalist", "skeptic", "chaos")


async def main() -> int:
    cfg = EnsConfig.from_env()
    if not cfg.chain_available:
        print(
            "✗ HOSTILE_MESH_REGISTRAR_PRIVKEY is not set — fill in .env first.",
            file=sys.stderr,
        )
        return 2

    chain = SepoliaChain(cfg)
    wallets = WalletManager(cfg.keystore_dir, cfg.keystore_passphrase or "demo-passphrase-please-change")
    archive = Archive(cfg, chain, wallets)

    print(f"Parent ENS: {cfg.parent_name}")
    print(f"Registrar:  {chain.registrar_address}")
    print()

    for combatant in COMBATANTS:
        print(f"→ register combatant {combatant}")
        result = await archive.register_agent(combatant, role="combatant")
        print(f"   {result.status}  tx={result.tx_hash}  err={result.error}")

    for archetype in CHORUS:
        agent = f"{archetype}.chorus"
        print(f"→ register chorus {agent}")
        result = await archive.register_agent(agent, role="chorus", archetype=archetype)
        print(f"   {result.status}  tx={result.tx_hash}  err={result.error}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
