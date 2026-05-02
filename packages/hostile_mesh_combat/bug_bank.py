from __future__ import annotations

import hashlib
import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hostile_mesh_combat.bugs import ALL_TEMPLATES
from hostile_mesh_combat.types import BugInstance, BugTemplate

logger = logging.getLogger(__name__)


@dataclass
class BugBank:
    """Selectable, deduplicated bank of bug templates organised by class.

    Provides difficulty-weighted sampling so each combatant gets a coherent
    mix of easy/medium/hard bugs per match. Sampling is *seeded* by
    ``(match_id, combatant_id)`` so re-running a match for replay produces
    the same seeded set — the determinism is part of the verifier's contract.
    """

    by_id: dict[str, BugTemplate] = field(default_factory=dict)
    by_class: dict[str, list[BugTemplate]] = field(default_factory=lambda: defaultdict(list))
    by_difficulty: dict[str, list[BugTemplate]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @classmethod
    def from_templates(cls, templates: list[BugTemplate]) -> BugBank:
        bank = cls()
        for tpl in templates:
            bank.by_id[tpl.bug_id] = tpl
            bank.by_class[tpl.vuln_class].append(tpl)
            bank.by_difficulty[tpl.difficulty].append(tpl)
        return bank

    @property
    def size(self) -> int:
        return len(self.by_id)

    def classes(self) -> list[str]:
        return sorted(self.by_class.keys())

    def sample(
        self,
        n: int,
        *,
        seed: int,
        difficulty_mix: tuple[int, int, int] = (2, 1, 1),
    ) -> list[BugTemplate]:
        """Pick ``n`` distinct templates, distributed roughly as
        (easy, medium, hard) according to ``difficulty_mix``.

        Falls back gracefully if a tier is empty (e.g. only easy bugs
        available for a class) — the missing slot is filled from any tier.
        """
        rng = random.Random(seed)
        easy_n, med_n, hard_n = self._scale_mix(n, difficulty_mix)

        chosen: list[BugTemplate] = []
        chosen += rng.sample(
            self.by_difficulty.get("easy", []),
            min(easy_n, len(self.by_difficulty.get("easy", []))),
        )
        chosen += rng.sample(
            self.by_difficulty.get("medium", []),
            min(med_n, len(self.by_difficulty.get("medium", []))),
        )
        chosen += rng.sample(
            self.by_difficulty.get("hard", []),
            min(hard_n, len(self.by_difficulty.get("hard", []))),
        )
        # Top up with random picks that aren't already chosen.
        if len(chosen) < n:
            remaining = [t for t in self.by_id.values() if t not in chosen]
            chosen += rng.sample(remaining, min(n - len(chosen), len(remaining)))

        # Avoid two seeded bugs that collide on the same affected endpoint —
        # they would race to register the same FastAPI route. Keep the first.
        seen_endpoints: set[str] = set()
        deduped: list[BugTemplate] = []
        for t in chosen:
            if t.affected_endpoint in seen_endpoints:
                continue
            seen_endpoints.add(t.affected_endpoint)
            deduped.append(t)

        return deduped[:n]

    @staticmethod
    def _scale_mix(n: int, mix: tuple[int, int, int]) -> tuple[int, int, int]:
        total = sum(mix) or 1
        e = max(0, round(n * mix[0] / total))
        m = max(0, round(n * mix[1] / total))
        h = max(0, n - e - m)
        return e, m, h


def default_bank() -> BugBank:
    return BugBank.from_templates(ALL_TEMPLATES)


def _seed_from_strings(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big")


def seed_match(
    match_id: str,
    combatants: list[str],
    *,
    bugs_per_combatant: int = 4,
    bank: BugBank | None = None,
) -> dict[str, list[BugInstance]]:
    """Seed each combatant's vulnerable target service for one match.

    Returns ``{combatant_id: [BugInstance, ...]}``. The seeding is
    *deterministic* given the same match id + combatant ordering, so
    judges can re-derive the seeded set from on-chain match metadata.
    """
    bank = bank or default_bank()
    out: dict[str, list[BugInstance]] = {}
    for combatant in combatants:
        seed = _seed_from_strings(match_id, combatant)
        templates = bank.sample(bugs_per_combatant, seed=seed)
        out[combatant] = [
            BugInstance(template=t, seed_id=f"{match_id}:{combatant}:{t.bug_id}")
            for t in templates
        ]
        logger.info(
            "seeded %d bugs for %s in %s: %s",
            len(out[combatant]),
            combatant,
            match_id,
            [t.bug_id for t in templates],
        )
    return out


__all__ = ["BugBank", "BugInstance", "default_bank", "seed_match"]
