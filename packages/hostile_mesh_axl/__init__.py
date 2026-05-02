"""Gensyn AXL — Go-binary supervisor + Python client + high-level mesh.

A Hostile Mesh deployment runs one AXL node per agent (combatants + chorus +
arena bridge). This package brings the whole AXL surface to Python:

- ``binary``   — locate or build the ``./node`` binary from the upstream repo.
- ``config``   — generate per-node ``node-config.json`` files with unique ports,
                 ed25519 keys, and a hub-and-spoke peer topology.
- ``client``   — typed HTTPX wrapper around `/topology /send /recv /mcp /a2a`.
- ``supervisor``— spawn N node processes, capture logs, await peer-id readiness.
- ``mesh``     — high-level publish / broadcast / inbox queue with envelopes.
"""

from hostile_mesh_axl.binary import AxlBinary, ensure_binary
from hostile_mesh_axl.client import AxlClient, AxlError, Topology
from hostile_mesh_axl.config import HubLayout, NodeConfig, NodeSpec
from hostile_mesh_axl.mesh import CombatEnvelope, Mesh, MeshNode
from hostile_mesh_axl.supervisor import AxlNodeProcess, Supervisor

__all__ = [
    "AxlBinary",
    "AxlClient",
    "AxlError",
    "AxlNodeProcess",
    "CombatEnvelope",
    "HubLayout",
    "Mesh",
    "MeshNode",
    "NodeConfig",
    "NodeSpec",
    "Supervisor",
    "Topology",
    "ensure_binary",
]
