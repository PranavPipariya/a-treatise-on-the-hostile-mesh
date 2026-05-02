from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from hostile_mesh_axl.binary import AxlBinary
from hostile_mesh_axl.client import AxlClient, AxlError
from hostile_mesh_axl.config import NodeConfig

logger = logging.getLogger(__name__)


@dataclass
class AxlNodeProcess:
    """Live handle to one running ``./node`` Go process.

    Holds the parsed ``peer_id`` once it has been observed from `/topology`,
    plus the underlying ``Popen`` so the supervisor can terminate it cleanly.
    """

    config: NodeConfig
    process: subprocess.Popen[bytes]
    log_path: Path
    peer_id: str = ""
    started_at: float = field(default_factory=time.monotonic)
    _closed: bool = False

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def api_url(self) -> str:
        return self.config.api_url

    def terminate(self, timeout: float = 4.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGTERM)
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                with contextlib.suppress(Exception):
                    self.process.wait(timeout=2.0)


class Supervisor:
    """Spawns one AXL Go process per agent in a hub-and-spoke topology.

    After spawning, waits for each node's HTTP API to be reachable and reads
    ``/topology`` to capture the ed25519 public key (peer ID). Exposes typed
    ``AxlNodeProcess`` records that the high-level ``Mesh`` uses for
    routing.
    """

    def __init__(self, binary: AxlBinary, log_dir: Path) -> None:
        self._binary = binary
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._nodes: dict[str, AxlNodeProcess] = {}
        self._sigterm_handler_installed = False

    def install_signal_handlers(self) -> None:
        if self._sigterm_handler_installed:
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        self._sigterm_handler_installed = True

    async def start_all(
        self,
        configs: list[NodeConfig],
        *,
        per_node_ready_timeout: float = 30.0,
        on_node_ready: Callable[[AxlNodeProcess], Awaitable[None]] | None = None,
    ) -> dict[str, AxlNodeProcess]:
        # Start the hub first so spokes can dial it as soon as they boot.
        hub_first = sorted(configs, key=lambda c: 0 if c.is_hub else 1)
        for cfg in hub_first:
            node = self._spawn(cfg)
            self._nodes[cfg.agent_id] = node
            await self._await_ready(node, per_node_ready_timeout)
            if on_node_ready:
                await on_node_ready(node)
        return dict(self._nodes)

    def get(self, agent_id: str) -> AxlNodeProcess | None:
        return self._nodes.get(agent_id)

    def all(self) -> list[AxlNodeProcess]:
        return list(self._nodes.values())

    async def shutdown(self) -> None:
        for node in self._nodes.values():
            node.terminate()
        self._nodes.clear()

    def _spawn(self, cfg: NodeConfig) -> AxlNodeProcess:
        log_path = self._log_dir / f"{cfg.agent_id}.log"
        log_fd = log_path.open("ab", buffering=0)
        env = os.environ.copy()
        env.setdefault("GOTOOLCHAIN", "go1.25.5")
        process = subprocess.Popen(  # noqa: S603 — known binary path
            [str(self._binary.binary_path), "-config", str(cfg.config_path)],
            stdout=log_fd,
            stderr=log_fd,
            env=env,
            cwd=str(cfg.config_path.parent),
        )
        return AxlNodeProcess(config=cfg, process=process, log_path=log_path)

    async def _await_ready(self, node: AxlNodeProcess, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        client = AxlClient(node.api_url)
        try:
            while True:
                if not node.alive:
                    tail = node.log_path.read_text()[-2_000:] if node.log_path.is_file() else ""
                    raise RuntimeError(
                        f"AXL node {node.config.agent_id!r} exited "
                        f"(code={node.process.returncode}). Last log:\n{tail}"
                    )
                try:
                    topo = await client.topology()
                except (AxlError, httpx.HTTPError):
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            f"AXL node {node.config.agent_id!r} did not become "
                            f"reachable on {node.api_url} within {timeout}s"
                        )
                    await asyncio.sleep(0.25)
                    continue
                node.peer_id = topo.our_public_key
                if node.peer_id:
                    return
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"AXL node {node.config.agent_id!r} reachable but "
                        f"reported empty public key after {timeout}s"
                    )
                await asyncio.sleep(0.25)
        finally:
            await client.close()


__all__ = ["AxlNodeProcess", "Supervisor"]
