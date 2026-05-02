"""Broken Access Control — /priv/keys is exposed without an admin check.

Easy difficulty. The endpoint exists for ops use and was supposed to be
gated on the admin role; the gate is missing.
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
        @app.get("/priv/keys")
        async def list_keys(authorization: str | None = Header(None)) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            # BUG: missing role check — every authenticated user gets the keys.
            return {"keys": list(state.secrets.keys()), "secrets": dict(state.secrets)}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or replay.path != "/priv/keys":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("/priv/keys did not return 200")
        token = (replay.headers.get("authorization", "") or "").replace("Bearer ", "")
        sess = state.sessions.get(token, {})
        caller = state.users.get(sess.get("user_id", -1))
        if not caller:
            return fail("no caller resolved from session")
        if caller.get("role") == "admin":
            return fail("caller was admin — not a privilege escalation")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or "secrets" not in resp:
            return fail("response did not include secrets payload")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "non-admin retrieved /priv/keys",
            caller_role=caller.get("role"),
            keys_count=len(resp.get("keys", [])),
        )


TEMPLATE = _Template(
    bug_id="broken_access_priv_export_v1",
    vuln_class="broken_access",
    difficulty="easy",
    title="/priv/keys exposed without admin check",
    description=(
        "GET /priv/keys lists internal secret material. It was supposed to "
        "be admin-only; the role check was never added."
    ),
    affected_endpoint="GET /priv/keys",
)
