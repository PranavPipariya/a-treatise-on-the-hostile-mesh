from hostile_mesh_ens.namehash import labelhash_hex, namehash_hex


def test_namehash_empty_is_zero():
    assert namehash_hex("") == "0x" + "0" * 64


def test_namehash_eth_known_vector():
    # Reference: https://eips.ethereum.org/EIPS/eip-137
    assert (
        namehash_hex("eth")
        == "0x93cdeb708b7545dc668eb9280176169d1c33cfd8ed6f04690a0bcc88a93fc4ae"
    )


def test_namehash_subname_well_known():
    # foo.eth namehash from the EIP-137 test vector.
    assert (
        namehash_hex("foo.eth")
        == "0xde9b09fd7c5f901e23a3f19fecc54828e9c848539801e86591bd9801b019f84f"
    )


def test_labelhash_is_keccak_of_label():
    # eth's label hash is keccak("eth").
    h = labelhash_hex("eth")
    assert h.startswith("0x") and len(h) == 66
