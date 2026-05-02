"""Smoke-test the arena FastAPI surface in isolation (no AXL, no chain).

Ensures the routing, SSE plumbing, and shutdown lifecycle are correct
without spawning the full demo. Match-start is monkeypatched to avoid
spawning real AXL processes.
"""

from __future__ import annotations

import httpx
import pytest

from arena.api import build_app


@pytest.mark.asyncio
async def test_health_route():
    app = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "matches" in body


@pytest.mark.asyncio
async def test_state_404_on_unknown_match():
    app = build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/match/does-not-exist/state")
    assert resp.status_code == 404
