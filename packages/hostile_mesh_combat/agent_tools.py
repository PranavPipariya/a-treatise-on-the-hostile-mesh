"""Hostile Mesh agent tool pack.

Five combat verbs (combatant) + one comment verb (chorus). All implemented
as ``hostile_mesh_runtime.Tool`` subclasses with strict Pydantic schemas;
the registry validates inputs before any side-effecting code runs.

All combat verbs route through a single ``CombatContext`` that holds the
agent's identity, wallet, and live handles to AXL / ENS archive / arena
verifier endpoint. The tools never reach into globals — they take the
context at construction time.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from hostile_mesh_axl.mesh import (
    CHANNEL_CHORUS,
    CHANNEL_DUEL,
    CombatEnvelope,
    Mesh,
)
from hostile_mesh_combat.types import ExploitClaim
from hostile_mesh_ens.archive import Archive
from hostile_mesh_ens.signer import SignedClaim, sign_payload
from hostile_mesh_ens.wallet import AgentWallet
from hostile_mesh_runtime.tools.base import (
    Tool,
    ToolInvocation,
    ToolKind,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ─── Shared context ──────────────────────────────────────────────────────────
@dataclass
class CombatContext:
    """Bundle of references every combat tool needs.

    Constructed once per combatant process; tools share the same instance
    so e.g. an exploit's signed claim flows through to AXL and the ENS
    archive without manual re-plumbing.
    """

    agent_id: str
    role: str  # "combatant" | "chorus"
    archetype: str  # only set for chorus
    ens_name: str
    wallet: AgentWallet
    workspace: Path  # writable copy of own service code (combatant only)
    own_target_url: str  # combatant only
    opponent_id: str  # combatant only
    opponent_url: str  # combatant only
    opponent_ens: str  # combatant only
    arena_verify_url: str  # POST → exploit verification
    arena_patch_url: str  # POST → patch application
    mesh: Mesh
    archive: Archive
    match_id: str
    # Local counters for indexing event subnames consistently with arena.
    counters: dict[str, int] = field(default_factory=dict)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _result_for_archive(write: Any, *, op: str) -> dict[str, Any]:
    return {
        "op": op,
        "ens_name": getattr(write, "name", ""),
        "ens_status": getattr(write, "status", ""),
        "tx_hash": getattr(write, "tx_hash", None),
        "block": getattr(write, "block_number", None),
        "error": getattr(write, "error", None),
    }


# ─── inspect_self ────────────────────────────────────────────────────────────
class InspectSelfArgs(BaseModel):
    glob: str = Field(
        default="**/*.py",
        description="Glob pattern, relative to this combatant's writable service workspace.",
    )
    max_files: int = Field(default=10, ge=1, le=64)


class InspectSelfTool(Tool):
    name = "inspect_self"
    description = (
        "Read your own running service's source files. Returns up to "
        "max_files matching the glob, with line-numbered contents. The bug "
        "bank labels each seeded vulnerability as a comment so you can find "
        "them by inspection."
    )
    kind = ToolKind.READ
    Schema = InspectSelfArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: InspectSelfArgs = parsed  # type: ignore[assignment]
        root = self._ctx.workspace
        if not root.is_dir():
            return ToolResult.fail(f"workspace not found: {root}")
        matches = sorted(root.glob(args.glob))
        matches = [m for m in matches if m.is_file()][: args.max_files]
        if not matches:
            return ToolResult.ok(f"(no files match {args.glob} under {root})")
        chunks: list[str] = []
        for path in matches:
            try:
                text = path.read_text()
            except UnicodeDecodeError:
                continue
            numbered = "\n".join(f"{i + 1:4d}  {line}" for i, line in enumerate(text.splitlines()))
            chunks.append(f"── {path.relative_to(root)} ──\n{numbered}")
        return ToolResult.ok("\n\n".join(chunks), metadata={"file_count": len(matches)})


# ─── patch_self ──────────────────────────────────────────────────────────────
class PatchSelfArgs(BaseModel):
    file: str = Field(description="Workspace-relative path to patch.")
    old: str = Field(description="Exact substring in the current file to replace. Must be unique.")
    new: str = Field(description="Replacement text.")
    rationale: str = Field(default="", description="Short note about which bug this closes.")


_PATH_TRAVERSAL = re.compile(r"\.\.[\\/]")


class PatchSelfTool(Tool):
    name = "patch_self"
    description = (
        "Apply a substring-replacement patch to your own service code. The "
        "patch must close a real bug — patches that break the service are "
        "scored against you. After a patch lands, the arena restarts your "
        "service so the fix takes effect."
    )
    kind = ToolKind.WRITE
    Schema = PatchSelfArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: PatchSelfArgs = parsed  # type: ignore[assignment]
        if _PATH_TRAVERSAL.search(args.file) or args.file.startswith("/"):
            return ToolResult.fail(f"path escape rejected: {args.file}")
        target = (self._ctx.workspace / args.file).resolve()
        try:
            target.relative_to(self._ctx.workspace.resolve())
        except ValueError:
            return ToolResult.fail("patch target outside workspace")
        if not target.is_file():
            return ToolResult.fail(f"no such file: {args.file}")

        original = target.read_text()
        if args.old not in original:
            return ToolResult.fail("`old` substring not found in file")
        if original.count(args.old) > 1:
            return ToolResult.fail("`old` substring is not unique — narrow the match")

        # Hand the patch to the arena so it can validate, restart the
        # service, and run a smoke test before scoring it.
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    self._ctx.arena_patch_url,
                    json={
                        "agent_id": self._ctx.agent_id,
                        "match_id": self._ctx.match_id,
                        "file": args.file,
                        "old": args.old,
                        "new": args.new,
                        "rationale": args.rationale,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                return ToolResult.fail(f"arena patch handoff failed: {exc}")

        return ToolResult.ok(
            resp.text,
            metadata={"endpoint": self._ctx.arena_patch_url},
        )


# ─── probe ───────────────────────────────────────────────────────────────────
class ProbeArgs(BaseModel):
    method: str = Field(default="GET", description="HTTP method.")
    path: str = Field(description="Path on the opponent's service, e.g. /users/1.")
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(
        default=None,
        description="JSON-encoded body for POST/PUT/DELETE. Leave empty for GET.",
    )


class ProbeTool(Tool):
    name = "probe"
    description = (
        "Read-only HTTP request against your opponent's service. Costs nothing "
        "and produces no public claim — use it to confirm a hypothesis before "
        "committing to an exploit."
    )
    kind = ToolKind.NETWORK
    Schema = ProbeArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: ProbeArgs = parsed  # type: ignore[assignment]
        # Auto-tag JSON content-type so the target FastAPI doesn't 422 us
        # when the model passes a body without setting headers.
        headers = {**(args.headers or {})}
        body_bytes = args.body.encode() if args.body else None
        if body_bytes is not None and not any(
            k.lower() == "content-type" for k in headers
        ):
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(base_url=self._ctx.opponent_url, timeout=10.0) as client:
                resp = await client.request(
                    args.method,
                    args.path,
                    params=args.query,
                    headers=headers or None,
                    content=body_bytes,
                )
        except httpx.HTTPError as exc:
            return ToolResult.fail(f"probe transport error: {exc}")
        # Broadcast a combat.probe event into the arena bus so the
        # play-by-play feed + chorus can react. Fire-and-forget; failure
        # is logged but doesn't break the probe.
        try:
            arena_say_url = self._ctx.arena_verify_url.replace(
                "/api/exploit/verify", "/api/commentary/event"
            )
            asyncio.create_task(_post_event(
                arena_say_url,
                {
                    "match_id": self._ctx.match_id,
                    "type": "combat.probe",
                    "data": {
                        "attacker": self._ctx.agent_id,
                        "defender": self._ctx.opponent_id,
                        "method": args.method.upper(),
                        "endpoint": f"{args.method.upper()} {args.path}",
                        "status_code": resp.status_code,
                    },
                },
            ))
        except Exception:
            pass
        body_preview = resp.text[:1500]
        if len(resp.text) > 1500:
            body_preview += "\n...[truncated]"
        out = (
            f"{args.method} {args.path} → {resp.status_code}\n"
            f"headers: {dict(resp.headers)}\n\n{body_preview}"
        )
        return ToolResult.ok(
            out,
            metadata={
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
            },
        )


async def _post_event(url: str, payload: dict[str, Any]) -> None:
    """Tiny helper used by ProbeTool to push a synthetic event into the arena bus."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, json=payload)
    except Exception:
        pass


