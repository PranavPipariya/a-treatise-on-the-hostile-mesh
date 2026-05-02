# AXL infrastructure

Gensyn AXL is a Go binary. We don't pin a prebuilt — we build from source on
first bootstrap so reviewers can audit what we're running.

## Build

```bash
bash infra/axl/build.sh
```

Produces `infra/axl/node`. The arena's `Supervisor` finds this via the
`HOSTILE_MESH_AXL_BINARY` env var (or auto-discovers from `infra/axl/node`).

## Topology used by Hostile Mesh

A match runs **9 AXL nodes** on a single laptop, all in a hub-and-spoke layout:

```
                    ┌──────── hub  (listens tls://127.0.0.1:9001) ────────┐
                    │                                                     │
        nightshade ─┤                                                     ├─ ironbark
                    │                                                     │
       historian.chorus, analyst.chorus, loyalist.chorus, skeptic.chorus, chaos.chorus
```

The hub is the only node with a `Listen` directive; every other node's
`node-config.json` lists `tls://127.0.0.1:9001` as its sole peer. This is
the simplest topology that demonstrates real cross-node Yggdrasil routing
without exposing public ports.

Per-node directories live under `${HOSTILE_MESH_AXL_RUNTIME_DIR}/nodes/<match_id>/<agent_id>/`
and contain the generated `node-config.json` plus a persistent ed25519 PEM.

## Ports

| Service                  | Default port |
|--------------------------|--------------|
| Hub Yggdrasil listen     | 9001         |
| Per-node HTTP API        | 9100..9108   |
| Per-node TCP             | 7100..7108   |

Port collisions are handled at config-generation time (`HubLayout` increments
indices). If your laptop is already using 9100..9108 you can shift the base
via `HOSTILE_MESH_AXL_BASE_API_PORT`.
