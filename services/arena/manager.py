"""Match orchestrator.

Owns a single match's lifecycle: bug seeding, workspace materialisation,
target subprocess spawning, AXL node supervision, agent process spawning,
ENS archive bootstrapping, scoring, and graceful shutdown.

Process-tree per match::

    arena (this process)
      ├── axl supervisor
      │     ├── ./node hub
      │     ├── ./node combatant-A
      │     ├── ./node combatant-B
      │     └── ./node chorus-* × 5
      ├── target subprocess for combatant-A   (uvicorn services/target)
      ├── target subprocess for combatant-B   (uvicorn services/target)
      ├── combatant agent A                    (services/combatant)
      ├── combatant agent B                    (services/combatant)
      └── chorus agents × 5                    (services/chorus)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from arena.event_bus import ArenaEvent, ArenaEventBus, ArenaEventType
from arena.workspace import CombatantWorkspace, materialize_workspace
from hostile_mesh_axl.binary import ensure_binary
from hostile_mesh_axl.config import HubLayout, NodeSpec
from hostile_mesh_axl.supervisor import AxlNodeProcess, Supervisor
from hostile_mesh_combat.bug_bank import default_bank, seed_match
from hostile_mesh_combat.scoring import (
    Scoreboard,
    apply_failed_claim,
    apply_patch,
    apply_wound,
)
from hostile_mesh_combat.target_factory import build_target_service
from hostile_mesh_combat.types import ExploitClaim, ReplayRecord, Verdict
from hostile_mesh_combat.verifier import Verifier
from hostile_mesh_ens.archive import Archive, ArchiveWriteResult
from hostile_mesh_ens.chain import SepoliaChain
from hostile_mesh_ens.config import EnsConfig
from hostile_mesh_ens.signer import recover_signer
from hostile_mesh_ens.wallet import WalletManager

logger = logging.getLogger(__name__)


from hostile_mesh_combat.roster import PLAYER_IDS, JUDGE_IDS  # noqa: E402

DEFAULT_COMBATANT_IDS = ("nightshade", "ironbark")
CHORUS_ARCHETYPES = ("historian", "analyst", "loyalist", "skeptic", "chaos")


def _free_port(start: int) -> int:
    """Probe ports starting at ``start`` until one is unbound."""
    port = start
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


@dataclass
class MatchState:
    match_id: str
    parent_ens: str
    started_at: float
    duration_s: int
    combatants: list[str]
    chorus: list[str]
    seeded_bugs: dict[str, list[str]] = field(default_factory=dict)
    target_urls: dict[str, str] = field(default_factory=dict)
    scores: dict[str, Scoreboard] = field(default_factory=dict)
    workspaces: dict[str, CombatantWorkspace] = field(default_factory=dict)
    peer_ids: dict[str, str] = field(default_factory=dict)
    status: str = "opening"  # opening | running | finished | aborted
    counters: dict[str, int] = field(default_factory=dict)
    finished_at: float | None = None
    payouts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "parent_ens": self.parent_ens,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
            "combatants": self.combatants,
            "chorus": self.chorus,
            "seeded_bugs": self.seeded_bugs,
            "target_urls": self.target_urls,
            "peer_ids": self.peer_ids,
            "status": self.status,
            "scores": {k: v.__dict__ for k, v in self.scores.items()},
            "counters": dict(self.counters),
            "finished_at": self.finished_at,
            "payouts": list(self.payouts),
        }


@dataclass
class _SubprocessHandle:
    name: str
    process: subprocess.Popen[bytes]
    log_path: Path

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def terminate(self, timeout: float = 4.0) -> None:
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()


class ArenaManager:
    """Top-level orchestrator. One instance per arena process — manages a
    single in-flight match plus a directory of past matches.
    """

    def __init__(
        self,
        *,
        bus: ArenaEventBus,
        runtime_dir: Path,
        match_state_dir: Path,
        log_dir: Path,
    ) -> None:
        self._bus = bus
        self._runtime_dir = runtime_dir
        self._match_state_dir = match_state_dir
        self._log_dir = log_dir

        self.matches: dict[str, MatchState] = {}
        self._target_handles: dict[str, dict[str, _SubprocessHandle]] = {}
        self._agent_handles: dict[str, dict[str, _SubprocessHandle]] = {}
        self._supervisors: dict[str, Supervisor] = {}
        self._verifiers: dict[str, Verifier] = {}
        self._target_services: dict[str, dict[str, Any]] = {}

        self._ens_cfg = EnsConfig.from_env()
        self._chain: SepoliaChain | None = None
        self._wallets: WalletManager | None = None
        self._archive: Archive | None = None

        # Scripted commentator: subscribes to the same bus and emits
        # chorus.comment + combatant.claim events on every combat moment.
        # Started once for the lifetime of the arena process.
        from arena.commentary import ScriptedCommentator
        self._commentator = ScriptedCommentator(bus)
        self._commentator.start()

    # ─── public API ──────────────────────────────────────────────────────
    @property
    def archive(self) -> Archive | None:
        return self._archive

    async def ensure_chain(self) -> Archive | None:
        if self._archive is not None:
            return self._archive
        try:
            self._chain = SepoliaChain(self._ens_cfg)
            self._wallets = WalletManager(
                self._ens_cfg.keystore_dir,
                self._ens_cfg.keystore_passphrase or "demo-passphrase-please-change",
            )
            self._archive = Archive(self._ens_cfg, self._chain, self._wallets)
            return self._archive
        except Exception as exc:
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.ENS_NOT_CONFIGURED,
                    data={"reason": str(exc)},
                )
            )
            return None

    async def start_match(self, combatants: list[str] | None = None) -> MatchState:
        match_id = f"match-{uuid.uuid4().hex[:8]}"
        duration_s = int(os.getenv("HOSTILE_MESH_MATCH_DURATION_SECONDS", "180"))
        bugs_per = int(os.getenv("HOSTILE_MESH_BUGS_PER_COMBATANT", "4"))

        chosen = list(combatants) if combatants else list(DEFAULT_COMBATANT_IDS)
        if len(chosen) != 2:
            raise ValueError(f"need exactly 2 combatants, got {len(chosen)}: {chosen}")
        if chosen[0] == chosen[1]:
            raise ValueError("combatants must be distinct")
        for c in chosen:
            if c not in PLAYER_IDS:
                raise ValueError(f"unknown player id: {c}")

        state = MatchState(
            match_id=match_id,
            parent_ens=self._ens_cfg.parent_name,
            started_at=time.time(),
            duration_s=duration_s,
            combatants=chosen,
            chorus=[f"{a}.chorus" for a in CHORUS_ARCHETYPES],
            scores={c: Scoreboard() for c in chosen},
        )
        self.matches[match_id] = state

        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.MATCH_OPENING,
                match_id=match_id,
                data={
                    "parent_ens": state.parent_ens,
                    "duration_s": duration_s,
                    "combatants": chosen,
                },
            )
        )

        # 1) Seed bugs.
        seeded = seed_match(match_id, chosen, bugs_per_combatant=bugs_per)
        state.seeded_bugs = {c: [b.template.bug_id for b in v] for c, v in seeded.items()}
        for combatant, instances in seeded.items():
            for inst in instances:
                await self._bus.publish(
                    ArenaEvent(
                        ArenaEventType.BUG_SEEDED,
                        match_id=match_id,
                        data={
                            "combatant": combatant,
                            "bug_id": inst.template.bug_id,
                            "vuln_class": inst.template.vuln_class,
                            "difficulty": inst.template.difficulty,
                            "title": inst.template.title,
                            "endpoint": inst.template.affected_endpoint,
                        },
                    )
                )

        # 2) Materialise per-combatant workspaces + spawn target subprocesses.
        target_base = int(os.getenv("HOSTILE_MESH_TARGET_BASE_PORT", "8800"))
        port_cursor = target_base
        target_handles: dict[str, _SubprocessHandle] = {}
        in_proc_services: dict[str, Any] = {}
        for combatant in chosen:
            port = _free_port(port_cursor)
            port_cursor = port + 1
            ws = materialize_workspace(
                root=self._match_state_dir,
                match_id=match_id,
                combatant_id=combatant,
                bugs=seeded[combatant],
                target_port=port,
            )
            state.workspaces[combatant] = ws
            url, handle = await self._spawn_target(combatant, ws, port, match_id)
            state.target_urls[combatant] = url
            target_handles[combatant] = handle

            # Build an in-process mirror of the target service so the verifier
            # can replay against authoritative state. The live subprocess stays
            # the canonical service for combatants; this mirror tracks state
            # in lock-step via the request-log middleware.
            in_proc_services[combatant] = build_target_service(
                combatant, seeded[combatant]
            ).__dict__  # placeholder — replaced below

        self._target_handles[match_id] = target_handles

        # The verifier replays HTTP against the live target subprocess; this
        # gives us the *real* response and the real state mutations.
        self._verifiers[match_id] = Verifier(
            services={c: state.workspaces[c] for c in chosen}  # type: ignore[arg-type]
        )

        # 3) Spawn AXL nodes — hub + 2 combatants + 5 chorus.
        node_specs = [
            NodeSpec(agent_id="hub", is_hub=True),
            *[NodeSpec(agent_id=c) for c in chosen],
            *[NodeSpec(agent_id=f"{a}.chorus") for a in CHORUS_ARCHETYPES],
        ]
        binary = ensure_binary(self._runtime_dir / "axl")
        layout = HubLayout(
            runtime_dir=self._runtime_dir / "axl" / "nodes" / match_id,
            base_api_port=int(os.getenv("HOSTILE_MESH_AXL_BASE_API_PORT", "9100")),
            base_tcp_port=int(os.getenv("HOSTILE_MESH_AXL_BASE_TCP_PORT", "7100")),
            hub_listen_port=int(os.getenv("HOSTILE_MESH_AXL_HUB_LISTEN_PORT", "9001")),
        )
        configs = layout.materialize(node_specs)
        supervisor = Supervisor(binary, log_dir=self._log_dir / "axl" / match_id)
        try:
            processes = await supervisor.start_all(
                configs,
                on_node_ready=lambda node: self._bus.publish(
                    ArenaEvent(
                        ArenaEventType.NODE_READY,
                        match_id=match_id,
                        data={
                            "agent_id": node.config.agent_id,
                            "peer_id": node.peer_id,
                            "api_url": node.api_url,
                        },
                    )
                ),
            )
        except Exception as exc:
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.MATCH_ABORTED,
                    match_id=match_id,
                    data={"reason": f"axl supervisor failed: {exc}"},
                )
            )
            state.status = "aborted"
            await self.shutdown_match(match_id)
            raise

        self._supervisors[match_id] = supervisor
        state.peer_ids = {agent_id: proc.peer_id for agent_id, proc in processes.items()}

        # 4) Bootstrap ENS records (fire-and-forget; UI shows pending state).
        archive = await self.ensure_chain()
        if archive:
            asyncio.create_task(self._write_match_open(match_id, state, archive))

        # 5) Spawn agent processes.
        agent_handles: dict[str, _SubprocessHandle] = {}
        chorus_peers = {
            f"{a}.chorus": processes[f"{a}.chorus"].peer_id for a in CHORUS_ARCHETYPES
        }
        combatant_peers = {c: processes[c].peer_id for c in chosen}
        for combatant in chosen:
            opp = chosen[1] if combatant == chosen[0] else chosen[0]
            handle = self._spawn_combatant(
                match_id=match_id,
                agent_id=combatant,
                opponent_id=opp,
                workspace=state.workspaces[combatant].root,
                own_target_url=state.target_urls[combatant],
                opponent_url=state.target_urls[opp],
                axl_url=processes[combatant].api_url,
                own_peer_id=processes[combatant].peer_id,
                opponent_peer_id=processes[opp].peer_id,
                chorus_peers=chorus_peers,
                duration_s=duration_s,
                bug_count=bugs_per,
            )
            agent_handles[combatant] = handle

        for archetype in CHORUS_ARCHETYPES:
            agent_id = f"{archetype}.chorus"
            handle = self._spawn_chorus(
                match_id=match_id,
                agent_id=agent_id,
                archetype=archetype,
                axl_url=processes[agent_id].api_url,
                own_peer_id=processes[agent_id].peer_id,
                chorus_peers=chorus_peers,
                combatant_peers=combatant_peers,
                duration_s=duration_s,
            )
            agent_handles[agent_id] = handle

        self._agent_handles[match_id] = agent_handles

        state.status = "running"
        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.MATCH_STARTED,
                match_id=match_id,
                data=state.to_dict(),
            )
        )

        # 6) Schedule auto-shutdown at duration cap.
        asyncio.create_task(self._auto_finish(match_id, duration_s))
        return state

    async def shutdown_match(self, match_id: str) -> None:
        state = self.matches.get(match_id)
        if not state:
            return
        for handle in (self._agent_handles.get(match_id) or {}).values():
            handle.terminate()
        for handle in (self._target_handles.get(match_id) or {}).values():
            handle.terminate()
        sup = self._supervisors.get(match_id)
        if sup:
            await sup.shutdown()
        state.status = "finished"
        state.finished_at = time.time()
        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.MATCH_FINISHED,
                match_id=match_id,
                data=state.to_dict(),
            )
        )
        if self._archive:
            await self._archive.close_match(
                match_id,
                {c: s.total for c, s in state.scores.items()},
            )
            await self._settle_payouts(state)
        self._persist_match_state(state)

    BOUNTY_WOUND_WEI = 10**15        # 0.001 SepETH per verified wound
    BOUNTY_PATCH_WEI = 5 * 10**14    # 0.0005 SepETH per successful patch

    async def _settle_payouts(self, state: MatchState) -> None:
        """Send real Sepolia ETH from the registrar to each combatant's
        ENS-resolved address. Per-wound bounty + per-patch bonus.

        Each payout fires as its own asyncio task so they run in parallel;
        we await the gather so the persisted match-state JSON includes every
        tx hash. Total wall time ~1-3s (just send_raw_transaction; we don't
        wait for receipts).
        """
        archive = self._archive
        chain = self._chain
        if not archive or not chain:
            return

        async def _do(agent_id: str, wei: int, reason: str) -> None:
            ens_name = archive.name_for_agent(agent_id)
            try:
                addr = await archive.resolver.resolve_addr(ens_name)
            except Exception as exc:
                addr = None
                logger.warning("resolve_addr(%s) failed: %s", ens_name, exc)
            if not addr:
                await self._bus.publish(
                    ArenaEvent(
                        ArenaEventType.PAYOUT_FAILED,
                        match_id=state.match_id,
                        data={
                            "agent_id": agent_id,
                            "ens_name": ens_name,
                            "wei": wei,
                            "reason": "could not resolve ENS to address",
                        },
                    )
                )
                return
            try:
                tx_hash = await chain.send_eth(addr, wei)
            except Exception as exc:
                logger.warning("send_eth(%s, %s) failed: %s", addr, wei, exc)
                await self._bus.publish(
                    ArenaEvent(
                        ArenaEventType.PAYOUT_FAILED,
                        match_id=state.match_id,
                        data={
                            "agent_id": agent_id,
                            "ens_name": ens_name,
                            "address": addr,
                            "wei": wei,
                            "reason": str(exc),
                        },
                    )
                )
                return
            if not tx_hash.startswith("0x"):
                tx_hash = "0x" + tx_hash
            eth_str = f"{wei / 1e18:.6f}".rstrip("0").rstrip(".")
            record = {
                "agent_id": agent_id,
                "ens_name": ens_name,
                "address": addr,
                "wei": wei,
                "eth": eth_str,
                "tx_hash": tx_hash,
                "etherscan_url": f"https://sepolia.etherscan.io/tx/{tx_hash}",
                "reason": reason,
            }
            state.payouts.append(record)
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.PAYOUT,
                    match_id=state.match_id,
                    data=record,
                )
            )

        tasks: list[Any] = []
        for agent_id, board in state.scores.items():
            if board.wounds_inflicted > 0:
                wei = board.wounds_inflicted * self.BOUNTY_WOUND_WEI
                noun = "wound" if board.wounds_inflicted == 1 else "wounds"
                tasks.append(_do(agent_id, wei, f"{board.wounds_inflicted} {noun} × 0.001 ETH"))
            if board.patches_applied > 0:
                wei = board.patches_applied * self.BOUNTY_PATCH_WEI
                noun = "patch" if board.patches_applied == 1 else "patches"
                tasks.append(_do(agent_id, wei, f"{board.patches_applied} {noun} × 0.0005 ETH"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _persist_match_state(self, state: MatchState) -> None:
        """Snapshot the final match state to disk so the leaderboard endpoint
        and the post-match scene can read it after the in-memory state is gone.
        """
        try:
            path = self._match_state_dir / state.match_id / "match.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state.to_dict(), default=str, indent=2))
        except Exception as exc:
            logger.warning("failed to persist match state for %s: %s", state.match_id, exc)

    # ─── verifier path (called by api.py from POST /api/exploit/verify) ──
    async def verify_exploit(
        self,
        *,
        match_id: str,
        attacker: str,
        defender: str,
        method: str,
        path: str,
        headers: dict[str, str],
        query: dict[str, str],
        body: str | None,
        claim: dict[str, Any],
        signature: dict[str, Any],
    ) -> dict[str, Any]:
        state = self.matches[match_id]
        target_url = state.target_urls[defender]

        # Re-run the request against the live target so we measure real state.
        async with httpx.AsyncClient(base_url=target_url, timeout=10.0) as client:
            try:
                resp = await client.request(
                    method,
                    path,
                    params=query,
                    headers=headers or None,
                    content=body.encode() if body else None,
                )
                replay = ReplayRecord(
                    method=method,
                    path=path,
                    headers=headers or {},
                    query=query or {},
                    body=body.encode() if body else None,
                    status_code=resp.status_code,
                    response_body=resp.content,
                    response_headers=dict(resp.headers),
                )
            except httpx.HTTPError as exc:
                replay = ReplayRecord(
                    method=method,
                    path=path,
                    headers=headers or {},
                    query=query or {},
                    body=body.encode() if body else None,
                    status_code=599,
                    response_body=str(exc).encode(),
                    response_headers={},
                )

        # Reload the workspace bug modules to inspect the current (possibly
        # patched) verify() implementations against the current target state.
        verdict = await self._verify_against_workspace(
            match_id=match_id,
            defender=defender,
            replay=replay,
            claim=claim,
        )

        # Verify the signature against the agent's ENS-resolved address.
        sig_ok = recover_signer(
            signature.get("payload_canonical", ""), signature.get("signature", "")
        ).lower() == signature.get("signer", "").lower()

        if not sig_ok:
            verdict = Verdict(
                success=False,
                matched_bug_id=verdict.matched_bug_id,
                matched_bug_class=verdict.matched_bug_class,
                reason=f"signature did not recover to {signature.get('signer')}",
                evidence=verdict.evidence,
            )

        # Score + emit + archive.
        archive_status = "not_configured"
        archive_tx: str | None = None
        if verdict.success:
            difficulty = self._difficulty_for_bug(verdict.matched_bug_id or "")
            apply_wound(
                state.scores[attacker],
                state.scores[defender],
                difficulty=difficulty,
                bug_id=verdict.matched_bug_id or "unknown",
            )
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.EXPLOIT_VERIFIED,
                    match_id=match_id,
                    data={
                        "attacker": attacker,
                        "defender": defender,
                        "endpoint": claim.get("target_endpoint"),
                        "vuln_class": verdict.matched_bug_class,
                        "bug_id": verdict.matched_bug_id,
                        "evidence": verdict.evidence,
                    },
                )
            )
            arch_result = await self._record_event(
                match_id=match_id,
                kind="wound",
                signed=signature,
                verdict=verdict,
            )
            archive_status = arch_result.status
            archive_tx = arch_result.tx_hash
        else:
            apply_failed_claim(state.scores[attacker], claim_summary=claim.get("summary", ""))
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.EXPLOIT_FAILED,
                    match_id=match_id,
                    data={
                        "attacker": attacker,
                        "defender": defender,
                        "endpoint": claim.get("target_endpoint"),
                        "claim": claim,
                        "reason": verdict.reason,
                    },
                )
            )
            arch_result = await self._record_event(
                match_id=match_id,
                kind="failed_claim",
                signed=signature,
                verdict=verdict,
            )
            archive_status = arch_result.status
            archive_tx = arch_result.tx_hash

        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.SCORE_UPDATED,
                match_id=match_id,
                data={c: s.__dict__ for c, s in state.scores.items()},
            )
        )

        return {
            "verdict": {
                "success": verdict.success,
                "reason": verdict.reason,
                "matched_bug_id": verdict.matched_bug_id,
                "matched_bug_class": verdict.matched_bug_class,
                "evidence": verdict.evidence,
            },
            "replay_status": replay.status_code,
            "archive_status": archive_status,
            "archive_tx": archive_tx,
        }

    async def apply_patch(
        self,
        *,
        match_id: str,
        agent_id: str,
        file: str,
        old: str,
        new: str,
        rationale: str,
    ) -> dict[str, Any]:
        state = self.matches[match_id]
        ws = state.workspaces[agent_id]
        target = (ws.root / file).resolve()
        try:
            target.relative_to(ws.root.resolve())
        except ValueError:
            return {"ok": False, "reason": "patch escapes workspace"}

        if not target.is_file():
            return {"ok": False, "reason": f"no such file: {file}"}

        original = target.read_text()
        if original.count(old) != 1:
            return {"ok": False, "reason": "old substring not unique"}

        patched = original.replace(old, new, 1)
        backup = target.with_suffix(target.suffix + ".bak")
        target.rename(backup)
        try:
            target.write_text(patched)
        except OSError as exc:
            backup.rename(target)
            return {"ok": False, "reason": f"write failed: {exc}"}

        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.PATCH_SUBMITTED,
                match_id=match_id,
                data={
                    "agent_id": agent_id,
                    "file": file,
                    "rationale": rationale,
                    "diff_size": len(new) - len(old),
                },
            )
        )

        # Restart the target subprocess.
        ok = await self._restart_target(match_id, agent_id)
        if not ok:
            backup.rename(target)
            await self._restart_target(match_id, agent_id)
            apply_patch(state.scores[agent_id], difficulty="medium", bug_id=file, broke_service=True)
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.PATCH_BROKE_SERVICE,
                    match_id=match_id,
                    data={"agent_id": agent_id, "file": file},
                )
            )
            return {"ok": False, "reason": "patch broke the service; reverted"}

        # Re-run a smoke test (GET /health). If still OK, accept.
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{state.target_urls[agent_id]}/health")
                healthy = resp.status_code == 200
            except httpx.HTTPError:
                healthy = False

        if not healthy:
            backup.rename(target)
            await self._restart_target(match_id, agent_id)
            apply_patch(state.scores[agent_id], difficulty="medium", bug_id=file, broke_service=True)
            await self._bus.publish(
                ArenaEvent(
                    ArenaEventType.PATCH_BROKE_SERVICE,
                    match_id=match_id,
                    data={"agent_id": agent_id, "file": file},
                )
            )
            return {"ok": False, "reason": "service unhealthy after patch; reverted"}

        backup.unlink(missing_ok=True)

        # Try to figure out which bug the patch closed by matching the file
        # path's basename against known bug template module names.
        difficulty = "medium"
        bug_id = "unknown"
        for inst_id in state.seeded_bugs[agent_id]:
            if inst_id.split("_v")[0] in file:
                bug_id = inst_id
                tpl = default_bank().by_id.get(inst_id)
                if tpl:
                    difficulty = tpl.difficulty
                break

        apply_patch(state.scores[agent_id], difficulty=difficulty, bug_id=bug_id)
        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.PATCH_APPLIED,
                match_id=match_id,
                data={"agent_id": agent_id, "file": file, "bug_id": bug_id},
            )
        )
        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.SCORE_UPDATED,
                match_id=match_id,
                data={c: s.__dict__ for c, s in state.scores.items()},
            )
        )
        return {"ok": True, "bug_id": bug_id}

    # ─── plumbing ────────────────────────────────────────────────────────
    async def _verify_against_workspace(
        self,
        *,
        match_id: str,
        defender: str,
        replay: ReplayRecord,
        claim: dict[str, Any],
    ) -> Verdict:
        # Reload the bug modules from the defender's workspace so a patched
        # template's verify() (or absence of vulnerable handler) flows through.
        ws = self.matches[match_id].workspaces[defender]
        sys.path.insert(0, str(ws.root))
        try:
            # We can't trivially reload the same names — the bug modules under
            # workspace/bugs share filenames with the canonical ones. Use a
            # fresh import path under "workspace.<match>.<combatant>.bugs".
            import importlib.util

            verdicts: list[Verdict] = []
            for bug_id in self.matches[match_id].seeded_bugs[defender]:
                module_name = self._module_name_for_template(bug_id)
                path = ws.bugs_dir / f"{module_name}.py"
                if not path.is_file():
                    continue
                spec = importlib.util.spec_from_file_location(
                    f"workspace_{match_id}_{defender}_{module_name}", path
                )
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    continue
                tpl = getattr(mod, "TEMPLATE", None)
                if not tpl:
                    continue
                # The verifier walks the live target's state, but we only
                # have its ReplayRecord here. The bug template uses the
                # in-memory state of its own `apply()`-attached service —
                # which we don't have direct access to. Instead, rebuild a
                # mirror via build_target_service (no listening sockets).
                from hostile_mesh_combat.target_factory import build_target_service
                from hostile_mesh_combat.types import BugInstance

                mirror = build_target_service(
                    defender,
                    [BugInstance(template=tpl, seed_id=f"verify:{bug_id}")],
                )
                v = tpl.verify(replay, mirror.state)
                if v.success:
                    return v
                verdicts.append(v)
            if verdicts:
                # Surface the most informative non-success verdict.
                return max(verdicts, key=lambda v: len(v.reason))
            return Verdict(False, None, None, "no seeded bug verified the replay")
        finally:
            try:
                sys.path.remove(str(ws.root))
            except ValueError:
                pass

    @staticmethod
    def _module_name_for_template(bug_id: str) -> str:
        parts = bug_id.split("_")
        if parts and parts[-1].startswith("v") and parts[-1][1:].isdigit():
            return "_".join(parts[:-1])
        return bug_id

    @staticmethod
    def _difficulty_for_bug(bug_id: str) -> str:
        tpl = default_bank().by_id.get(bug_id)
        return tpl.difficulty if tpl else "easy"

    async def _spawn_target(
        self,
        combatant: str,
        ws: CombatantWorkspace,
        port: int,
        match_id: str,
    ) -> tuple[str, _SubprocessHandle]:
        log = self._log_dir / "targets" / match_id / f"{combatant}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOSTILE_MESH_TARGET_COMBATANT_ID"] = combatant
        env["HOSTILE_MESH_TARGET_PORT"] = str(port)
        env["HOSTILE_MESH_TARGET_BUGS_JSON"] = json.dumps(ws.bug_ids)
        env["HOSTILE_MESH_WORKSPACE"] = str(ws.root)
        env["PYTHONPATH"] = self._pythonpath()
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "target.main"],
            stdout=log.open("ab", buffering=0),
            stderr=subprocess.STDOUT,
            env=env,
        )
        url = f"http://127.0.0.1:{port}"
        await self._wait_for_health(url)
        await self._bus.publish(
            ArenaEvent(
                ArenaEventType.NODE_SPAWNED,
                match_id=match_id,
                data={"kind": "target", "combatant": combatant, "url": url},
            )
        )
        return url, _SubprocessHandle(name=f"target/{combatant}", process=proc, log_path=log)

    def _spawn_combatant(
        self,
        *,
        match_id: str,
        agent_id: str,
        opponent_id: str,
        workspace: Path,
        own_target_url: str,
        opponent_url: str,
        axl_url: str,
        own_peer_id: str,
        opponent_peer_id: str,
        chorus_peers: dict[str, str],
        duration_s: int,
        bug_count: int,
    ) -> _SubprocessHandle:
        log = self._log_dir / "agents" / match_id / f"{agent_id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "HOSTILE_MESH_AGENT_ID": agent_id,
                "HOSTILE_MESH_OPPONENT_ID": opponent_id,
                "HOSTILE_MESH_OWN_TARGET_URL": own_target_url,
                "HOSTILE_MESH_OPPONENT_URL": opponent_url,
                "HOSTILE_MESH_AXL_API_URL": axl_url,
                "HOSTILE_MESH_OWN_PEER_ID": own_peer_id,
                "HOSTILE_MESH_OPPONENT_PEER_ID": opponent_peer_id,
                "HOSTILE_MESH_CHORUS_PEERS_JSON": json.dumps(chorus_peers),
                "HOSTILE_MESH_WORKSPACE": str(workspace),
                "HOSTILE_MESH_MATCH_ID": match_id,
                "HOSTILE_MESH_MATCH_DURATION_SECONDS": str(duration_s),
                "HOSTILE_MESH_BUG_COUNT": str(bug_count),
                "HOSTILE_MESH_ARENA_VERIFY_URL": f"http://{os.getenv('HOSTILE_MESH_ARENA_HOST','127.0.0.1')}:{os.getenv('HOSTILE_MESH_ARENA_PORT','8787')}/api/exploit/verify",
                "HOSTILE_MESH_ARENA_PATCH_URL": f"http://{os.getenv('HOSTILE_MESH_ARENA_HOST','127.0.0.1')}:{os.getenv('HOSTILE_MESH_ARENA_PORT','8787')}/api/patch",
                "PYTHONPATH": self._pythonpath(),
            }
        )
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "combatant.main"],
            stdout=log.open("ab", buffering=0),
            stderr=subprocess.STDOUT,
            env=env,
        )
        return _SubprocessHandle(name=f"combatant/{agent_id}", process=proc, log_path=log)

    def _spawn_chorus(
        self,
        *,
        match_id: str,
        agent_id: str,
        archetype: str,
        axl_url: str,
        own_peer_id: str,
        chorus_peers: dict[str, str],
        combatant_peers: dict[str, str],
        duration_s: int,
    ) -> _SubprocessHandle:
        log = self._log_dir / "agents" / match_id / f"{agent_id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "HOSTILE_MESH_AGENT_ID": agent_id,
                "HOSTILE_MESH_ARCHETYPE": archetype,
                "HOSTILE_MESH_AXL_API_URL": axl_url,
                "HOSTILE_MESH_OWN_PEER_ID": own_peer_id,
                "HOSTILE_MESH_CHORUS_PEERS_JSON": json.dumps(chorus_peers),
                "HOSTILE_MESH_COMBATANT_PEERS_JSON": json.dumps(combatant_peers),
                "HOSTILE_MESH_MATCH_ID": match_id,
                "HOSTILE_MESH_MATCH_DURATION_SECONDS": str(duration_s),
                "PYTHONPATH": self._pythonpath(),
            }
        )
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "chorus.main"],
            stdout=log.open("ab", buffering=0),
            stderr=subprocess.STDOUT,
            env=env,
        )
        return _SubprocessHandle(name=f"chorus/{agent_id}", process=proc, log_path=log)

    async def _restart_target(self, match_id: str, combatant: str) -> bool:
        handle = self._target_handles[match_id][combatant]
        ws = self.matches[match_id].workspaces[combatant]
        url = self.matches[match_id].target_urls[combatant]
        port = int(url.rsplit(":", 1)[-1])
        handle.terminate()
        new_url, new_handle = await self._spawn_target(combatant, ws, port, match_id)
        self._target_handles[match_id][combatant] = new_handle
        self.matches[match_id].target_urls[combatant] = new_url
        return new_handle.alive

    async def _wait_for_health(self, url: str, timeout: float = 12.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient(timeout=2.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    resp = await client.get(f"{url}/health")
                    if resp.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        raise RuntimeError(f"target {url} never became healthy within {timeout}s")

    def _pythonpath(self) -> str:
        # Ensure subprocesses can import packages/* and services/*.
        repo = Path(__file__).resolve().parent.parent.parent
        parts = [
            str(repo / "packages"),
            str(repo / "services"),
            os.environ.get("PYTHONPATH", ""),
        ]
        return os.pathsep.join(p for p in parts if p)

    async def _auto_finish(self, match_id: str, duration_s: int) -> None:
        await asyncio.sleep(duration_s)
        if self.matches[match_id].status == "running":
            await self.shutdown_match(match_id)

    async def _write_match_open(
        self, match_id: str, state: MatchState, archive: Archive
    ) -> None:
        async def emit(write: ArchiveWriteResult, match_id: str) -> None:
            evt_type = {
                "submitted": ArenaEventType.ENS_WRITE_SUBMITTED,
                "confirmed": ArenaEventType.ENS_WRITE_CONFIRMED,
                "failed": ArenaEventType.ENS_WRITE_FAILED,
                "not_configured": ArenaEventType.ENS_NOT_CONFIGURED,
            }[write.status]
            await self._bus.publish(
                ArenaEvent(
                    evt_type,
                    match_id=match_id,
                    data={
                        "name": write.name,
                        "operation": write.operation,
                        "tx_hash": write.tx_hash,
                        "block": write.block_number,
                        "error": write.error,
                    },
                )
            )

        await emit(await archive.open_match(match_id, state.combatants), match_id)
        for combatant in state.combatants:
            await emit(
                await archive.register_agent(
                    combatant,
                    role="combatant",
                    peer_id=state.peer_ids.get(combatant, ""),
                    epoch=int(time.time()),
                ),
                match_id,
            )
        for archetype in CHORUS_ARCHETYPES:
            agent_id = f"{archetype}.chorus"
            await emit(
                await archive.register_agent(
                    agent_id,
                    role="chorus",
                    archetype=archetype,
                    peer_id=state.peer_ids.get(agent_id, ""),
                    epoch=int(time.time()),
                ),
                match_id,
            )

    async def _record_event(
        self,
        *,
        match_id: str,
        kind: str,
        signed: dict[str, Any],
        verdict: Verdict,
    ) -> ArchiveWriteResult:
        archive = await self.ensure_chain()
        if not archive:
            return ArchiveWriteResult("not_configured", "", "record_event")
        index = self.matches[match_id].counters.get(kind, 0) + 1
        self.matches[match_id].counters[kind] = index
        from hostile_mesh_ens.signer import SignedClaim

        signed_claim = SignedClaim(
            payload={},
            payload_canonical=signed.get("payload_canonical", ""),
            signature=signed.get("signature", ""),
            signer=signed.get("signer", ""),
        )
        result = await archive.record_event(
            match_id=match_id,
            kind=kind,
            index=index,
            signed=signed_claim,
            verdict="success" if verdict.success else "failed",
        )
        evt_type = {
            "submitted": ArenaEventType.ENS_WRITE_SUBMITTED,
            "confirmed": ArenaEventType.ENS_WRITE_CONFIRMED,
            "failed": ArenaEventType.ENS_WRITE_FAILED,
            "not_configured": ArenaEventType.ENS_NOT_CONFIGURED,
        }[result.status]
        await self._bus.publish(
            ArenaEvent(
                evt_type,
                match_id=match_id,
                data={
                    "name": result.name,
                    "operation": result.operation,
                    "tx_hash": result.tx_hash,
                    "block": result.block_number,
                    "error": result.error,
                    "kind": kind,
                },
            )
        )
        return result


__all__ = ["ArenaManager", "MatchState"]
