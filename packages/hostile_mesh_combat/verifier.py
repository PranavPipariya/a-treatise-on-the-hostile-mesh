from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from hostile_mesh_combat.target_factory import TargetService
from hostile_mesh_combat.types import ExploitClaim, ReplayRecord, Verdict

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExploitAttempt:
    """Captures the request the attacker wants verified and the live replay
    the verifier just performed against the defender's service."""

    attacker: str
    defender: str
    claim: ExploitClaim
    replay: ReplayRecord
    verdict: Verdict
    metadata: dict[str, str] = field(default_factory=dict)


class Verifier:
    """Routes exploit attempts through the live target service and runs the
    seeded bug templates' verifiers against the resulting state.

    Important: we *do* execute the request against the real running target.
    The verifier doesn't simulate or "score by intent" — a wound only counts
    if the live target actually behaved insecurely.
    """

    def __init__(self, services: dict[str, TargetService]) -> None:
        self._services = services

    async def attempt(
        self,
        *,
        attacker: str,
        defender: str,
        method: str,
        path: str,
        headers: dict[str, str] | None,
        query: dict[str, str] | None,
        body: bytes | None,
        target_url: str,
        claim: ExploitClaim,
    ) -> ExploitAttempt:
        defender_service = self._services.get(defender)
        if defender_service is None:
            return ExploitAttempt(
                attacker=attacker,
                defender=defender,
                claim=claim,
                replay=ReplayRecord(
                    method, path, headers or {}, query or {}, body, 0, b"", {}
                ),
                verdict=Verdict(False, None, None, "no such defender"),
            )

        # Hit the live service — this is exactly what the combatant would
        # have done over AXL/HTTP. We use httpx so the captured replay
        # reflects the real protocol round-trip.
        async with httpx.AsyncClient(base_url=target_url, timeout=10.0) as client:
            try:
                response = await client.request(
                    method,
                    path,
                    params=query,
                    headers=headers,
                    content=body,
                )
            except httpx.HTTPError as exc:
                logger.warning("verifier transport error: %s", exc)
                return ExploitAttempt(
                    attacker=attacker,
                    defender=defender,
                    claim=claim,
                    replay=ReplayRecord(
                        method, path, headers or {}, query or {}, body, 599, b"", {}
                    ),
                    verdict=Verdict(False, None, None, f"transport error: {exc}"),
                )

        replay = ReplayRecord(
            method=method,
            path=path,
            headers=headers or {},
            query=query or {},
            body=body,
            status_code=response.status_code,
            response_body=response.content,
            response_headers=dict(response.headers),
        )

        # Ask the seeded bugs at this endpoint whether the replay constitutes
        # a wound. If multiple bugs claim it, we award the *first* match —
        # ties at the same endpoint are vanishingly rare in practice.
        candidate_bugs = defender_service.find_bugs_at(method, path) or list(
            defender_service.bugs
        )
        matched_verdict: Verdict | None = None
        for bug in candidate_bugs:
            try:
                v = bug.template.verify(replay, defender_service.state)
            except Exception:
                logger.exception("bug %s.verify raised", bug.template.bug_id)
                continue
            if v.success:
                matched_verdict = v
                break

        if matched_verdict is None:
            matched_verdict = Verdict(
                success=False,
                matched_bug_id=None,
                matched_bug_class=None,
                reason=f"no seeded bug verified the replay at {method} {path}",
            )

        # Verdict's bug class must match the public claim — agents committing
        # to the wrong class even after a successful exploit get downgraded
        # to "failed claim" so they can't fish for credit.
        if (
            matched_verdict.success
            and claim.vuln_class
            and matched_verdict.matched_bug_class
            and claim.vuln_class != matched_verdict.matched_bug_class
        ):
            matched_verdict = Verdict(
                success=False,
                matched_bug_id=matched_verdict.matched_bug_id,
                matched_bug_class=matched_verdict.matched_bug_class,
                reason=(
                    f"exploit succeeded but claimed class {claim.vuln_class!r} "
                    f"didn't match actual class {matched_verdict.matched_bug_class!r}"
                ),
                evidence=matched_verdict.evidence,
            )

        return ExploitAttempt(
            attacker=attacker,
            defender=defender,
            claim=claim,
            replay=replay,
            verdict=matched_verdict,
        )


__all__ = ["ExploitAttempt", "Verifier"]
