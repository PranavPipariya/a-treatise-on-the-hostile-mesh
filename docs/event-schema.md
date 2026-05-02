# Arena event schema

The arena → UI surface is a single SSE stream of typed `ArenaEvent`s.
Mirror of `services/arena/event_bus.py` for UI implementers and external
spectators.

Each frame:

```json
{
  "type": "<ArenaEventType>",
  "ts":   1735689600.123,
  "match_id": "match-1a2b3c4d",
  "data": { ... type-specific payload ... }
}
```

## Lifecycle

| type              | data                                              |
|-------------------|---------------------------------------------------|
| `match.opening`   | `{parent_ens, duration_s}`                        |
| `match.started`   | full `MatchState`                                 |
| `match.finished`  | full `MatchState`                                 |
| `match.aborted`   | `{reason}` + `MatchState` if reachable            |

## AXL

| type                  | data                                            |
|-----------------------|-------------------------------------------------|
| `axl.node.spawned`    | `{kind, agent_id, url}` (target/agent/AXL node) |
| `axl.node.ready`      | `{agent_id, peer_id, api_url}`                  |
| `axl.topology`        | `{nodes: [...]}`                                |

## ENS

`ens.write.submitted` is emitted as soon as the tx hash is back from
Sepolia; it's *upgraded in place* to `confirmed` or `failed` once the
receipt comes in (UI clients should match on `name+operation`).

| type                     | data                                                    |
|--------------------------|---------------------------------------------------------|
| `ens.write.submitted`    | `{name, operation, tx_hash, kind}`                      |
| `ens.write.confirmed`    | `{name, operation, tx_hash, block, kind}`               |
| `ens.write.failed`       | `{name, operation, tx_hash, error, kind}`               |
| `ens.not_configured`     | `{name, operation, error}` — degraded mode (no key set) |

## Combat

| type                       | data                                                                       |
|----------------------------|----------------------------------------------------------------------------|
| `bug.seeded`               | `{combatant, bug_id, vuln_class, difficulty, title, endpoint}`             |
| `combat.probe`             | `{attacker, endpoint, ...}`                                                |
| `combat.exploit.attempt`   | `{attacker, defender, endpoint, vuln_class, summary}`                      |
| `combat.exploit.verified`  | `{attacker, defender, endpoint, vuln_class, bug_id, evidence}`             |
| `combat.exploit.failed`    | `{attacker, defender, endpoint, claim, reason}`                            |
| `combat.patch.submitted`   | `{agent_id, file, rationale, diff_size}`                                   |
| `combat.patch.applied`     | `{agent_id, file, bug_id}`                                                 |
| `combat.patch.broke_service` | `{agent_id, file}`                                                       |
| `chorus.comment`           | `{archetype, text, signature, signer, target, index}`                      |
| `combatant.claim`          | `{claim_kind, text, target, signature, signer}`                            |
| `score.updated`            | `{<combatant_id>: Scoreboard, ...}`                                        |

## Match state

```ts
type MatchState = {
  match_id: string;
  parent_ens: string;
  started_at: number;          // unix seconds
  duration_s: number;          // 180 by default
  combatants: string[];        // ["nightshade", "ironbark"]
  chorus: string[];            // ["historian.chorus", ...]
  seeded_bugs: Record<string, string[]>;
  target_urls: Record<string, string>;
  peer_ids: Record<string, string>;
  status: "opening" | "running" | "finished" | "aborted";
  scores: Record<string, Scoreboard>;
  counters: Record<string, number>;
  finished_at: number | null;
};

type Scoreboard = {
  wounds_inflicted: number;
  wounds_taken: number;
  patches_applied: number;
  patches_broken: number;
  failed_claims: number;
  breakdown: Array<{
    kind: "wound" | "wound_taken" | "patch" | "patch_broke_service" | "failed_claim";
    delta: number;
    bug_id?: string;
    summary?: string;
  }>;
};
```

`total = wounds_inflicted - wounds_taken + patches_applied - patches_broken - failed_claims`
