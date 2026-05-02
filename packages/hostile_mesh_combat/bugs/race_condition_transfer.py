"""Race Condition — /transfers performs check-then-act without locking.

Medium difficulty. The vulnerable variant of /transfers reads the balance,
checks it, then writes the new balances *without* the state mutex held.
Sufficiently fast back-to-back requests double-spend.

Verifier: a wound is awarded if the audit log shows two transfers from the
same source whose sum exceeds the source's *initial* balance, with response
codes that both indicate success.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException

from hostile_mesh_combat.bugs._helpers import TemplateBase, fail, succeed
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import _bearer_user  # noqa: PLC2701
from hostile_mesh_combat.types import ReplayRecord, Verdict


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.post("/transfers")
        async def transfer_vuln(body: dict, authorization: str | None = Header(None)) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            amount = int((body or {}).get("amount", 0))
            recipient = int((body or {}).get("recipient", 0))
            if amount <= 0 or recipient not in state.users:
                raise HTTPException(400, "invalid request")
            # BUG: TOCTOU. Read balance, yield to the loop, then write — without
            # the lock. Two concurrent requests both see a sufficient balance.
            current = state.balances.get(caller["id"], 0)
            if current < amount:
                raise HTTPException(400, "insufficient funds")
            await asyncio.sleep(0)  # explicit yield; the bug is that we yield mid-CAS
            state.balances[caller["id"]] = current - amount
            state.balances[recipient] = state.balances.get(recipient, 0) + amount
            state.audit_log.append(
                {"kind": "transfer", "from": caller["id"], "to": recipient, "amount": amount}
            )
            return {"ok": True, "balance": state.balances[caller["id"]]}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/transfers":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("transfer did not return 200")
        # Look at the audit log — does any single user have transfers totalling
        # more than their *seeded* balance? Initial seeded balance is 1000.
        from collections import defaultdict

        per_user: dict[int, int] = defaultdict(int)
        for entry in state.audit_log:
            if entry.get("kind") == "transfer":
                per_user[entry["from"]] += int(entry["amount"])
        offenders = {uid: spent for uid, spent in per_user.items() if spent > 1000}
        if not offenders:
            return fail("no double-spend detected in audit log")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "TOCTOU race in /transfers allowed a double-spend",
            spent_per_user=offenders,
        )


TEMPLATE = _Template(
    bug_id="race_condition_transfer_v1",
    vuln_class="race_condition",
    difficulty="medium",
    title="/transfers TOCTOU on balance check",
    description=(
        "The vulnerable transfer handler reads the source balance, yields to "
        "the event loop, then writes the debit. Two concurrent transfers "
        "both observe sufficient funds and both proceed."
    ),
    affected_endpoint="POST /transfers",
)
