"""SQL Injection — /users/search?q=… filter is concatenated into query.

Medium difficulty. ``GET /users/search`` takes a ``q`` parameter and returns
matching users; the implementation builds a fake SQL filter via string
concatenation, so a UNION-style injection leaks more rows than the caller
should see.
"""

from __future__ import annotations

import re
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


_UNION_RE = re.compile(r"union\s+select|--\s*$|'\s*or\s*'1'='1", re.IGNORECASE)


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.get("/users/search")
        async def search_users(
            q: str = "", authorization: str | None = Header(None)
        ) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            # BUG: tautology / UNION injection in q returns the entire table.
            if _UNION_RE.search(q):
                return {"results": list(state.users.values())}
            results = [
                {"id": u["id"], "email": u["email"]}
                for u in state.users.values()
                if q and q.lower() in u["email"].lower()
            ]
            return {"results": results}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or replay.path != "/users/search":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("search did not succeed")
        q = replay.query.get("q", "")
        if not _UNION_RE.search(q):
            return fail("query did not contain an injection pattern")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict):
            return fail("malformed response")
        results = resp.get("results", [])
        if not isinstance(results, list) or not results:
            return fail("injection returned no rows")
        # Real exploit: returned rows include sensitive fields (password) the
        # base handler would have stripped.
        leaked = [r for r in results if isinstance(r, dict) and "password" in r]
        if not leaked:
            return fail("rows returned but password field not leaked")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "UNION-style SQLi leaked password column from /users/search",
            leaked_count=len(leaked),
        )


TEMPLATE = _Template(
    bug_id="sqli_user_search_v1",
    vuln_class="sqli",
    difficulty="medium",
    title="String-concatenated filter on /users/search",
    description=(
        "GET /users/search?q=… concatenates the q parameter into its filter. "
        "A UNION-style injection bypasses the projection list and returns "
        "raw user rows including the password column."
    ),
    affected_endpoint="GET /users/search",
)
