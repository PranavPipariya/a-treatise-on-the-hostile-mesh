from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class NodeConfig:
    """Materialised on-disk node-config.json + identity for one AXL node."""

    agent_id: str
    config_path: Path
    private_key_path: Path
    api_port: int
    tcp_port: int
    listen_port: int | None
    peers: list[str]
    is_hub: bool

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"


@dataclass(slots=True)
class NodeSpec:
    """Inputs for ``HubLayout.materialize`` — the desired topology slot."""

    agent_id: str
    is_hub: bool = False


@dataclass(slots=True)
class HubLayout:
    """Hub-and-spoke topology generator.

    The first node marked ``is_hub`` listens on the loopback at
    ``hub_listen_port``. Every other node peers to that hub via
    ``tls://127.0.0.1:<hub_listen_port>``. This is the simplest topology
    that demonstrates real cross-node Yggdrasil routing on a single laptop
    without anyone having to expose a public port.
    """

    runtime_dir: Path
    base_api_port: int = 9100
    base_tcp_port: int = 7100
    hub_listen_port: int = 9001
    extra_router: bool = False
    nodes: list[NodeConfig] = field(default_factory=list)

    def materialize(self, specs: list[NodeSpec]) -> list[NodeConfig]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        configs: list[NodeConfig] = []

        hub_specs = [s for s in specs if s.is_hub]
        if not hub_specs:
            specs[0].is_hub = True  # promote first
            hub_specs = [specs[0]]
        if len(hub_specs) > 1:
            raise ValueError("HubLayout currently supports exactly one hub node")

        hub = hub_specs[0]

        for index, spec in enumerate(specs):
            agent_dir = self.runtime_dir / spec.agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            private_key = agent_dir / "private.pem"
            self._ensure_ed25519_key(private_key)

            api_port = self.base_api_port + index
            tcp_port = self.base_tcp_port + index
            listen_port = self.hub_listen_port if spec.is_hub else None

            payload: dict[str, object] = {
                "PrivateKeyPath": str(private_key),
                "Peers": [],
                "Listen": [],
                "api_port": api_port,
                "bridge_addr": "127.0.0.1",
                "tcp_port": tcp_port,
            }
            if spec.is_hub:
                payload["Listen"] = [f"tls://127.0.0.1:{self.hub_listen_port}"]
            else:
                payload["Peers"] = [f"tls://127.0.0.1:{self.hub_listen_port}"]

            if self.extra_router:
                payload["router_addr"] = "http://127.0.0.1"
                payload["router_port"] = 9300 + index
                payload["a2a_addr"] = "http://127.0.0.1"
                payload["a2a_port"] = 9400 + index

            config_path = agent_dir / "node-config.json"
            config_path.write_text(json.dumps(payload, indent=2))

            configs.append(
                NodeConfig(
                    agent_id=spec.agent_id,
                    config_path=config_path,
                    private_key_path=private_key,
                    api_port=api_port,
                    tcp_port=tcp_port,
                    listen_port=listen_port,
                    peers=[f"tls://127.0.0.1:{self.hub_listen_port}"] if not spec.is_hub else [],
                    is_hub=spec.is_hub,
                )
            )

        self.nodes = configs
        return configs

    @staticmethod
    def _ensure_ed25519_key(path: Path) -> None:
        if path.is_file() and path.stat().st_size > 0:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        # AXL accepts an OpenSSL-generated ed25519 PEM. If openssl is unavailable
        # the AXL node will generate an in-memory key on startup, but persistence
        # is preferable so peer IDs survive restarts.
        try:
            subprocess.run(
                ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(path)],
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            # Fall back to letting the node generate one — record the absence.
            path.write_text("")  # zero-byte sentinel; AXL will ignore + autogen
            os.chmod(path, 0o600)
            return
        os.chmod(path, 0o600)


__all__ = ["HubLayout", "NodeConfig", "NodeSpec"]
