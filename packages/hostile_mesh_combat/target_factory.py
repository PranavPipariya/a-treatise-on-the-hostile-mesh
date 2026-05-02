from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.types import BugInstance, ReplayRecord

logger = logging.getLogger(__name__)


@dataclass
class TargetService:
    """A built target — FastAPI app + the state it mutates + the seeded bugs.

    The arena keeps a handle to this so the verifier can replay exploit
    attempts against the *same* state mutations the live request produced.
    """

    combatant_id: str
    app: FastAPI
    state: TargetState
    bugs: list[BugInstance]
    base_routes: list[tuple[str, str]] = field(default_factory=list)
    request_log: list[ReplayRecord] = field(default_factory=list)
    bug_routes: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def affected_endpoints(self) -> list[str]:
        return sorted({b.template.affected_endpoint for b in self.bugs})

    def find_bugs_at(self, method: str, path: str) -> list[BugInstance]:
        sig = f"{method.upper()} {path}"
        return [b for b in self.bugs if b.template.affected_endpoint == sig]


# ─── Auth helper used by base + vulnerable handlers ──────────────────────────
def _bearer_user(state: TargetState, authorization: str | None) -> dict[str, Any] | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    sess = state.sessions.get(token)
    if not sess:
        return None
    return state.users.get(sess["user_id"])


def _make_token(user_id: int) -> str:
    return hashlib.sha256(f"sess-{user_id}-{time.time_ns()}".encode()).hexdigest()


# ─── Base (mostly safe) handlers ─────────────────────────────────────────────
def install_base_handlers(app: FastAPI, state: TargetState) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "ts": str(int(time.time()))}

    @app.post("/auth/login")
    async def login(body: dict) -> dict:
        email = (body or {}).get("email", "")
        password = (body or {}).get("password", "")
        for user in state.users.values():
            if user["email"] == email and user["password"] == password:
                token = _make_token(user["id"])
                state.sessions[token] = {"user_id": user["id"], "issued": time.time()}
                return {"token": token, "role": user["role"], "user_id": user["id"]}
        raise HTTPException(401, "invalid credentials")

    @app.get("/auth/me")
    async def me(authorization: str | None = Header(None)) -> dict:
        u = _bearer_user(state, authorization)
        if not u:
            raise HTTPException(401, "unauthenticated")
        return {"id": u["id"], "email": u["email"], "role": u["role"]}

    @app.get("/users/{user_id}")
    async def get_user(user_id: int, authorization: str | None = Header(None)) -> dict:
        caller = _bearer_user(state, authorization)
        if not caller:
            raise HTTPException(401, "unauthenticated")
        target = state.users.get(user_id)
        if not target:
            raise HTTPException(404, "no such user")
        # Base behaviour: callers can only see themselves unless admin.
        if caller["id"] != user_id and caller["role"] != "admin":
            raise HTTPException(403, "forbidden")
        return {"id": target["id"], "email": target["email"], "role": target["role"]}

    @app.get("/users")
    async def list_users(authorization: str | None = Header(None)) -> dict:
        caller = _bearer_user(state, authorization)
        if not caller or caller["role"] != "admin":
            raise HTTPException(403, "forbidden")
        return {"users": [{"id": u["id"], "email": u["email"]} for u in state.users.values()]}

    @app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: int, authorization: str | None = Header(None)) -> dict:
        caller = _bearer_user(state, authorization)
        if not caller:
            raise HTTPException(401, "unauthenticated")
        inv = state.invoices.get(invoice_id)
        if not inv:
            raise HTTPException(404, "no such invoice")
        if inv["owner"] != caller["id"] and caller["role"] != "admin":
            raise HTTPException(403, "forbidden")
        return inv

    @app.get("/files/{name:path}")
    async def get_file(name: str) -> PlainTextResponse:
        data = state.files.get(name)
        if not data:
            raise HTTPException(404, "no such file")
        return PlainTextResponse(data.decode("utf-8", errors="replace"))

    @app.post("/transfers")
    async def transfer(body: dict, authorization: str | None = Header(None)) -> dict:
        caller = _bearer_user(state, authorization)
        if not caller:
            raise HTTPException(401, "unauthenticated")
        amount = int((body or {}).get("amount", 0))
        recipient = int((body or {}).get("recipient", 0))
        if amount <= 0 or recipient not in state.users:
            raise HTTPException(400, "invalid request")
        with state.lock:
            if state.balances.get(caller["id"], 0) < amount:
                raise HTTPException(400, "insufficient funds")
            state.balances[caller["id"]] -= amount
            state.balances[recipient] = state.balances.get(recipient, 0) + amount
        state.audit_log.append(
            {"kind": "transfer", "from": caller["id"], "to": recipient, "amount": amount}
        )
        return {"ok": True, "balance": state.balances[caller["id"]]}

    routes = [
        ("GET", "/health"),
        ("POST", "/auth/login"),
        ("GET", "/auth/me"),
        ("GET", "/users/{user_id}"),
        ("GET", "/users"),
        ("GET", "/invoices/{invoice_id}"),
        ("GET", "/files/{name}"),
        ("POST", "/transfers"),
    ]
    return routes


# ─── Request capture middleware ──────────────────────────────────────────────
def install_request_logger(service: TargetService) -> None:
    """Captures every (method, path, body) → (status, body) tuple so the
    verifier can re-examine a successful exploit's effects later."""

    @service.app.middleware("http")
    async def capture(request: Request, call_next: Callable):  # type: ignore
        body = await request.body()
        response = await call_next(request)
        # Read response body safely without consuming the stream from FastAPI.
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        full_body = b"".join(chunks)
        record = ReplayRecord(
            method=request.method,
            path=request.url.path,
            headers=dict(request.headers),
            query={k: v for k, v in request.query_params.items()},
            body=body,
            status_code=response.status_code,
            response_body=full_body,
            response_headers=dict(response.headers),
        )
        service.request_log.append(record)
        if len(service.request_log) > 4096:
            service.request_log = service.request_log[-2048:]
        return JSONResponse(
            content=None,
            status_code=response.status_code,
            background=None,
        ) if False else _rebuild_response(full_body, response)


def _rebuild_response(body: bytes, original: Any) -> Any:
    from starlette.responses import Response

    return Response(
        content=body,
        status_code=original.status_code,
        headers={k: v for k, v in original.headers.items() if k.lower() != "content-length"},
        media_type=original.media_type,
    )


def build_target_service(
    combatant_id: str,
    bugs: list[BugInstance],
    *,
    state: TargetState | None = None,
) -> TargetService:
    """Compose the FastAPI app for a combatant.

    Order of operations matters: vulnerable bug routes are registered
    *first* so they win over base safe handlers when paths collide.
    """

    state = state or TargetState.seeded(combatant_id)
    app = FastAPI(title=f"hostile-mesh target [{combatant_id}]", version="0.1.0")
    service = TargetService(
        combatant_id=combatant_id, app=app, state=state, bugs=bugs
    )
    install_request_logger(service)

    for bug in bugs:
        try:
            bug.template.apply(app, state)
            service.bug_routes[bug.template.bug_id] = [
                (bug.template.affected_endpoint.split(" ", 1)[0],
                 bug.template.affected_endpoint.split(" ", 1)[1])
            ]
        except Exception:
            logger.exception("failed to install bug %s", bug.template.bug_id)

    service.base_routes = install_base_handlers(app, state)
    return service


__all__ = ["TargetService", "build_target_service"]
