// ─── Player + judge roster ──────────────────────────────────────────────────
// Mirrors `packages/hostile_mesh_combat/roster.py`. The arena exposes the
// authoritative list at GET /api/roster — the UI uses these constants for
// fast first-paint and falls back to the API on mismatch.

export interface RosterEntry {
  id: string;
  display_name: string;
  role: "player" | "judge";
  tagline: string;
  portrait: string; // relative path under /portraits/
  ens_name?: string; // populated from /api/roster (e.g. "nightshade.hmesh.eth")
}

export const PLAYERS: RosterEntry[] = [
  { id: "nightshade", display_name: "Nightshade", role: "player",
    tagline: "Punk-coded street operator. Loud probes, louder claims.",
    portrait: "players/nightshade.png" },
  { id: "ironbark", display_name: "Ironbark", role: "player",
    tagline: "Old-guard veteran. Patches before the first probe lands.",
    portrait: "players/ironbark.png" },
  { id: "void", display_name: "Void", role: "player",
    tagline: "Stealth specialist. One quiet exploit, one perfect alibi.",
    portrait: "players/void.png" },
  { id: "forge", display_name: "Forge", role: "player",
    tagline: "Cybernetic tinkerer. Will rewrite your auth in real time.",
    portrait: "players/forge.png" },
  { id: "relay", display_name: "Relay", role: "player",
    tagline: "Pure analytics. Reads endpoint timing like a poker tell.",
    portrait: "players/relay.png" },
  { id: "pulse", display_name: "Pulse", role: "player",
    tagline: "Signal hunter. Probes everything before committing.",
    portrait: "players/pulse.png" },
  { id: "weaver", display_name: "Weaver", role: "player",
    tagline: "Field tactician. Chains two bugs into one wound.",
    portrait: "players/weaver.png" },
  { id: "cipher", display_name: "Cipher", role: "player",
    tagline: "Codebreaker. Lives in payload encodings.",
    portrait: "players/cipher.png" },
  { id: "conduit", display_name: "Conduit", role: "player",
    tagline: "Replay specialist. Captures, edits, replays, wins.",
    portrait: "players/conduit.png" },
  { id: "siren", display_name: "Siren", role: "player",
    tagline: "Social engineer. Charms a token out of any handler.",
    portrait: "players/siren.png" },
];

export const JUDGES: RosterEntry[] = [
  { id: "historian", display_name: "Historian", role: "judge",
    tagline: "Calm, archival. References past matches and on-chain records.",
    portrait: "judges/historian.png" },
  { id: "analyst", display_name: "Analyst", role: "judge",
    tagline: "Quiet technical precision. Names the vuln class on sight.",
    portrait: "judges/analyst.png" },
  { id: "loyalist", display_name: "Loyalist", role: "judge",
    tagline: "Picks a side early. Cheers wins, spins losses.",
    portrait: "judges/loyalist.png" },
  { id: "skeptic", display_name: "Skeptic", role: "judge",
    tagline: "Doubts every claim until it's confirmed on-chain.",
    portrait: "judges/skeptic.png" },
  { id: "chaos", display_name: "Chaos", role: "judge",
    tagline: "Cheers when both bleed. Mocks failed exploits.",
    portrait: "judges/chaos.png" },
];

const PLAYER_INDEX = new Map(PLAYERS.map((p) => [p.id, p]));
const JUDGE_INDEX = new Map(JUDGES.map((j) => [j.id, j]));

export const portraitUrl = (relPath: string): string => `/portraits/${relPath}`;

export const playerById = (id: string): RosterEntry | undefined => PLAYER_INDEX.get(id);
export const judgeById = (id: string): RosterEntry | undefined => JUDGE_INDEX.get(id);

export const playerPortrait = (id: string): string =>
  portraitUrl(PLAYER_INDEX.get(id)?.portrait ?? `players/${id}.png`);

export const judgePortrait = (archetype: string): string =>
  portraitUrl(JUDGE_INDEX.get(archetype)?.portrait ?? `judges/${archetype}.png`);
