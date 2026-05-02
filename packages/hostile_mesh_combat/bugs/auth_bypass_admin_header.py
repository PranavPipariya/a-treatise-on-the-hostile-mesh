"""Auth bypass — `X-Internal-Admin: true` trusted across the trust boundary.

Medium difficulty. Pretends to be an internal-only header that an upstream
proxy would strip; the live target trusts it blindly.
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
        @app.get("/users")
        async def list_users_vuln(
            authorization: str | None = Header(None),
            x_internal_admin: str | None = Header(None),
        ) -> dict:
            if x_internal_admin == "true":
                # BUG: header is supposed to be stripped at the edge proxy.
                return {
                    "users": [
                        {"id": u["id"], "email": u["email"], "role": u["role"]}
                        for u in state.users.values()
                    ]
                }
            caller = _bearer_user(state, authorization)
            if not caller or caller["role"] != "admin":
                raise HTTPException(403, "forbidden")
            return {"users": [{"id": u["id"], "email": u["email"]} for u in state.users.values()]}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or replay.path != "/users":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("listing did not succeed")
        # The exploit must rely on the rogue header AND must NOT carry a real admin token.
        had_header = replay.headers.get("x-internal-admin", "").lower() == "true"
        if not had_header:
            return fail("did not use X-Internal-Admin: true")
        # If the request also carried a valid admin Bearer token, that's not the bypass.
        token = (replay.headers.get("authorization", "") or "").replace("Bearer ", "")
        sess = state.sessions.get(token, {})
        caller = state.users.get(sess.get("user_id", -1))
        if caller and caller.get("role") == "admin":
            return fail("request carried a real admin token — not a bypass")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or not resp.get("users"):
            return fail("response had no users")
        # And the response must include user records not visible to a non-admin.
        return succeed(
            self.bug_id,
            self.vuln_class,
            "X-Internal-Admin header bypassed admin role check",
            user_count=len(resp.get("users", [])),
        )


TEMPLATE = _Template(
    bug_id="auth_bypass_admin_header_v1",
    vuln_class="auth_bypass",
    difficulty="medium",
    title="X-Internal-Admin header trusted past the trust boundary",
    description=(
        "GET /users honours an internal X-Internal-Admin: true header that is "
        "*supposed* to be stripped by an edge proxy. The live target has no "
        "edge proxy in this environment, so the header is trusted directly."
    ),
    affected_endpoint="GET /users",
)
