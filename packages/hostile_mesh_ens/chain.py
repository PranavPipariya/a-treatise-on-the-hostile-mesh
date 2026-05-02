from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from eth_account import Account
from eth_utils import to_checksum_address
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TransactionNotFound
from web3.types import TxReceipt

from hostile_mesh_ens.abis import (
    ENS_REGISTRY_ABI,
    NAME_WRAPPER_ABI,
    PUBLIC_RESOLVER_ABI,
)
from hostile_mesh_ens.config import EnsConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SepoliaContracts:
    registry: Contract
    public_resolver: Contract
    name_wrapper: Contract


class SepoliaChain:
    """Single point of contact with Sepolia.

    Owns the registrar wallet (the EOA that pays gas to write subnames /
    text records under our parent name), wraps web3.py contract handles,
    and serializes nonce assignment behind a mutex so concurrent writes
    from the arena don't collide.
    """

    def __init__(self, config: EnsConfig) -> None:
        self._config = config
        self._w3: Web3 | None = None
        self._contracts: SepoliaContracts | None = None
        self._registrar_addr: str = ""
        self._nonce_lock = threading.Lock()
        self._next_nonce: int | None = None

    @property
    def config(self) -> EnsConfig:
        return self._config

    @property
    def web3(self) -> Web3:
        if self._w3 is None:
            self._w3 = Web3(
                Web3.HTTPProvider(
                    self._config.rpc_url,
                    request_kwargs={"timeout": self._config.request_timeout},
                )
            )
            if not self._w3.is_connected():
                raise RuntimeError(f"Sepolia RPC unreachable: {self._config.rpc_url}")
        return self._w3

    @property
    def contracts(self) -> SepoliaContracts:
        if self._contracts is None:
            w3 = self.web3
            self._contracts = SepoliaContracts(
                registry=w3.eth.contract(
                    address=to_checksum_address(self._config.registry_address),
                    abi=ENS_REGISTRY_ABI,
                ),
                public_resolver=w3.eth.contract(
                    address=to_checksum_address(self._config.public_resolver_address),
                    abi=PUBLIC_RESOLVER_ABI,
                ),
                name_wrapper=w3.eth.contract(
                    address=to_checksum_address(self._config.name_wrapper_address),
                    abi=NAME_WRAPPER_ABI,
                ),
            )
        return self._contracts

    @property
    def registrar_address(self) -> str:
        if not self._registrar_addr:
            if not self._config.registrar_privkey:
                raise RuntimeError(
                    "HOSTILE_MESH_REGISTRAR_PRIVKEY is empty — chain writes disabled"
                )
            self._registrar_addr = Account.from_key(
                self._config.registrar_privkey
            ).address
        return self._registrar_addr

    def _allocate_nonce(self) -> int:
        with self._nonce_lock:
            if self._next_nonce is None:
                self._next_nonce = self.web3.eth.get_transaction_count(
                    self.registrar_address, "pending"
                )
            n = self._next_nonce
            self._next_nonce += 1
            return n

    def _build_tx_kwargs(self, *, gas: int = 250_000) -> dict[str, Any]:
        gas_price = self.web3.eth.gas_price
        return {
            "chainId": self._config.chain_id,
            "from": self.registrar_address,
            "nonce": self._allocate_nonce(),
            "gas": gas,
            "maxFeePerGas": int(gas_price * 2),
            "maxPriorityFeePerGas": int(gas_price),
        }

    def _send_signed(self, tx: dict[str, Any]) -> str:
        signed = self.web3.eth.account.sign_transaction(
            tx, private_key=self._config.registrar_privkey
        )
        # web3 v6 → rawTransaction; v7 → raw_transaction
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        tx_hash = self.web3.eth.send_raw_transaction(raw)
        return tx_hash.hex()

    async def send_tx(
        self, contract_call: Any, *, gas: int = 250_000
    ) -> str:
        """Build, sign, and submit a transaction in a worker thread.

        ``contract_call`` is the bound contract function with arguments
        already supplied (e.g. ``contract.functions.setText(node, key, value)``).
        Returns the tx hash. Caller is responsible for awaiting confirmation
        if needed via :meth:`wait_for_receipt`.
        """

        def _send() -> str:
            tx = contract_call.build_transaction(self._build_tx_kwargs(gas=gas))
            return self._send_signed(tx)

        return await asyncio.to_thread(_send)

    async def send_eth(self, to_address: str, wei: int) -> str:
        """Send a plain ETH transfer from the registrar to `to_address`.

        Uses the same nonce-allocation path as send_tx so concurrent payouts
        don't collide. Returns the tx hash hex immediately — does not wait
        for receipt. Caller can `wait_for_receipt(tx_hash)` if confirmation
        is needed.
        """
        if wei <= 0:
            raise ValueError(f"refusing to send zero/negative wei: {wei}")
        recipient = to_checksum_address(to_address)

        def _send() -> str:
            kwargs = self._build_tx_kwargs(gas=21_000)
            kwargs["to"] = recipient
            kwargs["value"] = int(wei)
            kwargs["type"] = 2  # EIP-1559
            return self._send_signed(kwargs)

        return await asyncio.to_thread(_send)

    async def wait_for_receipt(self, tx_hash: str) -> TxReceipt | None:
        def _wait() -> TxReceipt | None:
            try:
                return self.web3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self._config.confirmation_timeout
                )
            except TransactionNotFound:
                return None

        return await asyncio.to_thread(_wait)

    async def call(self, contract_call: Any) -> Any:
        return await asyncio.to_thread(contract_call.call)


__all__ = ["SepoliaChain", "SepoliaContracts"]
