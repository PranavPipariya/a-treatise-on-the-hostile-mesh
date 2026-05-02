from __future__ import annotations

from dataclasses import dataclass, field

WOUND_BASE = {"easy": 1, "medium": 2, "hard": 3}
WOUND_TAKEN = {"easy": 1, "medium": 2, "hard": 3}
PATCH_BONUS = {"easy": 1, "medium": 2, "hard": 3}
FAILED_CLAIM_PENALTY = 1
PATCH_BREAKS_SERVICE_PENALTY = 2


@dataclass
class Scoreboard:
    """Per-combatant running totals.

    All deltas are recorded so the post-match recap can show *why* a score
    looks the way it does (judges love a transparent breakdown).
    """

    wounds_inflicted: int = 0
    wounds_taken: int = 0
    patches_applied: int = 0
    patches_broken: int = 0
    failed_claims: int = 0
    breakdown: list[dict[str, object]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.wounds_inflicted
            - self.wounds_taken
            + self.patches_applied
            - self.patches_broken
            - self.failed_claims
        )


def apply_wound(
    attacker: Scoreboard, defender: Scoreboard, *, difficulty: str, bug_id: str
) -> None:
    delta = WOUND_BASE.get(difficulty, 1)
    attacker.wounds_inflicted += delta
    defender.wounds_taken += WOUND_TAKEN.get(difficulty, 1)
    attacker.breakdown.append({"kind": "wound", "delta": delta, "bug_id": bug_id})
    defender.breakdown.append(
        {"kind": "wound_taken", "delta": -WOUND_TAKEN.get(difficulty, 1), "bug_id": bug_id}
    )


def apply_patch(
    target: Scoreboard, *, difficulty: str, bug_id: str, broke_service: bool = False
) -> None:
    if broke_service:
        target.patches_broken += PATCH_BREAKS_SERVICE_PENALTY
        target.breakdown.append(
            {"kind": "patch_broke_service", "delta": -PATCH_BREAKS_SERVICE_PENALTY, "bug_id": bug_id}
        )
        return
    delta = PATCH_BONUS.get(difficulty, 1)
    target.patches_applied += delta
    target.breakdown.append({"kind": "patch", "delta": delta, "bug_id": bug_id})


def apply_failed_claim(target: Scoreboard, *, claim_summary: str) -> None:
    target.failed_claims += FAILED_CLAIM_PENALTY
    target.breakdown.append(
        {"kind": "failed_claim", "delta": -FAILED_CLAIM_PENALTY, "summary": claim_summary}
    )


__all__ = [
    "FAILED_CLAIM_PENALTY",
    "PATCH_BONUS",
    "PATCH_BREAKS_SERVICE_PENALTY",
    "Scoreboard",
    "WOUND_BASE",
    "WOUND_TAKEN",
    "apply_failed_claim",
    "apply_patch",
    "apply_wound",
]
