"""ABI fragments for the Sepolia ETHRegistrarController.

Just the functions ``scripts/register_sepolia_parent.py`` calls. Sourced from
https://github.com/ensdomains/ens-contracts/blob/master/contracts/ethregistrar/ETHRegistrarController.sol
"""

ETH_REGISTRAR_CONTROLLER_ABI = [
    {
        "inputs": [{"internalType": "string", "name": "name", "type": "string"}],
        "name": "available",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "uint256", "name": "duration", "type": "uint256"},
        ],
        "name": "rentPrice",
        "outputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "base", "type": "uint256"},
                    {"internalType": "uint256", "name": "premium", "type": "uint256"},
                ],
                "internalType": "struct IPriceOracle.Price",
                "name": "price",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "duration", "type": "uint256"},
            {"internalType": "bytes32", "name": "secret", "type": "bytes32"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "bytes[]", "name": "data", "type": "bytes[]"},
            {"internalType": "bool", "name": "reverseRecord", "type": "bool"},
            {"internalType": "uint16", "name": "ownerControlledFuses", "type": "uint16"},
        ],
        "name": "makeCommitment",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "pure",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "commitment", "type": "bytes32"}],
        "name": "commit",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "duration", "type": "uint256"},
            {"internalType": "bytes32", "name": "secret", "type": "bytes32"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "bytes[]", "name": "data", "type": "bytes[]"},
            {"internalType": "bool", "name": "reverseRecord", "type": "bool"},
            {"internalType": "uint16", "name": "ownerControlledFuses", "type": "uint16"},
        ],
        "name": "register",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "minCommitmentAge",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "maxCommitmentAge",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# Canonical Sepolia ETHRegistrarController address.
SEPOLIA_ETH_REGISTRAR_CONTROLLER = "0xFED6a969AaA60E4961FCD3EBF1A2e8913ac65B72"


__all__ = ["ETH_REGISTRAR_CONTROLLER_ABI", "SEPOLIA_ETH_REGISTRAR_CONTROLLER"]
