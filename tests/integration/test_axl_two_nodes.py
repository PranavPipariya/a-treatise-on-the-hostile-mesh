"""Boot two real AXL Go-binary nodes and verify cross-node communication.

Skipped automatically when:
  - the AXL binary doesn't exist (no `infra/axl/node`),
  - or the Go toolchain isn't available to build it,
  - or the test runner doesn't have ports 9001/9100/9101/7100/7101 free.

When it does run, this test is the qualification proof for the Gensyn AXL
track: separate processes, separate ed25519 keys, real Yggdrasil routing,
and a verifiable round-trip via /send + /recv.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from hostile_mesh_axl.binary import ensure_binary
from hostile_mesh_axl.client import AxlClient
from hostile_mesh_axl.config import HubLayout, NodeSpec
from hostile_mesh_axl.supervisor import Supervisor


@pytest.mark.skipif(
    shutil.which("go") is None and not Path("infra/axl/node").is_file(),
    reason="AXL binary unavailable (Go toolchain not installed and no prebuilt node)",
)
@pytest.mark.skipif(
    os.getenv("HOSTILE_MESH_RUN_AXL_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="AXL integration tests are gated by HOSTILE_MESH_RUN_AXL_TESTS=1 (they spawn real processes)",
)
def test_two_nodes_send_and_recv(tmp_path):
    asyncio.run(_run(tmp_path))


async def _run(tmp_path: Path) -> None:
    binary = ensure_binary(tmp_path / "axl")
    layout = HubLayout(
        runtime_dir=tmp_path / "axl-nodes",
        base_api_port=9100,
        base_tcp_port=7100,
        hub_listen_port=9001,
    )
    configs = layout.materialize(
        [
            NodeSpec(agent_id="hub", is_hub=True),
            NodeSpec(agent_id="alpha"),
        ]
    )
    supervisor = Supervisor(binary, log_dir=tmp_path / "logs")
    try:
        nodes = await supervisor.start_all(configs, per_node_ready_timeout=45.0)
        hub_peer = nodes["hub"].peer_id
        alpha_peer = nodes["alpha"].peer_id
        assert hub_peer and alpha_peer and hub_peer != alpha_peer

        # Send a payload alpha → hub, then poll hub's /recv for it.
        payload = b'{"hello":"hostile-mesh"}'
        hub_client = AxlClient(nodes["hub"].api_url)
        alpha_client = AxlClient(nodes["alpha"].api_url)
        try:
            await alpha_client.send(hub_peer, payload)
            received: tuple[str, bytes] | None = None
            for _ in range(40):
                received = await hub_client.recv()
                if received:
                    break
                await asyncio.sleep(0.25)
            assert received is not None, "hub never received the message"
            from_peer, body = received
            assert from_peer == alpha_peer
            assert body == payload
        finally:
            await hub_client.close()
            await alpha_client.close()
    finally:
        await supervisor.shutdown()
