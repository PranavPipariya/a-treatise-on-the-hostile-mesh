"""Arena FastAPI surface.

Three primary endpoints:

  POST /api/match/start          → start a match (returns initial state)
  GET  /api/match/{id}/state     → current state snapshot
  GET  /api/match/{id}/events    → SSE stream of ArenaEvent objects

  POST /api/exploit/verify       → called by combatants' `exploit` tool
  POST /api/patch                → called by combatants' `patch_self` tool
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from arena.event_bus import ArenaEventBus
from arena.manager import ArenaManager


def build_app() -> FastAPI:
    bus = ArenaEventBus()
    runtime_dir = Path(os.getenv("HOSTILE_MESH_AXL_RUNTIME_DIR", "./.axl")).resolve()
    match_state_dir = Path(".match-state").resolve()
    log_dir = Path(".logs").resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    match_state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    manager = ArenaManager(
        bus=bus,
        runtime_dir=runtime_dir,
        match_state_dir=match_state_dir,
        log_dir=log_dir,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        yield
        for match_id in list(manager.matches.keys()):
            await manager.shutdown_match(match_id)

    app = FastAPI(
        title="A Treatise on the Hostile Mesh — Arena",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.bus = bus
    app.state.manager = manager

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "matches": list(manager.matches.keys()),
            "ens_chain_available": manager.archive is not None,
        }

    @app.post("/api/match/start")
    async def start_match(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        combatants = body.get("combatants")
        try:
            state = await manager.start_match(combatants=combatants)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return state.to_dict()

    @app.get("/api/roster")
    async def roster() -> dict[str, list[dict[str, str]]]:
        from hostile_mesh_combat.roster import JUDGES, PLAYERS, to_dict
        parent = os.getenv("HOSTILE_MESH_ENS_PARENT", "").strip()

        def with_ens(entry):
            d = to_dict(entry)
            d["ens_name"] = f"{entry.id}.{parent}" if parent else ""
            return d

        return {
            "players": [with_ens(p) for p in PLAYERS],
            "judges": [with_ens(j) for j in JUDGES],
        }

    @app.get("/api/leaderboard")
    async def leaderboard() -> dict[str, Any]:
        """Aggregate every persisted match-state JSON into a per-agent ranking.

        Reads `.match-state/<match_id>/match.json` files (written by the
        arena's _persist_match_state at shutdown). Sums payouts in wei,
        win/loss/wound/patch counts. Returns the top combatants sorted by
        cumulative SepETH earned.
        """
        from hostile_mesh_combat.roster import PLAYERS, player_lookup

        parent = os.getenv("HOSTILE_MESH_ENS_PARENT", "").strip()
        agg: dict[str, dict[str, Any]] = {}
        for entry in PLAYERS:
            agg[entry.id] = {
                "agent_id": entry.id,
                "display_name": entry.display_name,
                "ens_name": f"{entry.id}.{parent}" if parent else "",
                "address": "",
                "portrait": entry.portrait,
                "total_wei": 0,
                "total_eth": "0",
                "matches_played": 0,
                "wins": 0,
                "losses": 0,
                "wounds_inflicted": 0,
                "wounds_taken": 0,
                "bugs_patched": 0,
                "last_match_ts": 0.0,
            }

        for match_dir in sorted(match_state_dir.iterdir()):
            if not match_dir.is_dir():
                continue
            mfile = match_dir / "match.json"
            if not mfile.is_file():
                continue
            try:
                m = json.loads(mfile.read_text())
            except Exception:
                continue
            combatants = m.get("combatants") or []
            scores = m.get("scores") or {}
            payouts = m.get("payouts") or []
            ts = m.get("finished_at") or m.get("started_at") or 0
            top_score = -1
            top_id = None
            for cid in combatants:
                board = scores.get(cid) or {}
                total = (
                    int(board.get("wounds_inflicted", 0))
                    - int(board.get("wounds_taken", 0))
                    + int(board.get("patches_applied", 0))
                    - int(board.get("patches_broken", 0))
                )
                if total > top_score:
                    top_score = total
                    top_id = cid
            for cid in combatants:
                if cid not in agg:
                    p = player_lookup(cid)
                    agg[cid] = {
                        "agent_id": cid,
                        "display_name": p.display_name if p else cid,
                        "ens_name": f"{cid}.{parent}" if parent else "",
                        "address": "",
                        "portrait": p.portrait if p else "",
                        "total_wei": 0,
                        "total_eth": "0",
                        "matches_played": 0,
                        "wins": 0,
                        "losses": 0,
                        "wounds_inflicted": 0,
                        "wounds_taken": 0,
                        "bugs_patched": 0,
                        "last_match_ts": 0.0,
                    }
                a = agg[cid]
                a["matches_played"] += 1
                if cid == top_id and top_score > 0:
                    a["wins"] += 1
                elif top_id and cid != top_id:
                    a["losses"] += 1
                board = scores.get(cid) or {}
                a["wounds_inflicted"] += int(board.get("wounds_inflicted", 0))
                a["wounds_taken"] += int(board.get("wounds_taken", 0))
                a["bugs_patched"] += int(board.get("patches_applied", 0))
                if ts and float(ts) > a["last_match_ts"]:
                    a["last_match_ts"] = float(ts)
            for p in payouts:
                cid = p.get("agent_id")
                if cid in agg:
                    agg[cid]["total_wei"] += int(p.get("wei", 0))
                    addr = p.get("address") or ""
                    if addr and not agg[cid]["address"]:
                        agg[cid]["address"] = addr

        rows = list(agg.values())
        for r in rows:
            wei = r["total_wei"]
            r["total_eth"] = f"{wei / 1e18:.6f}".rstrip("0").rstrip(".") if wei > 0 else "0"
            if r["address"]:
                r["etherscan_url"] = f"https://sepolia.etherscan.io/address/{r['address']}"
        rows.sort(key=lambda r: (-r["total_wei"], -r["wins"], -r["wounds_inflicted"]))
        return {"rows": rows[:20], "parent_ens": parent}

    @app.get("/api/match/{match_id}/state")
    async def match_state(match_id: str) -> dict[str, Any]:
        state = manager.matches.get(match_id)
        if not state:
            raise HTTPException(404, f"no such match: {match_id}")
        return state.to_dict()

    @app.get("/api/match/{match_id}/events")
    async def match_events(match_id: str, request: Request) -> EventSourceResponse:
        async def stream():
            async for event in bus.subscribe():
                if await request.is_disconnected():
                    break
                if event.match_id and event.match_id != match_id:
                    continue
                yield {
                    "event": event.type.value,
                    "data": json.dumps(event.to_dict()),
                }

        return EventSourceResponse(stream())

    @app.get("/api/events")
    async def all_events(request: Request) -> EventSourceResponse:
        async def stream():
            async for event in bus.subscribe():
                if await request.is_disconnected():
                    break
                yield {
                    "event": event.type.value,
                    "data": json.dumps(event.to_dict()),
                }

        return EventSourceResponse(stream())

    @app.post("/api/exploit/verify")
    async def exploit_verify(payload: dict[str, Any]) -> JSONResponse:
        required = {"match_id", "attacker", "defender", "method", "path", "claim", "signature"}
        missing = required - set(payload.keys())
        if missing:
            raise HTTPException(400, f"missing fields: {missing}")
        result = await manager.verify_exploit(
            match_id=payload["match_id"],
            attacker=payload["attacker"],
            defender=payload["defender"],
            method=payload["method"],
            path=payload["path"],
            headers=payload.get("headers", {}) or {},
            query=payload.get("query", {}) or {},
            body=payload.get("body"),
            claim=payload["claim"],
            signature=payload["signature"],
        )
        return JSONResponse(result)

    @app.post("/api/commentary/event")
    async def commentary_event(payload: dict[str, Any]) -> JSONResponse:
        """Generic event-relay endpoint used by tools that need to push a
        synthetic event onto the bus (e.g. the probe tool emitting
        combat.probe events for the play-by-play feed)."""
        from arena.event_bus import ArenaEvent, ArenaEventType
        import time as _time

        event_type = (payload.get("type") or "").strip()
        match_id = payload.get("match_id") or ""
        data = payload.get("data") or {}
        if not (event_type and match_id):
            raise HTTPException(400, "type and match_id required")
        try:
            kind = ArenaEventType(event_type)
        except ValueError:
            raise HTTPException(400, f"unknown event type: {event_type}")
        await bus.publish(
            ArenaEvent(type=kind, match_id=match_id, ts=_time.time(), data=data)
        )
        return JSONResponse({"ok": True})

    @app.post("/api/commentary/say")
    async def commentary_say(payload: dict[str, Any]) -> JSONResponse:
        """Generic 'speak' endpoint used by combatant + chorus processes to
        push a bubble straight onto the SSE stream.

        Body: { match_id, speaker, kind: "claim"|"comment", text, archetype? }
        kind="claim"  -> ArenaEventType.COMBATANT_CLAIM
        kind="comment"-> ArenaEventType.CHORUS_COMMENT
        """
        from arena.event_bus import ArenaEvent, ArenaEventType
        import time as _time

        text = (payload.get("text") or "").strip()
        match_id = payload.get("match_id") or ""
        speaker = payload.get("speaker") or ""
        kind = (payload.get("kind") or "claim").strip()
        if not (text and match_id and speaker):
            raise HTTPException(400, "match_id, speaker, text required")
        if len(text) > 220:
            text = text[:217].rstrip() + "…"

        event_type = (
            ArenaEventType.CHORUS_COMMENT if kind == "comment"
            else ArenaEventType.COMBATANT_CLAIM
        )
        data: dict[str, Any] = {
            "speaker": speaker,
            "sender": speaker,
            "text": text,
            "scripted": False,
            "source": payload.get("source", "agent"),
        }
        if kind == "comment":
            data["archetype"] = payload.get("archetype") or speaker.split(".")[0]
        await bus.publish(
            ArenaEvent(
                type=event_type,
                match_id=match_id,
                ts=_time.time(),
                data=data,
            )
        )
        return JSONResponse({"ok": True})

    @app.post("/api/patch")
    async def patch(payload: dict[str, Any]) -> JSONResponse:
        required = {"match_id", "agent_id", "file", "old", "new"}
        missing = required - set(payload.keys())
        if missing:
            raise HTTPException(400, f"missing fields: {missing}")
        result = await manager.apply_patch(
            match_id=payload["match_id"],
            agent_id=payload["agent_id"],
            file=payload["file"],
            old=payload["old"],
            new=payload["new"],
            rationale=payload.get("rationale", ""),
        )
        return JSONResponse(result)

    return app


__all__ = ["build_app"]
