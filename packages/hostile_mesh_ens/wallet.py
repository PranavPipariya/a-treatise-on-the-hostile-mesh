from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentWallet:
    """An Ethereum wallet bound to one agent identity.

    Stored on disk as an encrypted Web3 keystore JSON (eth-account v3 encrypt).
    Loaded into memory only when needed for signing.
    """

    agent_id: str
    address: str
    private_key: str  # 0x-prefixed hex
    keystore_path: Path

    @property
    def checksummed(self) -> str:
        return Account.from_key(self.private_key).address


class WalletManager:
    """Generates and persists encrypted keystores for every Hostile Mesh agent.

    Idempotent: calling ``ensure(agent_id)`` either generates a fresh wallet
    and writes the encrypted keystore, or unlocks the existing one. The
    passphrase is supplied via ``HOSTILE_MESH_KEYSTORE_PASSPHRASE`` and is
    *required* to encrypt — refusing to fall back to plaintext keystores
    even in dev preserves the security story.
    """

    def __init__(self, keystore_dir: Path, passphrase: str) -> None:
        if not passphrase:
            raise ValueError(
                "HOSTILE_MESH_KEYSTORE_PASSPHRASE must be set — refusing to write "
                "plaintext keystores"
            )
        self._dir = keystore_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._passphrase = passphrase
        self._cache: dict[str, AgentWallet] = {}

    def keystore_path(self, agent_id: str) -> Path:
        return self._dir / f"{agent_id}.json"

    def ensure(self, agent_id: str) -> AgentWallet:
        if agent_id in self._cache:
            return self._cache[agent_id]

        path = self.keystore_path(agent_id)
        if path.is_file():
            wallet = self._load(agent_id, path)
        else:
            wallet = self._generate(agent_id, path)

        self._cache[agent_id] = wallet
        return wallet

    def _generate(self, agent_id: str, path: Path) -> AgentWallet:
        acct = Account.create()
        keystore = Account.encrypt(acct.key, self._passphrase)
        path.write_text(json.dumps(keystore))
        path.chmod(0o600)
        logger.info("generated wallet for %s at %s", agent_id, path)
        return AgentWallet(
            agent_id=agent_id,
            address=acct.address,
            private_key=acct.key.hex(),
            keystore_path=path,
        )

    def _load(self, agent_id: str, path: Path) -> AgentWallet:
        keystore = json.loads(path.read_text())
        privkey_bytes = Account.decrypt(keystore, self._passphrase)
        acct = Account.from_key(privkey_bytes)
        return AgentWallet(
            agent_id=agent_id,
            address=acct.address,
            private_key=acct.key.hex(),
            keystore_path=path,
        )

    def all(self) -> list[AgentWallet]:
        return list(self._cache.values())


__all__ = ["AgentWallet", "WalletManager"]
