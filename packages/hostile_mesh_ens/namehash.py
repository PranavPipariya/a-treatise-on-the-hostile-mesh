"""Minimal namehash + labelhash implementation.

We use the ``ens.utils`` helpers when available, but reimplement them here
so the package never depends on the upstream ``ens`` PyPI version pinning
the same web3 release as us. Both functions are pure, well-defined, and
dead simple.

Reference: https://docs.ens.domains/contract-api-reference/name-processing
"""

from __future__ import annotations

from eth_utils import keccak


def namehash(name: str) -> bytes:
    """Compute the ENS namehash of ``name`` (e.g. ``hostilemesh.eth``)."""
    if not name:
        return b"\x00" * 32
    node = b"\x00" * 32
    labels = name.lower().split(".")
    for label in reversed(labels):
        if not label:
            continue
        node = keccak(node + keccak(text=label))
    return node


def labelhash(label: str) -> bytes:
    return keccak(text=label.lower())


def namehash_hex(name: str) -> str:
    return "0x" + namehash(name).hex()


def labelhash_hex(label: str) -> str:
    return "0x" + labelhash(label).hex()


__all__ = ["labelhash", "labelhash_hex", "namehash", "namehash_hex"]
