# A Treatise on the Hostile Mesh

A peer-to-peer arena where autonomous AI agents probe each other's services for vulnerabilities, exploit what they find, patch their own systems under fire, and build verifiable on-chain reputations. The combat is the demo. The infrastructure is the product.

Built for the OpenAgents hackathon against the **Gensyn AXL** and **ENS** tracks.

## What it actually is

Two combatant agents and five spectator ("chorus") agents. Each runs as its own OS process with its own Yggdrasil-routed AXL node. Combatants own a small FastAPI service seeded with four randomly-selected vulnerabilities pulled from a 16-template bug bank covering eight vulnerability classes. They probe each other over AXL, commit to public exploit claims, patch their own services under fire, and sign every claim with an Ethereum wallet whose address is resolvable through their ENS subname.

Every meaningful event — match creation, endpoint rotation, signed wound, signed patch, chorus commentary — is a real on-chain ENS write under a configurable parent name (`HOSTILE_MESH_ENS_PARENT`). The match transcript becomes a queryable subname tree.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          UI (Vite)                              │
│  battle scene · ENS registry · AXL topology · post-match recap  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ SSE
┌──────────────────────────┴──────────────────────────────────────┐
│                  Arena (FastAPI + supervisor)                   │
│  match authority · scoring · verifier · process orchestration   │
└──────┬─────────────────┬──────────────────┬────────────────────┘
       │                 │                  │
   spawn/rpc         spawn/rpc          spawn/rpc
       │                 │                  │
┌──────┴────────┐  ┌─────┴────────┐  ┌─────┴───────────┐
│ combatant ×2  │  │ chorus ×5    │  │ target service  │
│ runtime+tools │  │ runtime+tool │  │ FastAPI w/ bugs │
└──────┬────────┘  └─────┬────────┘  └─────────────────┘
       │                 │
       ▼                 ▼
┌────────────────────────────────────────┐      ┌──────────────────┐
│   Gensyn AXL mesh (Go binary, 1/agent) │ ◄──► │ ENS on Sepolia    │
│   /send /recv /topology /mcp /a2a      │      │ subnames + texts  │
└────────────────────────────────────────┘      └──────────────────┘
```

The four packages under `packages/`:

- **`hostile_mesh_runtime`** — agent runtime adapted from [Godel](./Godel). Streaming Anthropic loop, typed Pydantic tools, six-mode permission engine, context compression, infinite-loop detection, hooks, sessions.
- **`hostile_mesh_axl`** — Go-binary supervisor + Python client for the AXL mesh. Generates per-node configs, spawns nodes with unique ports/keys, discovers peer IDs from `/topology`, exposes a typed `Mesh` for sending/receiving combat events across nodes.
- **`hostile_mesh_ens`** — Sepolia wallet + signer + on-chain ENS reader/writer. EIP-191 personal_sign for every claim, NameWrapper subname creation, custom resolver text records (`hm.axl.peer`, `hm.event.payload`, `hm.event.signature`, …), and a verifier that resolves an ENS name to its expected signer address.
- **`hostile_mesh_combat`** — vulnerability bug bank (16 templates / 8 classes), vulnerable target factory, deterministic exploit verifier, scoring.

The five service entrypoints under `services/`:

- **`arena`** — match authority, FastAPI + SSE event stream, process supervisor.
- **`combatant`** — boots a combatant agent process bound to its own AXL node + ENS identity.
- **`chorus`** — boots a chorus agent process (one per personality archetype).
- **`target`** — boots a vulnerable FastAPI service for a single combatant.

The UI lives in `apps/ui` (Vite + React + TypeScript) and follows the battle scene reference exactly: portrait-anchored chat bubbles, central endpoint hex with live attack lanes, ENS pending/confirmed pulses, AXL heartbeats, action logs, post-match archive.

## Run it

```bash
make bootstrap          # build AXL Go binary, set up venv, install UI deps
cp .env.example .env    # fill in keys (see notes below)
make register-ens       # generate Sepolia wallet + register a fresh *.eth
make demo               # spin everything up — arena API at :8787, UI at :5173
```

You need three things in `.env` for the full live experience:

1. **An LLM key** — either `API_KEY=…` (OpenRouter, Godel-compatible) *or*
   `ANTHROPIC_API_KEY=…`. The runtime auto-detects which provider to use.
2. **`HOSTILE_MESH_REGISTRAR_PRIVKEY`** + **`HOSTILE_MESH_ENS_PARENT`** —
   Sepolia wallet that owns a `*.eth` parent name. `make register-ens` does
   the whole bootstrap (generate wallet → fund from faucet → register name →
   write keys into `.env`) end-to-end.
3. **`HOSTILE_MESH_KEYSTORE_PASSPHRASE`** — any non-empty string; encrypts
   each agent's wallet keystore at rest.

If any of these are missing, the corresponding layer degrades visibly: the UI shows ENS records as `pending → failed` rather than fake confirmations, agents fall back to a deterministic policy instead of LLM reasoning, etc.

## Why we win the tracks

**Gensyn AXL — depth of integration.** Every agent (combatants + chorus + arena bridge = 9 processes) runs its own AXL node with unique ed25519 identity, unique ports, real `/send` + `/recv` traffic. Peer discovery happens through `/topology`. Two-node integration tests in `tests/integration/test_axl_two_nodes.py` prove cross-node communication. Adversarial isolation across processes is *structurally required* — you cannot share state between agents that are trying to break each other.

**ENS Best Integration for AI Agents.** ENS is the discovery and identity backbone. Combatants resolve each other through `<name>.<parent>` rather than knowing AXL peer IDs out of band. Each agent's resolver record (`hm.axl.peer`) holds its current peer ID. Each agent's wallet address (the ENS owner) signs every public claim, and the verifier rejects any wound/patch whose signature doesn't recover to the ENS-resolved address. No hardcoded values — `HOSTILE_MESH_ENS_PARENT` is the only knob.

**ENS Most Creative.** Three structurally honest creative angles:

1. **Auto-rotating endpoints.** Each match writes a new `hm.axl.epoch` record and a fresh `hm.axl.peer` value, so the ENS resolution of a combatant returns the *current* match endpoint.
2. **Subnames as scoped spectator access.** `spectator-<hash>.match-N.<parent>` subnames are time-bounded grants whose resolver record holds the broadcast channel ID and expiry.
3. **Subname tree as combat archive.** Every wound, patch, and chorus commentary is its own subname (`wound-N.match-M.<parent>`, etc.) with text records for the signed payload, the recovering address, and the verifier verdict — the entire combat history is queryable on-chain forever.

## Layout

```
packages/    importable Python libraries (runtime, axl, ens, combat)
services/    process entrypoints (arena, combatant, chorus, target)
apps/ui/     React/Vite battle UI
infra/axl/   AXL Go binary + per-node config generator
scripts/     bootstrap, demo runner, ENS bootstrap, stop-all
tests/       unit + integration (incl. two-AXL-node + signed claim round-trip)
docs/        protocol notes, build notes, design rationale
Godel/       reference: prior coding-agent project; runtime base
```
