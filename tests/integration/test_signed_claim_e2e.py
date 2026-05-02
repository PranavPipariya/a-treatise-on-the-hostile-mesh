"""End-to-end signed-claim verification round-trip without touching Sepolia.

Simulates what the arena does when a combatant's `exploit` tool fires:
the agent signs a canonical payload with its wallet, the verifier recovers
the signer, and a tampered payload is rejected.
"""

from __future__ import annotations

from eth_account import Account

from hostile_mesh_ens.signer import recover_signer, sign_payload


def test_round_trip():
    acct = Account.create()
    payload = {
        "kind": "exploit",
        "match_id": "match-007",
        "attacker": "nightshade",
        "defender": "ironbark",
        "vuln_class": "idor",
        "endpoint": "GET /invoices/10003",
        "summary": "non-owner read another user's invoice",
    }
    signed = sign_payload(payload, acct.key.hex())
    recovered = recover_signer(signed.payload_canonical, signed.signature)
    assert recovered == acct.address


def test_tampered_payload_rejected():
    acct = Account.create()
    signed = sign_payload({"k": "v"}, acct.key.hex())
    tampered = signed.payload_canonical.replace('"v"', '"w"')
    assert recover_signer(tampered, signed.signature) != acct.address


def test_resolver_records_present():
    acct = Account.create()
    signed = sign_payload({"k": "v"}, acct.key.hex())
    records = signed.to_resolver_records()
    assert "hm.event.payload" in records
    assert "hm.event.signature" in records
    assert "hm.event.signer" in records
    assert records["hm.event.signer"] == acct.address
