"""IDOR — GET /users/{id} returns the password field on lookup.

Medium difficulty. The vulnerable handler returns the *full* user record,
including the password hash, when called by any authenticated peer.
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
        @app.get("/users/{user_id}")
        async def get_user_vuln(
            user_id: int, authorization: str | None = Header(None)
        ) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            target = state.users.get(user_id)
            if not target:
                raise HTTPException(404, "no such user")
            # BUG: returns full record (incl. `password`) regardless of caller.
            return dict(target)

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or not replay.path.startswith("/users/"):
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("request did not succeed")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or "password" not in resp:
            return fail("response did not leak the password field")
        try:
            user_id = int(replay.path.rsplit("/", 1)[-1])
        except ValueError:
            return fail("could not parse user id")
        target = state.users.get(user_id)
        token = (replay.headers.get("authorization", "") or "").replace("Bearer ", "")
        sess = state.sessions.get(token, {})
        caller = state.users.get(sess.get("user_id", -1))
        if not target or not caller:
            return fail("missing state")
        if caller["id"] == target["id"]:
            return fail("caller looked up themselves — not horizontal IDOR")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "GET /users/{id} leaked the password field across users",
            target_id=target["id"],
            password_prefix=str(target.get("password", ""))[:4],
        )


TEMPLATE = _Template(
    bug_id="idor_user_lookup_v1",
    vuln_class="idor",
    difficulty="medium",
    title="GET /users/{id} returns password field",
    description=(
        "The user-lookup endpoint serialises the full user record verbatim, "
        "including the password column, to anyone with a valid session."
    ),
    affected_endpoint="GET /users/{user_id}",
)
