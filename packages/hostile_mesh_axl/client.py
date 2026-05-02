from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class AxlError(RuntimeError):
    pass


@dataclass(slots=True)
class Topology:
    our_public_key: str
    our_ipv6: str
    peers: list[Any]
    tree: list[Any]

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> Topology:
        return cls(
            our_public_key=raw.get("our_public_key", ""),
            our_ipv6=raw.get("our_ipv6", ""),
            peers=list(raw.get("peers", []) or []),
            tree=list(raw.get("tree", []) or []),
        )


class AxlClient:
    """Async HTTPX client for one AXL node's local HTTP API.

    Mirrors the AXL HTTP surface (``/topology /send /recv /mcp /a2a``)
    one-to-one. ``recv`` returns ``None`` on a 204 (queue empty) so callers
    can long-poll without exception handling for the empty case.
    """

    def __init__(self, api_url: str, timeout: float = 10.0) -> None:
        self.api_url = api_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.api_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def topology(self) -> Topology:
        try:
            resp = await self._client.get("/topology")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AxlError(f"/topology failed: {exc}") from exc
        return Topology.from_payload(resp.json())

    async def send(self, destination_peer_id: str, payload: bytes) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                "/send",
                content=payload,
                headers={
                    "X-Destination-Peer-Id": destination_peer_id,
                    "Content-Type": "application/octet-stream",
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AxlError(f"/send failed: {exc}") from exc
        return {
            "status": resp.status_code,
            "sent_bytes": resp.headers.get("x-sent-bytes"),
        }

    async def recv(self) -> tuple[str, bytes] | None:
        """Poll for an inbound message. Returns ``(from_peer_id, payload)``
        or ``None`` if the queue is empty (HTTP 204)."""
        try:
            resp = await self._client.get("/recv")
        except httpx.HTTPError as exc:
            raise AxlError(f"/recv failed: {exc}") from exc
        if resp.status_code == 204:
            return None
        if resp.status_code != 200:
            raise AxlError(f"/recv unexpected status {resp.status_code}: {resp.text}")
        from_peer = resp.headers.get("x-from-peer-id", "")
        return from_peer, resp.content

    async def mcp(
        self, peer_id: str, service: str, request_body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"/mcp/{peer_id}/{service}",
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AxlError(f"/mcp failed: {exc}") from exc
        return resp.json()

    async def a2a(self, peer_id: str, request_body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"/a2a/{peer_id}",
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AxlError(f"/a2a failed: {exc}") from exc
        return resp.json()


__all__ = ["AxlClient", "AxlError", "Topology"]
