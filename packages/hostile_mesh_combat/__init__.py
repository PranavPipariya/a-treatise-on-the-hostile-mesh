"""Combat domain: vulnerabilities, target services, verifier, scoring.

The bug bank is a curated set of vulnerability templates organised by class:
auth bypass, IDOR, SQL injection, command injection, path traversal, race
condition, broken access control, signature replay. Each match seeds N bugs
per combatant by sampling from the bank with a difficulty-weighted policy.

The target factory composes a base FastAPI app from a set of seeded bugs;
the deterministic verifier replays an exploit attempt against the live
target state and returns a structured verdict.
"""

from hostile_mesh_combat.bug_bank import BugBank, default_bank, seed_match
from hostile_mesh_combat.scoring import (
    PATCH_BONUS,
    PATCH_BREAKS_SERVICE_PENALTY,
    Scoreboard,
    apply_failed_claim,
    apply_patch,
    apply_wound,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import TargetService, build_target_service
from hostile_mesh_combat.types import (
    BugInstance,
    BugTemplate,
    ExploitClaim,
    ReplayRecord,
    Verdict,
    VulnerabilityClass,
)
from hostile_mesh_combat.verifier import Verifier

__all__ = [
    "BugBank",
    "BugInstance",
    "BugTemplate",
    "ExploitClaim",
    "PATCH_BONUS",
    "PATCH_BREAKS_SERVICE_PENALTY",
    "ReplayRecord",
    "Scoreboard",
    "TargetService",
    "TargetState",
    "Verdict",
    "Verifier",
    "VulnerabilityClass",
    "apply_failed_claim",
    "apply_patch",
    "apply_wound",
    "build_target_service",
    "default_bank",
    "seed_match",
]
