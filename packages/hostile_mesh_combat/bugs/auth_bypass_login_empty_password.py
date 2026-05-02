"""Auth bypass — login with empty password short-circuits to admin.

Easy difficulty. The vulnerable handler trusts a falsy ``password`` to mean
"developer override" — a plausible bug for code that grew organically from
local-dev shortcuts.

Fix signature:  the patched code must check that ``password`` is truthy and
must compare it strictly to the stored value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException

from hostile_mesh_combat.bugs._helpers import (
    TemplateBase,
    parse_json_body,
    parse_json_response,
    succeed,
    fail,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import _make_token  # noqa: PLC2701
from hostile_mesh_combat.types import ReplayRecord, Verdict


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        # Vulnerable variant of /auth/login. Registered before base so it wins.
        @app.post("/auth/login")
        async def login(body: dict) -> dict:  # noqa: ARG001
            email = (body or {}).get("email", "")
            password = (body or {}).get("password", "")
            user = next((u for u in state.users.values() if u["email"] == email), None)
            if not user:
                raise HTTPException(401, "invalid credentials")
            # BUG: falsy password short-circuits to "dev override" — comment
            # left from a long-gone local-dev tool. inspect_self() shows it.
            if not password or password == user["password"]:
                token = _make_token(user["id"])
                state.sessions[token] = {"user_id": user["id"], "issued": 0}
                return {"token": token, "role": user["role"], "user_id": user["id"]}
            raise HTTPException(401, "invalid credentials")

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/auth/login":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("login did not succeed")
        body = parse_json_body(replay)
        password = body.get("password", "")
        # The exploit only counts if a *non-existent or empty* password landed
        # an admin/elevated session. We don't reward correct creds.
        if password not in ("", None):
            return fail("login used a real password — not a bypass")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or "token" not in resp:
            return fail("response had no token")
        if resp.get("role") != "admin":
            return fail("token issued but not admin — partial credit unsupported")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "login accepted empty password and returned admin token",
            email=body.get("email"),
            issued_token_prefix=resp["token"][:8],
        )


TEMPLATE = _Template(
    bug_id="auth_bypass_login_empty_password_v1",
    vuln_class="auth_bypass",
    difficulty="easy",
    title="Empty-password admin bypass on /auth/login",
    description=(
        "A 'dev override' shortcut accepts logins with an empty password and "
        "issues a session for whatever email is supplied. If the supplied "
        "email belongs to an admin user, the attacker gets an admin token."
    ),
    affected_endpoint="POST /auth/login",
)
