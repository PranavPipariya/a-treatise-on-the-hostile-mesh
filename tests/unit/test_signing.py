from eth_account import Account

from hostile_mesh_ens.signer import canonicalize, recover_signer, sign_payload


def test_sign_then_recover():
    acct = Account.create()
    payload = {"kind": "exploit", "match_id": "match-1", "endpoint": "GET /users/1"}
    signed = sign_payload(payload, acct.key.hex())
    assert recover_signer(signed.payload_canonical, signed.signature) == acct.address


def test_canonicalize_is_stable():
    a = canonicalize({"b": 1, "a": 2})
    b = canonicalize({"a": 2, "b": 1})
    assert a == b


def test_tampered_payload_recovers_different_address():
    acct = Account.create()
    signed = sign_payload({"x": 1}, acct.key.hex())
    tampered = signed.payload_canonical.replace('"x":1', '"x":2')
    assert recover_signer(tampered, signed.signature) != acct.address


def test_garbage_signature_returns_zero_address():
    bad = recover_signer('{"x":1}', "0x" + "ff" * 65)
    assert bad == "0x" + "0" * 40
