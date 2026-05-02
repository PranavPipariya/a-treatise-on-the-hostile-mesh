"""Boot a vulnerable target service in-process via httpx.ASGITransport and
exercise both successful and unsuccessful exploit attempts. Ensures each
bug template's ``apply()`` and ``verify()`` halves cohere with a real HTTP
round-trip.
"""

from __future__ import annotations

import httpx
import pytest

from hostile_mesh_combat.bug_bank import default_bank
from hostile_mesh_combat.target_factory import build_target_service
from hostile_mesh_combat.types import BugInstance


def _service(bug_id: str):
    bank = default_bank()
    bug = bank.by_id[bug_id]
    return build_target_service(
        "test-combatant",
        [BugInstance(template=bug, seed_id="t")],
    )


@pytest.mark.asyncio
async def test_empty_password_yields_admin_token():
    service = _service("auth_bypass_login_empty_password_v1")
    state = service.state
    admin_email = next(u["email"] for u in state.users.values() if u["role"] == "admin")
    transport = httpx.ASGITransport(app=service.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/auth/login", json={"email": admin_email, "password": ""})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "admin" and body["token"]


@pytest.mark.asyncio
async def test_correct_password_still_works():
    service = _service("auth_bypass_login_empty_password_v1")
    state = service.state
    user = next(iter(state.users.values()))
    transport = httpx.ASGITransport(app=service.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/auth/login", json={"email": user["email"], "password": user["password"]}
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_request_log_captures_payload():
    service = _service("auth_bypass_login_empty_password_v1")
    transport = httpx.ASGITransport(app=service.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/health")
    log = service.request_log
    assert any(r.path == "/health" and r.method == "GET" for r in log)


@pytest.mark.asyncio
async def test_idor_invoice_owner_skip_actually_leaks():
    service = _service("idor_invoice_owner_skip_v1")
    state = service.state
    # Create a session for user 1 (a regular user); fetch invoice 10003 (owned
    # by the admin anchor).
    user_token = "test-session"
    state.sessions[user_token] = {"user_id": 1, "issued": 0}
    transport = httpx.ASGITransport(app=service.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/invoices/10003", headers={"Authorization": f"Bearer {user_token}"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 10003 and body["owner"] != 1


@pytest.mark.asyncio
async def test_path_traversal_secrets_returns_real_secret():
    service = _service("path_traversal_secrets_v1")
    transport = httpx.ASGITransport(app=service.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/files/..%2F..%2Fetc%2Fpasswd")
        if resp.status_code != 200:
            resp = await client.get("/files/../../etc/passwd")
    assert resp.status_code == 200
    assert "root" in resp.text or "PRIVATE" in resp.text or "DB_PASSWORD" in resp.text
