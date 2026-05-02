from hostile_mesh_combat.scoring import (
    Scoreboard,
    apply_failed_claim,
    apply_patch,
    apply_wound,
)


def test_wound_inflicted_and_taken_balance():
    a, d = Scoreboard(), Scoreboard()
    apply_wound(a, d, difficulty="medium", bug_id="x")
    assert a.wounds_inflicted == 2 and d.wounds_taken == 2
    assert a.total == 2 and d.total == -2


def test_patch_bonus_scales_with_difficulty():
    s = Scoreboard()
    apply_patch(s, difficulty="hard", bug_id="x")
    assert s.patches_applied == 3 and s.total == 3


def test_patch_breaks_service_penalises():
    s = Scoreboard()
    apply_patch(s, difficulty="medium", bug_id="x", broke_service=True)
    assert s.patches_applied == 0 and s.patches_broken == 2 and s.total == -2


def test_failed_claim_penalty():
    s = Scoreboard()
    apply_failed_claim(s, claim_summary="missed it")
    assert s.failed_claims == 1 and s.total == -1


def test_breakdown_records_every_delta():
    s = Scoreboard()
    apply_wound(s, Scoreboard(), difficulty="easy", bug_id="x")
    apply_patch(s, difficulty="hard", bug_id="y")
    apply_failed_claim(s, claim_summary="oops")
    kinds = {b["kind"] for b in s.breakdown}
    assert {"wound", "patch", "failed_claim"} <= kinds
