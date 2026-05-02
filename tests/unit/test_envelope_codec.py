from hostile_mesh_axl.mesh import CHANNEL_DUEL, CombatEnvelope


def test_envelope_roundtrip():
    e = CombatEnvelope.new(
        channel=CHANNEL_DUEL,
        kind="exploit_outcome",
        sender="nightshade",
        sender_ens="nightshade.hostilemesh.eth",
        payload={"verdict": {"success": True}},
    )
    raw = e.to_bytes()
    decoded = CombatEnvelope.from_bytes(raw)
    assert decoded.id == e.id
    assert decoded.kind == "exploit_outcome"
    assert decoded.payload["verdict"]["success"] is True


def test_envelope_is_canonical_json():
    e = CombatEnvelope.new(
        channel="x",
        kind="x",
        sender="x",
        payload={"b": 1, "a": 2},  # intentionally out of order
    )
    raw = e.to_bytes().decode()
    # sort_keys ensures stable bytes regardless of input order — important for
    # signature verification on the receiving side.
    assert raw.find('"a"') < raw.find('"b"')


def test_envelope_unique_ids():
    a = CombatEnvelope.new("x", "x", "x", {})
    b = CombatEnvelope.new("x", "x", "x", {})
    assert a.id != b.id
