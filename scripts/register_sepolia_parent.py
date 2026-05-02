"""Bootstrap a fresh Sepolia ENS name + registrar wallet for Hostile Mesh.

End-to-end flow (interactive, ~5 minutes including faucet wait):

  1. Generate a fresh Ethereum keypair (or reuse the one in .env if set).
  2. Print the wallet address; pause until the user funds it from a faucet.
  3. Pick an available `<name>.eth` on Sepolia (or accept --name).
  4. Submit `commit(commitment)` to the ETHRegistrarController.
  5. Wait `minCommitmentAge` seconds (60s on Sepolia).
  6. Submit `register{value: price}(...)` — the name is wrapped via NameWrapper
     automatically because the controller registers through it.
  7. Write HOSTILE_MESH_REGISTRAR_PRIVKEY + HOSTILE_MESH_ENS_PARENT into .env
     (and HOSTILE_MESH_KEYSTORE_PASSPHRASE if it's empty).

Usage:
    . .venv/bin/activate
    python scripts/register_sepolia_parent.py             # interactive
    python scripts/register_sepolia_parent.py --name foo  # specific name
    python scripts/register_sepolia_parent.py --reuse     # reuse existing privkey
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
import time
import uuid
from pathlib import Path

# Make package imports work without `pip install -e .`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from eth_account import Account  # noqa: E402
from eth_utils import to_checksum_address  # noqa: E402
from web3 import Web3  # noqa: E402

from hostile_mesh_ens.abis_controller import (  # noqa: E402
    ETH_REGISTRAR_CONTROLLER_ABI,
    SEPOLIA_ETH_REGISTRAR_CONTROLLER,
)
from hostile_mesh_ens.config import (  # noqa: E402
    DEFAULT_RPC,
    SEPOLIA_PUBLIC_RESOLVER,
)


ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
ONE_YEAR = 31_536_000

NAME_RE = re.compile(r"^[a-z0-9-]{3,63}$")


# ─── Pretty printers ─────────────────────────────────────────────────────────
def step(msg: str) -> None:
    print(f"\n\033[1;36m▸\033[0m {msg}")


def info(msg: str) -> None:
    print(f"  \033[2m{msg}\033[0m")


def ok(msg: str) -> None:
    print(f"  \033[1;32m✓\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"  \033[1;33m!\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"\n\033[1;31m✗\033[0m {msg}", file=sys.stderr)


# ─── .env editing (preserves all other lines verbatim) ───────────────────────
def read_env() -> dict[str, str]:
    if not ENV_PATH.is_file():
        if ENV_EXAMPLE_PATH.is_file():
            ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text())
            info(f"copied {ENV_EXAMPLE_PATH.name} → .env")
        else:
            ENV_PATH.write_text("")
    out: dict[str, str] = {}
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def write_env_var(key: str, value: str) -> None:
    """Set or append a single key=value, preserving the rest of the file."""
    text = ENV_PATH.read_text() if ENV_PATH.is_file() else ""
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    if pattern.search(text):
        text = pattern.sub(f"{key}={value}", text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{key}={value}\n"
    ENV_PATH.write_text(text)


# ─── Wallet setup ─────────────────────────────────────────────────────────────
def get_or_create_wallet(reuse_existing: bool, env: dict[str, str]):
    if reuse_existing and env.get("HOSTILE_MESH_REGISTRAR_PRIVKEY"):
        priv = env["HOSTILE_MESH_REGISTRAR_PRIVKEY"]
        if not priv.startswith("0x"):
            priv = "0x" + priv
        acct = Account.from_key(priv)
        ok(f"reusing existing registrar wallet {acct.address}")
        return acct
    acct = Account.create()
    ok(f"generated fresh registrar wallet {acct.address}")
    return acct


def wait_for_funding(w3: Web3, address: str, min_balance_wei: int) -> None:
    step(f"Fund the wallet from a Sepolia faucet (need ≥ {Web3.from_wei(min_balance_wei, 'ether')} SepETH).")
    info("Faucets:")
    info("  · https://sepoliafaucet.com/")
    info("  · https://www.alchemy.com/faucets/ethereum-sepolia")
    info("  · https://cloud.google.com/application/web3/faucet/ethereum/sepolia")
    info(f"Send funds to:  {address}")
    info("Polling balance every 10 s. Press Ctrl-C to abort.")
    while True:
        bal = w3.eth.get_balance(address)
        if bal >= min_balance_wei:
            ok(f"balance reached {Web3.from_wei(bal, 'ether'):.4f} SepETH — proceeding")
            return
        info(f"  current balance: {Web3.from_wei(bal, 'ether'):.4f} SepETH")
        time.sleep(10)


# ─── Name picking ─────────────────────────────────────────────────────────────
def is_valid_label(label: str) -> bool:
    return bool(NAME_RE.match(label))


def choose_label(controller, requested: str | None) -> str:
    if requested:
        if not is_valid_label(requested):
            raise SystemExit(f"invalid name {requested!r} (3-63 chars, [a-z0-9-])")
        if not controller.functions.available(requested).call():
            raise SystemExit(f"{requested}.eth is not available on Sepolia")
        return requested

    while True:
        candidate = f"hostile-mesh-{uuid.uuid4().hex[:6]}"
        if controller.functions.available(candidate).call():
            return candidate


# ─── Registration ─────────────────────────────────────────────────────────────
def build_tx_kwargs(w3: Web3, owner: str, *, gas: int) -> dict:
    gas_price = w3.eth.gas_price
    return {
        "chainId": 11155111,
        "from": owner,
        "nonce": w3.eth.get_transaction_count(owner, "pending"),
        "gas": gas,
        "maxFeePerGas": int(gas_price * 2),
        "maxPriorityFeePerGas": int(gas_price),
    }


def send(w3: Web3, signed) -> str:
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    return w3.eth.send_raw_transaction(raw).hex()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="Specific label (without .eth)")
    parser.add_argument("--rpc", default=os.getenv("HOSTILE_MESH_SEPOLIA_RPC", DEFAULT_RPC))
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse HOSTILE_MESH_REGISTRAR_PRIVKEY if set in .env",
    )
    parser.add_argument(
        "--duration-years",
        type=int,
        default=1,
        help="Registration duration in years (default: 1).",
    )
    parser.add_argument(
        "--passphrase",
        default=None,
        help="If set, also writes HOSTILE_MESH_KEYSTORE_PASSPHRASE.",
    )
    args = parser.parse_args()

    env = read_env()

    step(f"Connecting to Sepolia RPC ({args.rpc})")
    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        fail(f"could not connect to {args.rpc}")
        return 2
    chain_id = w3.eth.chain_id
    if chain_id != 11155111:
        fail(f"RPC reports chain_id={chain_id}, expected 11155111 (Sepolia)")
        return 2
    ok(f"connected · block {w3.eth.block_number}")

    controller = w3.eth.contract(
        address=to_checksum_address(SEPOLIA_ETH_REGISTRAR_CONTROLLER),
        abi=ETH_REGISTRAR_CONTROLLER_ABI,
    )

    step("Setting up registrar wallet")
    acct = get_or_create_wallet(args.reuse, env)

    step(f"Choosing a Sepolia ENS name")
    label = choose_label(controller, args.name)
    full_name = f"{label}.eth"
    ok(f"will register {full_name}")

    step("Computing rent price")
    duration = ONE_YEAR * max(1, args.duration_years)
    base, premium = controller.functions.rentPrice(label, duration).call()
    price_wei = base + premium
    info(
        f"base={Web3.from_wei(base, 'ether'):.6f} SepETH  "
        f"premium={Web3.from_wei(premium, 'ether'):.6f} SepETH  "
        f"total={Web3.from_wei(price_wei, 'ether'):.6f} SepETH"
    )

    # Pad funding requirement to comfortably cover gas + price.
    min_funding = price_wei + Web3.to_wei("0.01", "ether")
    wait_for_funding(w3, acct.address, min_funding)

    step("Submitting commitment")
    secret = secrets.token_bytes(32)
    resolver = to_checksum_address(SEPOLIA_PUBLIC_RESOLVER)
    commitment = controller.functions.makeCommitment(
        label,
        acct.address,
        duration,
        secret,
        resolver,
        [],
        False,
        0,
    ).call()
    info(f"commitment hash: 0x{commitment.hex()}")

    tx = controller.functions.commit(commitment).build_transaction(
        build_tx_kwargs(w3, acct.address, gas=120_000)
    )
    signed = w3.eth.account.sign_transaction(tx, private_key=acct.key)
    tx_hash = send(w3, signed)
    info(f"commit tx: {tx_hash}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        fail("commit reverted on-chain")
        return 3
    ok(f"commit confirmed in block {receipt['blockNumber']}")

    step("Waiting out commitment age")
    min_age = controller.functions.minCommitmentAge().call()
    info(f"minCommitmentAge = {min_age}s — sleeping...")
    for remaining in range(int(min_age) + 5, 0, -5):
        sys.stdout.write(f"\r  ⏱  {remaining:>3d}s ")
        sys.stdout.flush()
        time.sleep(5)
    print()

    step("Submitting register transaction")
    register_tx = controller.functions.register(
        label,
        acct.address,
        duration,
        secret,
        resolver,
        [],
        False,
        0,
    ).build_transaction(
        {
            **build_tx_kwargs(w3, acct.address, gas=400_000),
            "value": price_wei,
        }
    )
    signed = w3.eth.account.sign_transaction(register_tx, private_key=acct.key)
    tx_hash = send(w3, signed)
    info(f"register tx: {tx_hash}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=240)
    if receipt["status"] != 1:
        fail("register reverted on-chain — name may already be claimed or commitment expired")
        return 4
    ok(f"register confirmed in block {receipt['blockNumber']}")

    step("Writing .env")
    priv_hex = acct.key.hex()
    if not priv_hex.startswith("0x"):
        priv_hex = "0x" + priv_hex
    write_env_var("HOSTILE_MESH_REGISTRAR_PRIVKEY", priv_hex)
    write_env_var("HOSTILE_MESH_ENS_PARENT", full_name)
    if args.passphrase or not env.get("HOSTILE_MESH_KEYSTORE_PASSPHRASE"):
        passphrase = args.passphrase or "hostile-mesh-dev-" + secrets.token_hex(4)
        write_env_var("HOSTILE_MESH_KEYSTORE_PASSPHRASE", passphrase)
        ok(f"set HOSTILE_MESH_KEYSTORE_PASSPHRASE")
    ok(f"HOSTILE_MESH_REGISTRAR_PRIVKEY  → {acct.address}")
    ok(f"HOSTILE_MESH_ENS_PARENT         → {full_name}")

    print()
    ok("done — `make demo` is fully chain-live now")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        fail("aborted by user")
        sys.exit(130)
