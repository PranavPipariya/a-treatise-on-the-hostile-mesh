"""Server-side scripted commentary.

The arena's chorus members and combatants do speak via real LLM calls — but
infrequently, leaving the battle screen quiet. This module subscribes to the
event bus and emits *templated* commentary events on every meaningful combat
moment, so the UI always has bubbles popping. Real LLM commentary layers on
top of these scripted lines unchanged.

Both scripted and real commentary flow through the same event types
(``combatant.claim`` and ``chorus.comment``) so the UI can render them
identically.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from arena.event_bus import ArenaEvent, ArenaEventBus, ArenaEventType
from hostile_mesh_combat.roster import player_lookup

logger = logging.getLogger(__name__)


# ─── Templates ──────────────────────────────────────────────────────────────
# Keys: { event_type → role → list[template] }
# `role` is "attacker" / "defender" for combatants, or one of the 5 archetypes.
# Format placeholders: {endpoint} {vuln_class} {attacker_name} {defender_name}
SCRIPTED: dict[str, dict[str, list[str]]] = {
    "combat.probe": {
        "attacker": [
            "checking {endpoint}",
            "probing {endpoint}",
            "let's see what {endpoint} returns",
            "knocking on {endpoint}",
        ],
    },
    "combat.exploit.attempt": {
        "attacker": [
            "going for it on {endpoint}",
            "committing to {endpoint}",
            "calling shot — {endpoint}",
            "this one lands.",
        ],
        "loyalist": ["here it comes!", "{attacker_name} commits."],
        "skeptic":  ["careful…", "we'll see if this verifies."],
        "chaos":    ["DO IT", "send it"],
    },
    "combat.exploit.verified": {
        "attacker": [
            "WOUND on {endpoint}!",
            "{vuln_class} landed.",
            "called it — {endpoint} is mine.",
            "first blood.",
            "told you.",
        ],
        "defender": [
            "shit, patching…",
            "won't land twice.",
            "regrouping.",
            "lucky shot.",
        ],
        "historian": [
            "third {vuln_class} wound this season.",
            "echoes match-007 — same class, same outcome.",
            "this pattern repeats.",
        ],
        "analyst":   [
            "{vuln_class} confirmed at {endpoint}.",
            "predicted: same class as the probe pattern.",
            "{vuln_class}, exactly as the probe trace suggested.",
        ],
        "loyalist":  [
            "ATTA {attacker_name}!",
            "called it — {attacker_name} eats.",
            "{attacker_name} is locked in tonight.",
        ],
        "skeptic":   [
            "…wait for the on-chain.",
            "I'll believe it when it confirms.",
            "save the celebration.",
        ],
        "chaos":     ["BLOOD", "MORE.", "yes yes yes"],
    },
    "combat.exploit.failed": {
        "attacker": [
            "missed.",
            "fine, regrouping.",
            "won't admit that one.",
        ],
        "defender": [
            "nice try.",
            "swing and a miss.",
            "you'll have to do better.",
        ],
        "historian": [
            "failed claims compound.",
            "this one stays in the archive.",
        ],
        "analyst":   [
            "wrong vuln class — replay didn't match.",
            "verifier rejected it.",
        ],
        "loyalist":  ["they'll get the next one.", "shake it off."],
        "skeptic":   ["told you.", "knew that wouldn't verify."],
        "chaos":     ["EMBARRASSING.", "lol", "MOCK THEM"],
    },
    "combat.patch.applied": {
        "defender": [
            "patched, that won't land twice.",
            "{vuln_class} closed.",
            "fixed it. moving on.",
            "one less hole.",
        ],
        "historian": [
            "{defender_name} patches under pressure.",
            "the archive notes a fix at {endpoint}.",
        ],
        "analyst":   [
            "patch closes {vuln_class}.",
            "service remains healthy post-restart.",
        ],
        "loyalist":  ["good defense!", "atta {defender_name}."],
        "skeptic":   ["might still leak elsewhere.", "one bug down, three to go."],
        "chaos":     ["BORING.", "where's the bleeding?"],
    },
    "combat.patch.broke_service": {
        "defender": [
            "shit, broke it.",
            "reverted. that wasn't supposed to do that.",
            "back to square one.",
        ],
        "loyalist":  ["it's fine, it's fine.", "{defender_name} will recover."],
        "skeptic":   ["told you.", "this is what happens when you patch under pressure."],
        "chaos":     ["SELF-OWN", "MAGNIFICENT", "they patched themselves into a wound"],
    },
}


# How long the scripted commentator waits between firing two consecutive
# bubbles, so they don't all collapse onto the same animation frame.
JITTER_MS = (60, 220)


# ─── Commentator ────────────────────────────────────────────────────────────
class ScriptedCommentator:
    """Subscribes to the event bus, emits templated chorus.comment +
    combatant.claim events for every combat moment.

    Decoupled from the chorus LLM agents — this runs in-process inside the
    arena, near-zero cost. LLM-driven chorus comments still arrive over AXL
    and layer on top through the same UI bubble path.
    """

    def __init__(self, bus: ArenaEventBus, *, rng: random.Random | None = None) -> None:
        self._bus = bus
        self._rng = rng or random.Random()
        self._last_emit_ts: float = 0.0
        # Per-event index counters (used for Bubble dedupe + as cheap unique ID)
        self._idx = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._loop(), name="commentary-loop")
        return self._task

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, BaseException):
                pass
            self._task = None

    async def _loop(self) -> None:
        async for event in self._bus.subscribe():
            try:
                await self._handle(event)
            except Exception:
                logger.exception("commentary handler raised")

    async def _handle(self, event: ArenaEvent) -> None:
        kind = event.type.value
        if kind not in SCRIPTED:
            return

        data = event.data
        ctx = self._build_context(kind, data)
        if ctx is None:
            return

        templates = SCRIPTED[kind]
        match_id = event.match_id

        # 1) Combatant lines (attacker + defender).
        for role in ("attacker", "defender"):
            speaker_id = ctx.get(role)
            if not speaker_id or role not in templates:
                continue
            text = self._render(templates[role], ctx)
            await self._delay()
            await self._emit_combatant_claim(
                match_id=match_id,
                speaker_id=speaker_id,
                text=text,
                kind=kind,
            )

        # 2) Chorus reactions. Pick 1–3 archetypes randomly so we don't fire
        # all five every time — keeps the commentary feeling reactive, not
        # robotic.
        chorus_archetypes = [a for a in ("historian", "analyst", "loyalist", "skeptic", "chaos") if a in templates]
        if chorus_archetypes:
            sample_size = min(len(chorus_archetypes), self._rng.randint(1, 3))
            chosen = self._rng.sample(chorus_archetypes, sample_size)
            for archetype in chosen:
                text = self._render(templates[archetype], ctx)
                await self._delay()
                await self._emit_chorus_comment(
                    match_id=match_id,
                    archetype=archetype,
                    text=text,
                    kind=kind,
                )

    def _build_context(self, kind: str, data: dict[str, Any]) -> dict[str, str] | None:
        """Translate event data into template variables.

        Different events carry slightly different keys — exploit events
        carry attacker/defender, patch events carry agent_id (the patcher)
        and need us to derive the attacker as the "opponent" notion.
        """
        ctx: dict[str, str] = {
            "endpoint": str(data.get("endpoint") or data.get("file") or ""),
            "vuln_class": str(data.get("vuln_class") or data.get("bug_id") or ""),
        }

        if kind in ("combat.probe", "combat.exploit.attempt", "combat.exploit.verified", "combat.exploit.failed"):
            attacker = str(data.get("attacker") or "")
            defender = str(data.get("defender") or "")
            if not attacker:
                return None
            ctx["attacker"] = attacker
            ctx["defender"] = defender
            ctx["attacker_name"] = self._display(attacker)
            ctx["defender_name"] = self._display(defender) if defender else ""
        elif kind in ("combat.patch.applied", "combat.patch.broke_service"):
            agent = str(data.get("agent_id") or "")
            if not agent:
                return None
            # The patcher acts as "defender" in template-speak.
            ctx["defender"] = agent
            ctx["defender_name"] = self._display(agent)
        else:
            return None

        return ctx

    def _display(self, agent_id: str) -> str:
        entry = player_lookup(agent_id)
        return entry.display_name if entry else agent_id

    def _render(self, choices: list[str], ctx: dict[str, str]) -> str:
        tpl = self._rng.choice(choices)
        try:
            return tpl.format(**ctx)
        except (KeyError, IndexError):
            return tpl

    async def _delay(self) -> None:
        # Randomized inter-bubble delay so multiple bubbles from one event
        # don't collide on the same frame in the UI.
        ms = self._rng.randint(*JITTER_MS)
        await asyncio.sleep(ms / 1000)

    async def _emit_combatant_claim(
        self, *, match_id: str, speaker_id: str, text: str, kind: str
    ) -> None:
        self._idx += 1
        await self._bus.publish(
            ArenaEvent(
                type=ArenaEventType.COMBATANT_CLAIM,
                match_id=match_id,
                ts=time.time(),
                data={
                    "speaker": speaker_id,
                    "sender": speaker_id,
                    "claim_kind": kind,
                    "text": text,
                    "scripted": True,
                    "index": self._idx,
                },
            )
        )

    async def _emit_chorus_comment(
        self, *, match_id: str, archetype: str, text: str, kind: str
    ) -> None:
        self._idx += 1
        await self._bus.publish(
            ArenaEvent(
                type=ArenaEventType.CHORUS_COMMENT,
                match_id=match_id,
                ts=time.time(),
                data={
                    "archetype": archetype,
                    "speaker": f"{archetype}.chorus",
                    "text": text,
                    "scripted": True,
                    "index": self._idx,
                    "trigger_kind": kind,
                },
            )
        )


__all__ = ["ScriptedCommentator", "SCRIPTED"]
