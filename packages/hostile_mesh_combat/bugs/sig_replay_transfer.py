"""Signature Replay — /signed/transfer accepts the same nonce twice.

Hard difficulty. The handler verifies an HMAC over `(from, to, amount,
nonce, ts)` but never records used nonces, so a captured signature can be
replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException

from hostile_mesh_combat.bugs._helpers import (
    TemplateBase,
    fail,
    parse_json_body,
    succeed,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.types import ReplayRecord, Verdict


_HMAC_KEY = b"hostile-mesh-shared-secret-v1"  # known to combatants via inspect_self


def _expected_sig(from_id: int, to_id: int, amount: int, nonce: str, ts: int) -> str:
    msg = f"{from_id}|{to_id}|{amount}|{nonce}|{ts}".encode()
    return hmac.new(_HMAC_KEY, msg, hashlib.sha256).hexdigest()


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.post("/signed/transfer")
        async def signed_transfer(body: dict) -> dict:
            from_id = int((body or {}).get("from", 0))
            to_id = int((body or {}).get("to", 0))
            amount = int((body or {}).get("amount", 0))
            nonce = str((body or {}).get("nonce", ""))
            ts = int((body or {}).get("ts", 0))
            sig = str((body or {}).get("sig", ""))
            if (
                from_id not in state.users
                or to_id not in state.users
                or amount <= 0
                or not nonce
                or not sig
            ):
                raise HTTPException(400, "invalid request")
            expected = _expected_sig(from_id, to_id, amount, nonce, ts)
            if not hmac.compare_digest(expected, sig):
                raise HTTPException(401, "invalid signature")
            # BUG: nonce is never recorded; ts is never bounded.
            with state.lock:
                if state.balances.get(from_id, 0) < amount:
                    raise HTTPException(400, "insufficient funds")
                state.balances[from_id] -= amount
                state.balances[to_id] = state.balances.get(to_id, 0) + amount
            state.audit_log.append(
                {
                    "kind": "signed_transfer",
                    "from": from_id,
                    "to": to_id,
                    "amount": amount,
                    "nonce": nonce,
                    "ts": ts,
                }
            )
            return {
                "ok": True,
                "balance": state.balances[from_id],
                "served_at": int(time.time()),
            }

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/signed/transfer":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("transfer did not succeed")
        body = parse_json_body(replay)
        nonce = str(body.get("nonce", ""))
        from_id = int(body.get("from", 0))
        # Replay verdict: the exact nonce was used at least twice for this from_id
        # in the audit log. (The verifier doesn't ask the combatant to *attempt*
        # a replay — it observes that the same nonce settled twice.)
        matching = [
            e
            for e in state.audit_log
            if e.get("kind") == "signed_transfer"
            and e.get("from") == from_id
            and e.get("nonce") == nonce
        ]
        if len(matching) < 2:
            return fail("nonce was not actually replayed (only one settlement)")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "/signed/transfer accepted the same nonce twice",
            nonce=nonce,
            replays=len(matching),
        )


TEMPLATE = _Template(
    bug_id="sig_replay_transfer_v1",
    vuln_class="signature_replay",
    difficulty="hard",
    title="/signed/transfer accepts replayed nonces",
    description=(
        "The signed-transfer endpoint verifies an HMAC over the request "
        "(including a `nonce` and `ts`) but never records used nonces. A "
        "captured request can be re-submitted to repeat the transfer."
    ),
    affected_endpoint="POST /signed/transfer",
)
