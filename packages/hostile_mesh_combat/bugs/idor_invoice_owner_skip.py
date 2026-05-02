"""IDOR — /invoices/{id} skips the owner check.

Easy difficulty. The vulnerable handler returns the invoice without
verifying ownership; any authenticated user can read any invoice by
incrementing the ID.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException

from hostile_mesh_combat.bugs._helpers import (
    TemplateBase,
    fail,
    parse_json_response,
    succeed,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import _bearer_user  # noqa: PLC2701
from hostile_mesh_combat.types import ReplayRecord, Verdict


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.get("/invoices/{invoice_id}")
        async def get_invoice_vuln(
            invoice_id: int, authorization: str | None = Header(None)
        ) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            inv = state.invoices.get(invoice_id)
            if not inv:
                raise HTTPException(404, "no such invoice")
            # BUG: missing owner check. Any logged-in user can read any invoice.
            return inv

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or not replay.path.startswith("/invoices/"):
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("request did not succeed")
        try:
            invoice_id = int(replay.path.rsplit("/", 1)[-1])
        except ValueError:
            return fail("could not parse invoice id from path")
        token = (replay.headers.get("authorization", "") or "").replace("Bearer ", "")
        sess = state.sessions.get(token, {})
        caller_id = sess.get("user_id", -1)
        caller = state.users.get(caller_id)
        invoice = state.invoices.get(invoice_id)
        if not caller or not invoice:
            return fail("caller or invoice missing from state")
        # Must be reading an invoice the caller does NOT own and must NOT be admin.
        if caller["role"] == "admin":
            return fail("caller is admin — not an IDOR bypass")
        if invoice["owner"] == caller["id"]:
            return fail("caller is the owner — no horizontal privilege escalation")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or resp.get("id") != invoice_id:
            return fail("response did not contain invoice payload")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "non-owner read another user's invoice",
            invoice_id=invoice_id,
            invoice_owner=invoice["owner"],
            caller_id=caller["id"],
        )


TEMPLATE = _Template(
    bug_id="idor_invoice_owner_skip_v1",
    vuln_class="idor",
    difficulty="easy",
    title="GET /invoices/{id} skips owner check",
    description=(
        "Any authenticated user can read any invoice by ID — the handler only "
        "checks for *some* valid session, not whether the session belongs to "
        "the invoice's owner."
    ),
    affected_endpoint="GET /invoices/{invoice_id}",
)
