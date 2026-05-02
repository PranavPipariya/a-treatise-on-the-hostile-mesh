"""Minimal ABI fragments for the ENS contracts we touch on Sepolia.

We only need the methods we actually call. Including full ABIs would bloat
the package and drift from upstream; this slim set is checked against the
canonical ABIs at https://github.com/ensdomains/ens-contracts.
"""

ENS_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "resolver",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "address", "name": "resolver", "type": "address"},
        ],
        "name": "setResolver",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


PUBLIC_RESOLVER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "string", "name": "key", "type": "string"},
        ],
        "name": "text",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "string", "name": "key", "type": "string"},
            {"internalType": "string", "name": "value", "type": "string"},
        ],
        "name": "setText",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "addr",
        "outputs": [{"internalType": "address payable", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "node", "type": "bytes32"},
            {"internalType": "address", "name": "a", "type": "address"},
        ],
        "name": "setAddr",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes[]", "name": "data", "type": "bytes[]"}],
        "name": "multicall",
        "outputs": [{"internalType": "bytes[]", "name": "results", "type": "bytes[]"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


# NameWrapper exposes setSubnodeRecord (label, owner, resolver, ttl, fuses, expiry).
NAME_WRAPPER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "parentNode", "type": "bytes32"},
            {"internalType": "string", "name": "label", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "uint64", "name": "ttl", "type": "uint64"},
            {"internalType": "uint32", "name": "fuses", "type": "uint32"},
            {"internalType": "uint64", "name": "expiry", "type": "uint64"},
        ],
        "name": "setSubnodeRecord",
        "outputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "parentNode", "type": "bytes32"},
            {"internalType": "string", "name": "label", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint32", "name": "fuses", "type": "uint32"},
            {"internalType": "uint64", "name": "expiry", "type": "uint64"},
        ],
        "name": "setSubnodeOwner",
        "outputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "node", "type": "bytes32"}],
        "name": "isWrapped",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


__all__ = ["ENS_REGISTRY_ABI", "NAME_WRAPPER_ABI", "PUBLIC_RESOLVER_ABI"]