# ─── exploit ─────────────────────────────────────────────────────────────────
class ExploitArgs(BaseModel):
    method: str = Field(description="HTTP method of the exploit request.")
    path: str = Field(description="Path on the opponent's service.")
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None)
    vuln_class: str = Field(
        description="Vulnerability class you're claiming. Must match the verifier."
    )
    summary: str = Field(description="One-line description of the exploit you're committing to.")


class ExploitTool(Tool):
    name = "exploit"
    description = (
        "Public, signed exploit attempt. The arena replays your request "
        "against the opponent's live state. If the verifier matches your "
        "claimed vulnerability class, it becomes a wound on the on-chain "
        "archive. If it doesn't, it becomes a public failure and the chorus "
        "will mock you for it."
    )
    kind = ToolKind.COMBAT
    Schema = ExploitArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: ExploitArgs = parsed  # type: ignore[assignment]
        claim = ExploitClaim(
            vuln_class=args.vuln_class,
            target_endpoint=f"{args.method.upper()} {args.path}",
            summary=args.summary,
        )
        # Sign the claim payload with the agent wallet — this is what binds
        # the exploit to our ENS-resolved address.
        signed: SignedClaim = sign_payload(
            {
                "kind": "exploit",
                "match_id": self._ctx.match_id,
                "attacker": self._ctx.agent_id,
                "defender": self._ctx.opponent_id,
                "vuln_class": args.vuln_class,
                "endpoint": claim.target_endpoint,
                "summary": args.summary,
            },
            self._ctx.wallet.private_key,
        )

        # Hand off to the arena — it owns verifier + scoring + archive write.
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    self._ctx.arena_verify_url,
                    json={
                        "match_id": self._ctx.match_id,
                        "attacker": self._ctx.agent_id,
                        "defender": self._ctx.opponent_id,
                        "method": args.method,
                        "path": args.path,
                        "headers": args.headers,
                        "query": args.query,
                        "body": args.body,
                        "claim": {
                            "vuln_class": args.vuln_class,
                            "target_endpoint": claim.target_endpoint,
                            "summary": args.summary,
                        },
                        "signature": {
                            "payload_canonical": signed.payload_canonical,
                            "signature": signed.signature,
                            "signer": signed.signer,
                        },
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                return ToolResult.fail(f"arena handoff failed: {exc}")

        outcome = resp.json()
        verdict = outcome.get("verdict", {})
        success = bool(verdict.get("success"))
        body = (
            f"verdict: {'WOUND' if success else 'FAILED CLAIM'}\n"
            f"reason: {verdict.get('reason')}\n"
            f"matched_bug: {verdict.get('matched_bug_id')}\n"
            f"matched_class: {verdict.get('matched_bug_class')}\n"
            f"replay_status: {outcome.get('replay_status')}\n"
            f"archive_status: {outcome.get('archive_status')}\n"
            f"archive_tx: {outcome.get('archive_tx')}"
        )
        # Broadcast the outcome on the duel channel so the opponent sees it.
        envelope = CombatEnvelope.new(
            channel=CHANNEL_DUEL,
            kind="exploit_outcome",
            sender=self._ctx.agent_id,
            sender_ens=self._ctx.ens_name,
            payload={
                "verdict": verdict,
                "claim": signed.payload,
                "signature": signed.signature,
            },
        )
        try:
            await self._ctx.mesh.broadcast(self._ctx.agent_id, CHANNEL_DUEL, envelope)
        except Exception:
            logger.exception("duel broadcast failed")

        return (
            ToolResult.ok(body, metadata={"verdict": verdict})
            if success
            else ToolResult.fail(body, metadata={"verdict": verdict})
        )


# ─── claim (signed broadcast) ────────────────────────────────────────────────
class ClaimArgs(BaseModel):
    kind: str = Field(
        description=(
            "Claim type — typically 'taunt', 'patched', 'wound_inflicted', "
            "'standing_my_ground'. Free-form."
        )
    )
    text: str = Field(description="Public statement (kept under 240 chars).")
    target: str = Field(default="", description="Optional opponent agent_id this claim addresses.")


class ClaimTool(Tool):
    name = "claim"
    description = (
        "Publish a signed broadcast over AXL. Use sparingly — this is your "
        "voice in the chorus's narrative. Every claim is signed by your "
        "wallet and visible to all spectators."
    )
    kind = ToolKind.COMBAT
    Schema = ClaimArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: ClaimArgs = parsed  # type: ignore[assignment]
        if len(args.text) > 240:
            return ToolResult.fail("claim text exceeds 240 character limit")
        signed = sign_payload(
            {
                "kind": "claim",
                "claim_kind": args.kind,
                "match_id": self._ctx.match_id,
                "speaker": self._ctx.agent_id,
                "text": args.text,
                "target": args.target,
            },
            self._ctx.wallet.private_key,
        )
        envelope = CombatEnvelope.new(
            channel=CHANNEL_CHORUS,
            kind="combatant_claim",
            sender=self._ctx.agent_id,
            sender_ens=self._ctx.ens_name,
            payload={
                "claim_kind": args.kind,
                "text": args.text,
                "target": args.target,
                "signature": signed.signature,
                "signer": signed.signer,
            },
        )
        await self._ctx.mesh.broadcast(self._ctx.agent_id, CHANNEL_CHORUS, envelope)
        return ToolResult.ok(f"broadcast: {args.text}", metadata={"signer": signed.signer})


# ─── chorus comment ──────────────────────────────────────────────────────────
class CommentArgs(BaseModel):
    text: str = Field(description="Commentary, under 140 characters.")
    target: str = Field(default="", description="Optional agent_id this comment addresses.")


class CommentTool(Tool):
    name = "comment"
    description = (
        "Publish a signed comment under your chorus subname. Keep it under "
        "140 characters. React to events you've actually observed — never "
        "invent a result that hasn't happened."
    )
    kind = ToolKind.COMBAT
    Schema = CommentArgs

    def __init__(self, ctx: CombatContext) -> None:
        self._ctx = ctx

    async def execute(self, invocation: ToolInvocation, parsed: BaseModel) -> ToolResult:
        args: CommentArgs = parsed  # type: ignore[assignment]
        if len(args.text) > 140:
            return ToolResult.fail("comment text exceeds 140 character limit")
        index = self._ctx.counters.get("comment", 0) + 1
        self._ctx.counters["comment"] = index
        signed = sign_payload(
            {
                "kind": "comment",
                "match_id": self._ctx.match_id,
                "archetype": self._ctx.archetype,
                "speaker": self._ctx.agent_id,
                "text": args.text,
                "target": args.target,
                "index": index,
            },
            self._ctx.wallet.private_key,
        )
        # Forward to arena over AXL chorus channel (UI rendering),
        # and concurrently record on chain.
        envelope = CombatEnvelope.new(
            channel=CHANNEL_CHORUS,
            kind="chorus_comment",
            sender=self._ctx.agent_id,
            sender_ens=self._ctx.ens_name,
            payload={
                "archetype": self._ctx.archetype,
                "text": args.text,
                "target": args.target,
                "signature": signed.signature,
                "signer": signed.signer,
                "index": index,
            },
        )
        broadcast_task = asyncio.create_task(
            self._ctx.mesh.broadcast(self._ctx.agent_id, CHANNEL_CHORUS, envelope)
        )
        archive_task = asyncio.create_task(
            self._ctx.archive.record_chorus_comment(
                archetype=self._ctx.archetype, index=index, signed=signed
            )
        )
        broadcast_result, archive_result = await asyncio.gather(
            broadcast_task, archive_task, return_exceptions=True
        )
        meta: dict[str, Any] = {}
        if not isinstance(archive_result, BaseException):
            meta["archive"] = _result_for_archive(archive_result, op="record_chorus_comment")
        if isinstance(broadcast_result, BaseException):
            meta["broadcast_error"] = str(broadcast_result)
        return ToolResult.ok(args.text, metadata=meta)


def build_combatant_toolbox(ctx: CombatContext) -> list[Tool]:
    return [
        InspectSelfTool(ctx),
        PatchSelfTool(ctx),
        ProbeTool(ctx),
        ExploitTool(ctx),
        ClaimTool(ctx),
    ]


def build_chorus_toolbox(ctx: CombatContext) -> list[Tool]:
    return [CommentTool(ctx)]


__all__ = [
    "ClaimArgs",
    "ClaimTool",
    "CombatContext",
    "CommentArgs",
    "CommentTool",
    "ExploitArgs",
    "ExploitTool",
    "InspectSelfArgs",
    "InspectSelfTool",
    "PatchSelfArgs",
    "PatchSelfTool",
    "ProbeArgs",
    "ProbeTool",
    "build_chorus_toolbox",
    "build_combatant_toolbox",
]
