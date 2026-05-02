# Summary of what was built

Pointers into the source so a reviewer can navigate the whole system in
under five minutes.

## Total surface

| Layer                          | Path                                  | Approx. LoC |
|--------------------------------|---------------------------------------|-------------|
| Agent runtime                  | `packages/hostile_mesh_runtime/`      | ~800        |
| AXL multi-node layer           | `packages/hostile_mesh_axl/`          | ~700        |
| ENS Sepolia layer              | `packages/hostile_mesh_ens/`          | ~900        |
| Combat domain (bugs, target,   | `packages/hostile_mesh_combat/`       | ~1500       |
|  verifier, agent tools)        |                                       |             |
| Service entrypoints            | `services/{arena,combatant,chorus,target}/` | ~1500 |
| UI                             | `apps/ui/src/`                        | ~1200       |
| Tests                          | `tests/`                              | ~600        |
| Docs                           | `docs/`                               | ~400        |
| Run scripts + infra            | `scripts/`, `infra/`                  | ~150        |

## Quick navigation

**The agent loop** — adapted from Godel
- `packages/hostile_mesh_runtime/runtime/orchestrator.py` — streaming loop
- `packages/hostile_mesh_runtime/client/anthropic_client.py` — tool-use streaming
- `packages/hostile_mesh_runtime/tools/registry.py` — Pydantic-validated dispatch
- `packages/hostile_mesh_runtime/context/loop_detector.py` — infinite-loop guard

**AXL** — qualification surface for the Gensyn track
- `packages/hostile_mesh_axl/binary.py` — clones+builds the Go node
- `packages/hostile_mesh_axl/config.py` — hub-and-spoke `node-config.json` gen
- `packages/hostile_mesh_axl/supervisor.py` — spawns N nodes, awaits peer-id readiness
- `packages/hostile_mesh_axl/mesh.py` — `Mesh.send` / `broadcast` over `/send /recv`
- `tests/integration/test_axl_two_nodes.py` — proof of cross-node communication

**ENS** — Sepolia identity, signing, archive
- `packages/hostile_mesh_ens/wallet.py` — encrypted per-agent keystores
- `packages/hostile_mesh_ens/signer.py` — EIP-191 sign + recover
- `packages/hostile_mesh_ens/chain.py` — web3.py contract handles
- `packages/hostile_mesh_ens/subnames.py` — `NameWrapper.setSubnodeRecord`
- `packages/hostile_mesh_ens/resolver.py` — `setText` via `multicall` for atomic record bundles
- `packages/hostile_mesh_ens/archive.py` — high-level `register_agent / record_event / grant_spectator`

**Combat domain**
- `packages/hostile_mesh_combat/bugs/*.py` — 12 vulnerability templates / 8 classes
- `packages/hostile_mesh_combat/bug_bank.py` — deterministic seeding
- `packages/hostile_mesh_combat/target_factory.py` — per-combatant FastAPI app
- `packages/hostile_mesh_combat/verifier.py` — replay against live target state
- `packages/hostile_mesh_combat/scoring.py` — wounds / patches / failed-claim accounting
- `packages/hostile_mesh_combat/agent_tools.py` — the 5 combat verbs + chorus comment

**Arena**
- `services/arena/manager.py` — match lifecycle, AXL+target+agent supervision
- `services/arena/api.py` — FastAPI + SSE
- `services/arena/event_bus.py` — typed event taxonomy
- `services/arena/workspace.py` — per-combatant writable target workspace

**Service entrypoints**
- `services/combatant/main.py` — combatant agent process
- `services/chorus/main.py` — chorus member process
- `services/target/main.py` — vulnerable FastAPI target

**UI**
- `apps/ui/src/scenes/ArenaScene.tsx` — battle scene, mirroring the reference image
- `apps/ui/src/components/EndpointHex.tsx` — animated attack-flow hex
- `apps/ui/src/components/BubbleLayer.tsx` — portrait-anchored speech bubbles
- `apps/ui/src/components/EnsRegistryPanel.tsx` — live on-chain status
- `apps/ui/src/state/store.ts` — event ingestion + UI state

## Run order

```
make bootstrap         # builds AXL, sets up venv + UI deps
cp .env.example .env   # fill in ANTHROPIC_API_KEY + ENS keys
make demo              # arena API on :8787, UI on :5173
```

POST to `/api/match/start` (or click "BEGIN MATCH" in the UI).

## Tests

```
make test                                   # unit + non-AXL integration
HOSTILE_MESH_RUN_AXL_TESTS=1 make test      # also spawns 2 real AXL nodes
```
