"""Chorus agent process entrypoint.

Each chorus archetype runs as its own OS process, subscribed to the arena's
SSE event stream, and reacts to noteworthy combat events with a one-shot
LLM call (cheap model, 60 tokens) in its archetype's voice. The reaction is
posted back to the arena's `/api/commentary/say` endpoint, which surfaces it
as a `chorus.comment` event on the bus → SSE → UI bubble.

This replaces the previous AXL-listener model, which was passive and almost
never fired because combatants rarely used the explicit `claim` tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import deque
from typing import Any

import httpx

from hostile_mesh_runtime.config import RuntimeConfig
from hostile_mesh_runtime.client.factory import make_client
from hostile_mesh_runtime.client.anthropic_client import StreamEventType
from hostile_mesh_runtime.prompts import chorus_system_prompt

logging.basicConfig(
    level=os.getenv("HOSTILE_MESH_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hostilemesh.chorus")


# Events worth a chorus reaction. Routine probes/attempts get filtered.
NOTEWORTHY = {
    "combat.probe",
    "combat.exploit.attempt",
    "combat.exploit.verified",
    "combat.exploit.failed",
    "combat.patch.applied",
    "combat.patch.submitted",
    "combat.patch.broke_service",
    "combatant.claim",
    "match.opening",
    "match.finished",
}

# Per-archetype rate limit — at most 1 LLM reaction per RATE_LIMIT_S seconds.
RATE_LIMIT_S = 3.0


async def main() -> int:
    agent_id = os.environ["HOSTILE_MESH_AGENT_ID"]
    archetype = os.environ["HOSTILE_MESH_ARCHETYPE"]
    match_id = os.environ["HOSTILE_MESH_MATCH_ID"]
    duration_s = int(os.environ.get("HOSTILE_MESH_MATCH_DURATION_SECONDS", "180"))
    arena_host = os.getenv("HOSTILE_MESH_ARENA_HOST", "127.0.0.1")
    arena_port = os.getenv("HOSTILE_MESH_ARENA_PORT", "8787")
    sse_url = f"http://{arena_host}:{arena_port}/api/match/{match_id}/events"
    say_url = f"http://{arena_host}:{arena_port}/api/commentary/say"

    ens_parent = os.getenv("HOSTILE_MESH_ENS_PARENT", "hostilemesh.eth")
    ens_name = f"{archetype}.chorus.{ens_parent}"

    # Lightweight runtime config — chorus uses gpt-4o-mini at 60 tokens / call.
    config = RuntimeConfig.from_env(
        agent_id=agent_id,
        role="chorus",
        system_prompt=chorus_system_prompt(
            agent_id=agent_id, ens_name=ens_name, archetype=archetype
        ),
        max_tokens=60,
        temperature=0.85,
        max_turns=1,
    )

    if not config.llm_available:
        logger.warning("chorus %s missing API key — going silent for the match", agent_id)
        await asyncio.sleep(duration_s)
        return 0

    client = make_client(config)
    last_emit_ts = 0.0
    deadline = asyncio.get_event_loop().time() + duration_s + 30  # small grace
    # Rolling buffer of the most recent peer-judge comments — fed back into
    # this archetype's LLM context so it can DEBATE / push back / agree with
    # what other judges just said. Capped to keep the prompt small.
    peer_history: deque[tuple[str, str]] = deque(maxlen=4)

    logger.info("chorus %s subscribed to %s", archetype, sse_url)

    async with httpx.AsyncClient(timeout=None) as http:
        try:
            async with http.stream(
                "GET", sse_url, headers={"Accept": "text/event-stream"}
            ) as resp:
                resp.raise_for_status()
                async for raw in resp.aiter_lines():
                    if asyncio.get_event_loop().time() > deadline:
                        break
                    if not raw or not raw.startswith("data:"):
                        continue
                    payload = raw[5:].strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")

                    # Track peers' commentary for the debate context.
                    if etype == "chorus.comment":
                        d = event.get("data") or {}
                        other = d.get("archetype")
                        text_peer = (d.get("text") or "").strip()
                        if other and other != archetype and text_peer and (d.get("source") == "llm"):
                            peer_history.append((other, text_peer))
                        # Don't react TO chorus comments — only to combat events.
                        continue

                    if etype not in NOTEWORTHY:
                        continue
                    if etype == "match.finished":
                        break

                    now = time.time()
                    if now - last_emit_ts < RATE_LIMIT_S:
                        continue

                    text = await _react(
                        client=client,
                        archetype=archetype,
                        event=event,
                        peer_history=list(peer_history),
                    )
                    if not text:
                        continue
                    last_emit_ts = now

                    try:
                        await http.post(
                            say_url,
                            json={
                                "match_id": match_id,
                                "speaker": agent_id,
                                "kind": "comment",
                                "archetype": archetype,
                                "text": text,
                                "source": "llm",
                            },
                            timeout=4.0,
                        )
                    except Exception as exc:
                        logger.debug("chorus post failed: %s", exc)
        except Exception:
            logger.exception("chorus stream loop crashed")
        finally:
            await client.close()

    return 0


# ─── LLM one-shot reaction ──────────────────────────────────────────────────
async def _react(
    *,
    client: Any,
    archetype: str,
    event: dict[str, Any],
    peer_history: list[tuple[str, str]] | None = None,
) -> str:
    etype = event.get("type", "")
    data = event.get("data", {}) or {}
    summary = _summarise_event(etype, data)

    peers_block = ""
    if peer_history:
        rendered = "\n".join(f"  {who.upper()}: \"{text}\"" for who, text in peer_history)
        peers_block = (
            f"\nWhat other judges just said:\n{rendered}\n\n"
            f"You may push back on a peer, agree with them, or build on their take "
            f"— OR ignore them and react purely to the event. Decide what's most fun. "
            f"If you reference a peer, address them BY NAME (e.g. 'Skeptic, you're wrong, ...').\n"
        )

    user_msg = (
        f"You are the {archetype.upper()} of the Hostile Mesh chorus. A new "
        f"combat event just happened:\n\n  {summary}\n"
        f"{peers_block}\n"
        f"React in *one* short line, in your voice. Maximum 90 characters. "
        f"No quotes, no preamble, just the line."
    )

    chunks: list[str] = []
    try:
        async for ev in client.stream(
            messages=[{"role": "user", "content": user_msg}],
            tools=None,
            system=None,
        ):
            if ev.type is StreamEventType.TEXT_DELTA and ev.text_delta:
                chunks.append(ev.text_delta.content)
            elif ev.type is StreamEventType.ERROR:
                return ""
            elif ev.type is StreamEventType.MESSAGE_COMPLETE:
                break
    except Exception as exc:
        logger.debug("chorus LLM call failed: %s", exc)
        return ""

    text = "".join(chunks).strip()
    text = re.sub(r'^["\']\s*|\s*["\']$', "", text)
    text = text.replace("\n", " ").strip()
    if len(text) > 120:
        text = text[:117].rstrip() + "…"
    return text


def _summarise_event(etype: str, data: dict[str, Any]) -> str:
    """Turn an arena event into a one-line context string for the LLM."""
    if etype == "combat.probe":
        return (
            f"{data.get('attacker','?')} probed {data.get('endpoint','?')} on "
            f"{data.get('defender','?')} — got {data.get('status_code','?')}"
        )
    if etype == "combat.exploit.attempt":
        return (
            f"{data.get('attacker','?')} just committed to an exploit at "
            f"{data.get('endpoint','?')} (claiming {data.get('vuln_class','?')})"
        )
    if etype == "combat.exploit.verified":
        return (
            f"{data.get('attacker','?')} landed a {data.get('vuln_class','?')} "
            f"wound on {data.get('defender','?')} via {data.get('endpoint','?')}"
        )
    if etype == "combat.exploit.failed":
        return (
            f"{data.get('attacker','?')} committed to an exploit at "
            f"{data.get('endpoint','?')} — verifier rejected it. "
            f"reason: {data.get('reason','?')}"
        )
    if etype == "combat.patch.submitted":
        return f"{data.get('agent_id','?')} is submitting a patch on {data.get('file','?')}"
    if etype == "combat.patch.applied":
        return (
            f"{data.get('agent_id','?')} patched {data.get('bug_id','?')} "
            f"in their service"
        )
    if etype == "combat.patch.broke_service":
        return f"{data.get('agent_id','?')} broke their own service with a bad patch"
    if etype == "combatant.claim":
        return f"{data.get('speaker','?')} just said: \"{(data.get('text','') or '')[:120]}\""
    if etype == "match.opening":
        return "the match is opening"
    if etype == "match.finished":
        return "the match just ended"
    return etype


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
