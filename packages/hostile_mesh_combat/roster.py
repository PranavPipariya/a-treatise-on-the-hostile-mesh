"""Player + judge roster — canonical IDs, display names, and short taglines.

Single source of truth shared by the arena (for validation) and the UI (via
the ``GET /api/roster`` endpoint). Keep this list in sync with the portraits
under ``apps/ui/public/portraits/{players,judges}/<id>.png``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class RosterEntry:
    id: str
    display_name: str
    role: str  # "player" | "judge"
    tagline: str
    portrait: str  # relative path under /portraits/ in the UI


PLAYERS: tuple[RosterEntry, ...] = (
    RosterEntry("nightshade", "Nightshade", "player",
                "Punk-coded street operator. Loud probes, louder claims.",
                "players/nightshade.png"),
    RosterEntry("ironbark",   "Ironbark",   "player",
                "Old-guard veteran. Patches before the first probe lands.",
                "players/ironbark.png"),
    RosterEntry("void",        "Void",       "player",
                "Stealth specialist. One quiet exploit, one perfect alibi.",
                "players/void.png"),
    RosterEntry("forge",       "Forge",      "player",
                "Cybernetic tinkerer. Will rewrite your auth in real time.",
                "players/forge.png"),
    RosterEntry("relay",       "Relay",      "player",
                "Pure analytics. Reads endpoint timing like a poker tell.",
                "players/relay.png"),
    RosterEntry("pulse",       "Pulse",      "player",
                "Signal hunter. Probes everything before committing.",
                "players/pulse.png"),
    RosterEntry("weaver",      "Weaver",     "player",
                "Field tactician. Chains two bugs into one wound.",
                "players/weaver.png"),
    RosterEntry("cipher",      "Cipher",     "player",
                "Codebreaker. Lives in payload encodings.",
                "players/cipher.png"),
    RosterEntry("conduit",     "Conduit",    "player",
                "Replay specialist. Captures, edits, replays, wins.",
                "players/conduit.png"),
    RosterEntry("siren",       "Siren",      "player",
                "Social engineer. Charms a token out of any handler.",
                "players/siren.png"),
)


JUDGES: tuple[RosterEntry, ...] = (
    RosterEntry("historian",   "Historian",  "judge",
                "Calm, archival. References past matches and on-chain records.",
                "judges/historian.png"),
    RosterEntry("analyst",     "Analyst",    "judge",
                "Quiet technical precision. Names the vuln class on sight.",
                "judges/analyst.png"),
    RosterEntry("loyalist",    "Loyalist",   "judge",
                "Picks a side early. Cheers wins, spins losses.",
                "judges/loyalist.png"),
    RosterEntry("skeptic",     "Skeptic",    "judge",
                "Doubts every claim until it's confirmed on-chain.",
                "judges/skeptic.png"),
    RosterEntry("chaos",       "Chaos",      "judge",
                "Cheers when both bleed. Mocks failed exploits.",
                "judges/chaos.png"),
)


PLAYER_IDS: frozenset[str] = frozenset(p.id for p in PLAYERS)
JUDGE_IDS: frozenset[str] = frozenset(j.id for j in JUDGES)


def player_lookup(agent_id: str) -> RosterEntry | None:
    for p in PLAYERS:
        if p.id == agent_id:
            return p
    return None


def to_dict(entry: RosterEntry) -> dict:
    return asdict(entry)


__all__ = [
    "JUDGES",
    "JUDGE_IDS",
    "PLAYERS",
    "PLAYER_IDS",
    "RosterEntry",
    "player_lookup",
    "to_dict",
]
