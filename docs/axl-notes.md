# AXL operational notes

What we depend on from Gensyn AXL, distilled from the upstream README,
`docs/api.md`, `docs/configuration.md`, `docs/architecture.md`, and the
example python-client.

## What we use

- **Go binary** `./node` from `cmd/node/` (built via `make build`).
- **HTTP API at `127.0.0.1:9002`** (per node) — we configure `api_port`
  to a unique value per agent so multiple nodes can run on one laptop.
  Endpoints we call:
  - `GET /topology` → reads `our_public_key` (the 64-hex ed25519 peer ID).
  - `POST /send` with `X-Destination-Peer-Id` → outbound combat envelope.
  - `GET /recv` → long-poll inbound queue. Returns 204 when empty.
  - We do *not* currently use `/mcp/{peer_id}/{service}` or
    `/a2a/{peer_id}` — combat envelopes are plain JSON over `/send /recv`.
    The wiring is in place via `AxlClient.mcp / a2a` if a future feature
    needs it.
- **node-config.json** with the documented fields:
  - `PrivateKeyPath` — persistent ed25519 PEM under
    `${HOSTILE_MESH_AXL_RUNTIME_DIR}/nodes/<match>/<agent>/private.pem`.
  - `Peers` — for spoke nodes: `["tls://127.0.0.1:<HUB_PORT>"]`.
  - `Listen` — only on the hub node: `["tls://127.0.0.1:<HUB_PORT>"]`.
  - `api_port`, `bridge_addr`, `tcp_port` — uniquely assigned per node.
- **Wire format**: AXL handles the 4-byte length prefix on the TCP side;
  applications send raw bytes via `/send`. We JSON-encode our combat
  envelope (see `packages/hostile_mesh_axl/mesh.py::CombatEnvelope`) with
  `sort_keys=True` for stable serialization and signature compatibility.

## Topology per match (9 nodes)

```
hub (Listen: tls://127.0.0.1:9001)
  ├── nightshade            (Peers: tls://127.0.0.1:9001)
  ├── ironbark              (Peers: tls://127.0.0.1:9001)
  ├── historian.chorus      (Peers: tls://127.0.0.1:9001)
  ├── analyst.chorus        (Peers: tls://127.0.0.1:9001)
  ├── loyalist.chorus       (Peers: tls://127.0.0.1:9001)
  ├── skeptic.chorus        (Peers: tls://127.0.0.1:9001)
  └── chaos.chorus          (Peers: tls://127.0.0.1:9001)
```

Per-node API ports default to 9100..9108. Per-node TCP ports 7100..7108.
Override via `HOSTILE_MESH_AXL_BASE_API_PORT` etc. in `.env`.

## Channels

AXL has no native pub/sub. We define three logical channels in
`packages/hostile_mesh_axl/mesh.py` and route via per-peer `/send`:

| Channel        | Members                         | Purpose                                        |
|----------------|---------------------------------|------------------------------------------------|
| `arena`        | combatants + arena bridge       | control plane (start/stop, scoring updates)    |
| `chorus`       | all five chorus + combatants    | broadcast spectator + claim events             |
| `duel`         | the two combatants              | direct taunts and exploit_outcome notifications |

Each broadcast iterates the channel's member list and issues `POST /send`
to each peer ID, with the same envelope (`id` field deduplicates so a
node that receives the same event twice via different paths drops it).

## Why AXL is structurally necessary, not an aesthetic choice

- **Adversarial isolation**: combatants share *no* in-process state.
  An exploit that compromises combatant A cannot reach combatant B's
  agent state — they're separate OS processes with separate keys.
- **Real peer discovery**: the arena learns peer IDs only after each
  AXL node reports its `/topology`. There is no central registry.
- **Cross-node send/recv**: every combat envelope crosses an AXL node
  boundary. The two-AXL-node integration test
  (`tests/integration/test_axl_two_nodes.py`) is the qualification proof.

## Build

```bash
bash infra/axl/build.sh         # builds infra/axl/node from gensyn-ai/axl
HOSTILE_MESH_RUN_AXL_TESTS=1 \\
  python -m pytest tests/integration/test_axl_two_nodes.py -q
```
