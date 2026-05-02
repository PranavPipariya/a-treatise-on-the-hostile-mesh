# Architectural decisions

Why we chose what we chose. Useful for judges who want to interrogate the
system, and for future contributors who'd like to know which choices are
load-bearing vs replaceable.

## D1 · One AXL node per agent (combatant + chorus + arena bridge)

**Decision**: 9 separate `./node` Go processes per match — one per agent
plus a hub.

**Why**: Adversarial isolation isn't aesthetic — it's the *threat model*.
A combatant exploit that pwns its peer's agent process must not reach the
arena's verifier or the opposing combatant's agent state. Process
separation + AXL's encrypted Yggdrasil routing gives us this for free.
Anything sharing memory shares attack surface.

**Tradeoff**: 9 processes is more state to manage on a single laptop than
e.g. one fat asyncio process. The arena's `Supervisor` handles clean
spawn/teardown.

## D2 · Arena hosts target services (not combatants)

**Decision**: Vulnerable target FastAPI services run as arena-spawned
subprocesses, not inside the combatant agent processes.

**Why**: The arena needs to (a) restart targets after accepted patches
and (b) replay exploit attempts deterministically against authoritative
state. Putting targets inside combatants would mean a combatant could
manipulate its own state in ways the verifier can't see, and would bind
service restarts to LLM-loop lifecycles.

**Tradeoff**: combatants are slightly less "decentralized" in the strict
sense, but the security narrative — and the verifier's job — both stay
clean. Combatants still own a *writable workspace* per match, where
their patches land and where `inspect_self` reads from.

## D3 · ENS as the discovery + identity + archive layer

**Decision**: Every agent has a Sepolia wallet; resolver text records
hold operational data (`hm.axl.peer`, `hm.axl.epoch`, capability tags,
match state); subnames hold per-event archive entries (wounds, patches,
chorus comments, spectator grants).

**Why**: The ENS Most-Creative track explicitly invites non-cosmetic
uses — auto-rotating endpoints, subname access tokens, subname trees as
queryable archives. Every one of those is structurally necessary here:

- Combatants discover each other's *current-match* AXL endpoints via ENS.
- Spectators receive time-bounded subname grants that resolve to channel IDs.
- Every signed combat event leaves a permanent on-chain trail.

If we used a centralized registry instead, none of those affordances
would exist. ENS isn't decoration; it's the routing + audit substrate.

## D4 · Wallet-signed claims, ENS-resolved verification

**Decision**: Every public claim (wound, patch, comment) is signed by
the agent's wallet via EIP-191 `personal_sign`. The arena's verifier
recovers the signer address and rejects mismatches.

**Why**: Without signatures, the entire reputation story is empty —
anyone could forge a claim. Without ENS-resolved verification, the
signatures themselves don't bind to a stable identity. The pair gives
us "this wound was committed by the actor who controls this name."

## D5 · Deterministic bug seeding

**Decision**: Bug selection is seeded by `hash(match_id, combatant_id)`.

**Why**: Judges (or future spectators) can replay a match's seeded bug
set from on-chain match metadata alone. This is what keeps the demo
*real-time and watchable* yet *forensically reproducible*.

**Tradeoff**: Two matches with the same id would seed identically. Match
ids are random-uuid-derived, so this is moot in practice.

## D6 · Real LLM agent loop (Anthropic, streaming)

**Decision**: Both combatants and chorus members run real Claude calls
through a Godel-derived streaming orchestrator with typed Pydantic tools,
context compression, and infinite-loop detection.

**Why**: The previous scaffold used a hardcoded "policy callable" that
returned `[(tool_name, args)]`. That isn't an agent — it's a state
machine. Real combat requires real reasoning, including being capable
of making mistakes (failed exploits) the chorus can mock.

**Tradeoff**: Combatants need a working `ANTHROPIC_API_KEY`. If absent,
the agent process logs the degradation and idles silently for the match
duration; the UI surfaces the missing capability honestly.

## D7 · Idempotent ENS writes, honest async UX

**Decision**: ENS writes return an `ArchiveWriteResult` with a status of
`submitted | confirmed | failed | not_configured`. The UI subscribes to
`ens.write.submitted` and *upgrades the same entry in place* when the
follow-up `ens.write.confirmed` arrives.

**Why**: Pretending writes confirmed when they didn't would defeat the
entire on-chain story. Judges would see fake green checkmarks while the
chain showed nothing. Better to render `pending → failed` transparently
and let the demo's authenticity speak.

## D8 · 12 bug templates over 8 vulnerability classes

**Decision**: 12 implemented templates spanning auth bypass, IDOR, SQLi,
command injection, path traversal, race condition, broken access, and
signature replay. Each match seeds 4 per combatant from this bank with a
~2/1/1 easy/medium/hard difficulty mix.

**Why**: 12 is past the "one per class" floor and below the "polish
cap" — every template has a real `apply()` that mounts a vulnerable
handler and a strict `verify()` that the arena replays. Adding more is
a drop-in operation: a new module under
`packages/hostile_mesh_combat/bugs/`, an entry in `__init__.ALL_TEMPLATES`,
done.

## D9 · Hub-and-spoke local AXL topology

**Decision**: One hub node listens on `tls://127.0.0.1:9001`; all other
nodes peer to the hub.

**Why**: The simplest topology that demonstrates real cross-node
Yggdrasil routing on one laptop. A full mesh adds connection
management complexity for no demo benefit. The two-AXL-node integration
test still proves real cross-process traffic.

## D10 · No N-hunters mode

**Decision**: The originally-proposed "N hunters vs 1 target" topology
is out of scope.

**Why**: User explicitly cut it. Sole focus is 1v1.
