"""SQL Injection — /auth/login interpolates email into a fake-SQL filter.

Hard difficulty. The handler simulates a string-concatenated SQL query
against the in-memory user table; an attacker can inject ``' OR '1'='1`` -
style boolean tautologies to log in as the first matching user.

We don't actually run SQL — we run a tiny eval-free SQL-like filter that
honours the same logic flaw, so the bug behaves like a real SQLi without
requiring sqlite in the demo target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException

from hostile_mesh_combat.bugs._helpers import (
    TemplateBase,
    fail,
    parse_json_body,
    parse_json_response,
    succeed,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import _make_token  # noqa: PLC2701
from hostile_mesh_combat.types import ReplayRecord, Verdict


_TAUTOLOGY = re.compile(
    r"(?:'\s*or\s*'?1'?\s*=\s*'?1)|(?:--)|(?:#$)|(?:'\s*or\s*1\s*=\s*1)",
    re.IGNORECASE,
)


def _evaluate_filter(query: str, users: list[dict]) -> list[dict]:
    """A toy "WHERE email = '<query>'" simulator that honours OR tautologies.

    If the *literal* query is a known tautology pattern, return all users.
    Otherwise compare verbatim. This is the moral equivalent of a string-
    concatenated SQL query.
    """
    if _TAUTOLOGY.search(query):
        return list(users)
    return [u for u in users if u["email"] == query]


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.post("/auth/login")
        async def login_vuln(body: dict) -> dict:
            email = (body or {}).get("email", "")
            password = (body or {}).get("password", "")
            # BUG: classic SQLi — `email` is concatenated into a query string
            # and evaluated by the filter, so 'foo' OR '1'='1 returns all rows.
            query = f"{email}"
            matches = _evaluate_filter(query, list(state.users.values()))
            if not matches:
                raise HTTPException(401, "invalid credentials")
            user = matches[0]
            if password and password != user["password"]:
                # On tautology injection, password is rarely correct — but the
                # bug is the boolean injection itself: we still return on the
                # first match if the supplied password equals literally any
                # known password (yes, also broken).
                fallback = next((u for u in matches if u["password"] == password), None)
                if fallback is None:
                    # *Still* sign in as first matching user under the assumption
                    # that "the DB returned them, therefore they're valid."
                    pass
                else:
                    user = fallback
            token = _make_token(user["id"])
            state.sessions[token] = {"user_id": user["id"], "issued": 0}
            return {"token": token, "role": user["role"], "user_id": user["id"]}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/auth/login":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("login did not succeed")
        body = parse_json_body(replay)
        email = body.get("email", "") or ""
        if not _TAUTOLOGY.search(email):
            return fail("email field did not contain a tautology pattern")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict) or "token" not in resp:
            return fail("no token in response")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "boolean-tautology SQLi in login authenticated as some user",
            issued_role=resp.get("role"),
            issued_user_id=resp.get("user_id"),
        )


TEMPLATE = _Template(
    bug_id="sqli_login_concat_v1",
    vuln_class="sqli",
    difficulty="hard",
    title="String-concatenated email filter on /auth/login",
    description=(
        "The login handler builds its user-lookup filter by concatenating the "
        "supplied email into a query string. A boolean-tautology injection "
        "(' OR '1'='1) returns the first user in the table and the handler "
        "authenticates as them."
    ),
    affected_endpoint="POST /auth/login",
)
