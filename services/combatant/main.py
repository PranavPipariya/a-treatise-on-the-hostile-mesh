"""Combatant agent process entrypoint.

Spawned by the arena once a match begins. Receives all configuration via
environment variables (process-isolation contract — no shared memory with
the arena), constructs its own AXL client, ENS archive, runtime session,
and Anthropic-backed orchestrator, then runs a single ``Orchestrator.run``
turn-loop until the match ends or its goal is achieved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from hostile_mesh_axl.client import AxlClient
from hostile_mesh_axl.mesh import (
    CHANNEL_CHORUS,
    CHANNEL_DUEL,
    CombatEnvelope,
    Mesh,
    MeshNode,
)
from hostile_mesh_axl.supervisor import AxlNodeProcess
from hostile_mesh_combat.agent_tools import CombatContext, build_combatant_toolbox
from hostile_mesh_ens.archive import Archive
from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.config import EnsConfig
from hostile_mesh_ens.wallet import WalletManager
from hostile_mesh_runtime.config import RuntimeConfig
from hostile_mesh_runtime.prompts import combatant_system_prompt
from hostile_mesh_runtime.runtime.events import AgentEventType
from hostile_mesh_runtime.runtime.orchestrator import Orchestrator
from hostile_mesh_runtime.runtime.session import Session
from hostile_mesh_runtime.tools.registry import ToolRegistry

logging.basicConfig(
    level=os.getenv("HOSTILE_MESH_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hostilemesh.combatant")


async def _build_solo_mesh(agent_id: str, axl_url: str, peer_id: str) -> Mesh:
    """Construct a Mesh that contains *only* this agent's own AXL node.

    The mesh's higher-level send/broadcast operations will route to
    arena-resolved peer IDs via the channel-membership API. We pre-load
    the membership lists from environment variables.
    """
    proc = AxlNodeProcess(
        config=type(  # tiny stand-in — combatant doesn't own the supervisor
            "FakeCfg",
            (),
            {"agent_id": agent_id, "is_hub": False, "api_url": axl_url, "config_path": Path("/tmp")},
        )(),
        process=None,  # type: ignore[arg-type]
        log_path=Path("/tmp/never"),
    )
    proc.peer_id = peer_id

    node = MeshNode(agent_id=agent_id, process=proc, client=AxlClient(axl_url))
    mesh = Mesh({agent_id: node})
    return mesh


async def main() -> int:
    agent_id = os.environ["HOSTILE_MESH_AGENT_ID"]
    opponent_id = os.environ["HOSTILE_MESH_OPPONENT_ID"]
    own_target_url = os.environ["HOSTILE_MESH_OWN_TARGET_URL"]
    opponent_url = os.environ["HOSTILE_MESH_OPPONENT_URL"]
    axl_url = os.environ["HOSTILE_MESH_AXL_API_URL"]
    arena_verify_url = os.environ["HOSTILE_MESH_ARENA_VERIFY_URL"]
    arena_patch_url = os.environ["HOSTILE_MESH_ARENA_PATCH_URL"]
    workspace = Path(os.environ["HOSTILE_MESH_WORKSPACE"]).resolve()
    match_id = os.environ["HOSTILE_MESH_MATCH_ID"]
    own_peer_id = os.environ.get("HOSTILE_MESH_OWN_PEER_ID", "")
    opponent_peer_id = os.environ.get("HOSTILE_MESH_OPPONENT_PEER_ID", "")
    chorus_peers = json.loads(os.environ.get("HOSTILE_MESH_CHORUS_PEERS_JSON", "{}"))
    bug_count = int(os.environ.get("HOSTILE_MESH_BUG_COUNT", "4"))
    duration_s = int(os.environ.get("HOSTILE_MESH_MATCH_DURATION_SECONDS", "180"))

    ens_cfg = EnsConfig.from_env()
    chain = SepoliaChain(ens_cfg)
    wallets = WalletManager(ens_cfg.keystore_dir, ens_cfg.keystore_passphrase or "demo-passphrase-please-change")
    archive = Archive(ens_cfg, chain, wallets)
    wallet = wallets.ensure(agent_id)
    ens_name = archive.name_for_agent(agent_id)
    opponent_ens = archive.name_for_agent(opponent_id)

    # Build a Mesh that knows about every peer the arena told us about.
    mesh = Mesh({})
    own_node = MeshNode(
        agent_id=agent_id,
        process=type("Stub", (), {"peer_id": own_peer_id, "api_url": axl_url})(),
        client=AxlClient(axl_url),
    )
    own_node.process.peer_id = own_peer_id  # type: ignore[attr-defined]
    mesh._nodes[agent_id] = own_node

    for peer_id_known in [opponent_peer_id, *chorus_peers.values()]:
        if not peer_id_known or peer_id_known == own_peer_id:
            continue
    # The combatant only needs `send`'s view of *recipient* peer IDs.
    # We register each known peer as a virtual MeshNode pointing at our own
    # AXL bridge (we send through our own bridge to their peer ID).
    for pid_agent, pid in [(opponent_id, opponent_peer_id), *chorus_peers.items()]:
        if not pid:
            continue
        stub_proc = type("Stub", (), {"peer_id": pid, "api_url": axl_url})()
        mesh._nodes[pid_agent] = MeshNode(
            agent_id=pid_agent,
            process=stub_proc,  # type: ignore[arg-type]
            client=AxlClient(axl_url),
        )

    mesh.set_channel_members(CHANNEL_DUEL, [agent_id, opponent_id])
    mesh.set_channel_members(
        CHANNEL_CHORUS, [agent_id, *list(chorus_peers.keys())]
    )

    await mesh.nodes[agent_id].start_recv_loop()

    ctx = CombatContext(
        agent_id=agent_id,
        role="combatant",
        archetype="",
        ens_name=ens_name,
        wallet=wallet,
        workspace=workspace,
        own_target_url=own_target_url,
        opponent_id=opponent_id,
        opponent_url=opponent_url,
        opponent_ens=opponent_ens,
        arena_verify_url=arena_verify_url,
        arena_patch_url=arena_patch_url,
        mesh=mesh,
        archive=archive,
        match_id=match_id,
    )

    config = RuntimeConfig.from_env(
        agent_id=agent_id,
        role="combatant",
        system_prompt=combatant_system_prompt(
            agent_id=agent_id,
            ens_name=ens_name,
            opponent_id=opponent_id,
            opponent_ens=opponent_ens,
            own_service_root=str(workspace),
            bug_count=bug_count,
            match_duration_seconds=duration_s,
        ),
        workspace=workspace,
    )

    registry = ToolRegistry()
    for tool in build_combatant_toolbox(ctx):
        registry.register(tool)
    session = Session.create(config, tools=registry)
    orchestrator = Orchestrator(session)

    if not config.llm_available:
        logger.warning(
            "combatant %s has no ANTHROPIC_API_KEY — agent will idle and emit a degraded notice",
            agent_id,
        )
        await mesh.broadcast(
            agent_id,
            CHANNEL_CHORUS,
            CombatEnvelope.new(
                channel=CHANNEL_CHORUS,
                kind="combatant_idle",
                sender=agent_id,
                sender_ens=ens_name,
                payload={"reason": "no ANTHROPIC_API_KEY"},
            ),
        )
        await asyncio.sleep(duration_s)
        return 0

    initial_brief = (
        f"Match {match_id} has begun. You are {agent_id} ({ens_name}). Your "
        f"opponent is {opponent_id} ({opponent_ens}) at {opponent_url}. Begin "
        f"by inspecting your own service to understand what's seeded against you, "
        f"then probe and exploit."
    )

    # Surface the model's natural-language reasoning as bubbles. Whenever the
    # orchestrator emits a complete chunk of text (the assistant's pre-tool
    # narration), we trim the first sentence and POST it to the arena's
    # commentary endpoint, which republishes it as a `combatant.claim` event.
    # Cost: zero — the LLM call already happened.
    arena_host = os.getenv("HOSTILE_MESH_ARENA_HOST", "127.0.0.1")
    arena_port = os.getenv("HOSTILE_MESH_ARENA_PORT", "8787")
    arena_say_url = f"http://{arena_host}:{arena_port}/api/commentary/say"
    arena_sse_url = f"http://{arena_host}:{arena_port}/api/match/{match_id}/events"
    import httpx

    # Background task that subscribes to the arena's SSE stream and injects
    # opponent claims + meaningful events into the combatant's conversation.
    # This is what lets the agent *respond by name* to what the opponent just
    # said or did — without it, each combatant runs blind to the other's
    # voice. Injection happens on `session.conversation` as user messages.
    # Buffered cross-talk: writing to session.conversation mid-turn corrupts
    # the assistant→tool_result pairing OpenAI requires (causes a 400 loop and
    # kills the agent). Push notable opponent events into a queue instead and
    # the outer loop folds them into the next cycle's nudge prompt.
    arena_inbox: asyncio.Queue[str] = asyncio.Queue()

    async def listen_to_arena() -> None:
        try:
            async with httpx.AsyncClient(timeout=None) as http:
                async with http.stream(
                    "GET", arena_sse_url, headers={"Accept": "text/event-stream"}
                ) as resp:
                    async for raw in resp.aiter_lines():
                        if not raw or not raw.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(raw[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        msg = _opponent_event_to_message(ev, agent_id, opponent_id)
                        if msg:
                            await arena_inbox.put(msg)
        except Exception:
            logger.debug("opponent-listener stream ended")

    def _drain_inbox() -> list[str]:
        msgs: list[str] = []
        while True:
            try:
                msgs.append(arena_inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        return msgs

    async def post_reasoning(text: str) -> None:
        snippet = _trim_to_punchy(text)
        if not snippet:
            return
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                await client.post(
                    arena_say_url,
                    json={
                        "match_id": match_id,
                        "speaker": agent_id,
                        "kind": "claim",
                        "text": snippet,
                        "source": "reasoning",
                    },
                )
        except Exception as exc:
            logger.debug("reasoning bubble post failed: %s", exc)

    listener_task = asyncio.create_task(listen_to_arena())

    # Match-clock-aware outer loop: keep relaunching the orchestrator with a
    # fresh "you still have N seconds — keep moving" nudge whenever it exits
    # early (model emitted a no-tool-calls final response, or hit max_turns).
    # Without this, combatants fall silent ~60-90s into a 180s match and the
    # play-by-play / chorus have nothing to react to.
    import time as _time
    match_start = _time.time()
    def _seconds_left() -> int:
        return max(0, duration_s - int(_time.time() - match_start))

    prompt = initial_brief
    cycle = 0
    try:
        while _seconds_left() > 8:
            cycle += 1
            async for ev in orchestrator.run(prompt):
                if ev.type is AgentEventType.TEXT_COMPLETE:
                    content = ev.data.get("content") or ""
                    if content.strip():
                        asyncio.create_task(post_reasoning(content))
                elif ev.type is AgentEventType.AGENT_ERROR:
                    logger.error("combatant %s: %s", agent_id, ev.data.get("error"))
                elif ev.type is AgentEventType.LOOP_DETECTED:
                    logger.warning("combatant %s loop: %s", agent_id, ev.data.get("reason"))
                if _seconds_left() <= 4:
                    break
            remaining = _seconds_left()
            if remaining <= 8:
                break
            inbox = _drain_inbox()
            inbox_block = ""
            if inbox:
                rendered = "\n".join(f"  • {m}" for m in inbox[-6:])
                inbox_block = (
                    f"\nSince your last cycle the arena saw:\n{rendered}\n"
                    f"React to the most interesting one BY NAME in your next line.\n"
                )
            prompt = (
                f"[arena clock] {remaining}s left on the match. The fight is NOT "
                f"over — the crowd is watching and you've gone quiet. Pick a fresh "
                f"endpoint on {opponent_id}, run a probe or commit an exploit RIGHT "
                f"NOW. Do not sit and reason — act, then narrate. One sharp line, "
                f"then a tool call. Cycle {cycle + 1}.{inbox_block}"
            )
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except (asyncio.CancelledError, BaseException):
            pass
        await mesh.stop()
        await session.close()

    return 0


def _opponent_event_to_message(
    ev: dict, my_id: str, opp_id: str
) -> str | None:
    """Translate an arena SSE event into a single-line user-message nudge.

    Only surfaces things the combatant *should* react to:
      • opponent's claim text (so they can taunt back)
      • opponent's verified wound (so they can react to being hit / acknowledge)
      • their own wound just landed (so they can crow about it)
    Returns None when the event isn't worth interrupting the agent over.
    """
    etype = ev.get("type", "")
    data = ev.get("data") or {}
    if etype == "combatant.claim":
        speaker = data.get("speaker")
        text = (data.get("text") or "").strip()
        if speaker == opp_id and text:
            return f"[{opp_id} just said] \"{text}\""
        return None
    if etype == "combat.exploit.verified":
        attacker = data.get("attacker")
        defender = data.get("defender")
        endpoint = data.get("endpoint", "")
        cls = data.get("vuln_class", "")
        if defender == my_id:
            return (
                f"[{attacker} just landed a {cls} wound on YOU at {endpoint}. "
                f"Patch it or counter-attack — and respond in voice.]"
            )
        if attacker == my_id:
            return f"[your {cls} exploit on {opp_id} at {endpoint} just landed. take a victory shot, then keep moving.]"
        return None
    if etype == "combat.exploit.failed":
        attacker = data.get("attacker")
        if attacker == opp_id:
            return f"[{opp_id} just whiffed an exploit. mock them and pivot.]"
        return None
    return None


def _trim_to_punchy(text: str) -> str:
    """Pick the most expressive single line out of the model's reasoning.

    Strategy: take the first non-empty line that looks like prose (drops
    bullet lists, numbered steps). Cap at 140 chars.
    """
    text = text.strip()
    if not text:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "#", "```", ">")):
            continue
        if line[:2] in {"1.", "2.", "3.", "4.", "5."}:
            continue
        # Take just the first sentence so bubbles stay short + punchy.
        for sep in (". ", "? ", "! "):
            if sep in line:
                line = line.split(sep, 1)[0] + sep.strip()
                break
        if len(line) > 140:
            line = line[:137].rstrip() + "…"
        return line
    return ""


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
