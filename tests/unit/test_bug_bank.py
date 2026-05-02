from hostile_mesh_combat.bug_bank import default_bank, seed_match


def test_bank_covers_all_eight_classes():
    bank = default_bank()
    classes = set(bank.classes())
    expected = {
        "auth_bypass",
        "idor",
        "sqli",
        "cmd_injection",
        "path_traversal",
        "race_condition",
        "broken_access",
        "signature_replay",
    }
    missing = expected - classes
    assert not missing, f"missing classes: {missing}"


def test_seed_match_is_deterministic():
    a = seed_match("match-007", ["nightshade", "ironbark"], bugs_per_combatant=4)
    b = seed_match("match-007", ["nightshade", "ironbark"], bugs_per_combatant=4)
    assert [t.template.bug_id for t in a["nightshade"]] == [
        t.template.bug_id for t in b["nightshade"]
    ]


def test_different_match_ids_produce_different_seeds():
    a = seed_match("match-A", ["nightshade", "ironbark"], bugs_per_combatant=4)
    b = seed_match("match-B", ["nightshade", "ironbark"], bugs_per_combatant=4)
    a_ids = sorted(t.template.bug_id for t in a["nightshade"])
    b_ids = sorted(t.template.bug_id for t in b["nightshade"])
    assert a_ids != b_ids


def test_seeded_bugs_dont_collide_on_endpoint():
    seeded = seed_match("collide-test", ["x"], bugs_per_combatant=4)
    endpoints = [t.template.affected_endpoint for t in seeded["x"]]
    assert len(set(endpoints)) == len(endpoints)
