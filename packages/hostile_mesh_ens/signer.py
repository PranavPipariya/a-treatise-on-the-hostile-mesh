from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address


@dataclass(slots=True)
class SignedClaim:
    """A canonical JSON payload + EIP-191 personal_sign signature.

    Combatants produce these for every public claim (wound / patch /
    comment); the verifier resolves the claimant's ENS name to an
    expected address and rejects any claim whose signature doesn't
    recover to that address.
    """

    payload: dict[str, Any]
    payload_canonical: str  # canonical JSON used for signing
    signature: str  # 0x-prefixed hex
    signer: str  # checksummed address recovered locally for sanity

    def to_resolver_records(self) -> dict[str, str]:
        return {
            "hm.event.payload": self.payload_canonical,
            "hm.event.signature": self.signature,
            "hm.event.signer": self.signer,
        }


def canonicalize(payload: dict[str, Any]) -> str:
    """Stable JSON encoding used as the signed message."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_payload(payload: dict[str, Any], private_key: str) -> SignedClaim:
    canonical = canonicalize(payload)
    msg = encode_defunct(text=canonical)
    signed = Account.sign_message(msg, private_key=private_key)
    signer = to_checksum_address(Account.recover_message(msg, signature=signed.signature))
    return SignedClaim(
        payload=payload,
        payload_canonical=canonical,
        signature=signed.signature.hex()
        if isinstance(signed.signature, bytes)
        else str(signed.signature),
        signer=signer,
    )


def recover_signer(payload_canonical: str, signature: str) -> str:
    """Recover the checksummed address that produced ``signature`` over
    ``payload_canonical``. Returns ``"0x000…"`` (zero address) on malformed
    input rather than raising — verifiers compare against an expected address
    and treat a mismatch as a failed verification regardless."""
    try:
        msg = encode_defunct(text=payload_canonical)
        return to_checksum_address(Account.recover_message(msg, signature=signature))
    except Exception:
        return "0x" + "0" * 40


__all__ = ["SignedClaim", "canonicalize", "recover_signer", "sign_payload"]
