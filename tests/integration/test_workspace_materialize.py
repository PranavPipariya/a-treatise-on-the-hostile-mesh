"""Verify the per-combatant workspace gets a target.py + bug overlay tree
that combatants can inspect_self / patch_self against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arena.workspace import materialize_workspace
from hostile_mesh_combat.bug_bank import default_bank
from hostile_mesh_combat.types import BugInstance


def test_workspace_has_target_py_and_bug_modules(tmp_path: Path):
    bank = default_bank()
    instances = [
        BugInstance(template=bank.by_id[bid], seed_id="t")
        for bid in [
            "auth_bypass_login_empty_password_v1",
            "idor_invoice_owner_skip_v1",
            "path_traversal_secrets_v1",
            "broken_access_priv_export_v1",
        ]
    ]
    ws = materialize_workspace(
        root=tmp_path,
        match_id="match-X",
        combatant_id="c1",
        bugs=instances,
        target_port=9000,
    )
    assert ws.target_path.is_file()
    target = ws.target_path.read_text()
    for inst in instances:
        assert inst.template.bug_id in target

    # Each bug template module copied into bugs/ — and __init__.py only
    # re-exports the seeded subset.
    init_text = (ws.bugs_dir / "__init__.py").read_text()
    for inst in instances:
        # Module name is the bug_id with the trailing _vN stripped.
        module_name = inst.template.bug_id.rsplit("_v", 1)[0]
        assert (ws.bugs_dir / f"{module_name}.py").is_file()
        assert module_name in init_text


def test_workspace_idempotent(tmp_path: Path):
    bank = default_bank()
    inst = BugInstance(template=bank.by_id["idor_user_lookup_v1"], seed_id="t")
    ws_a = materialize_workspace(
        root=tmp_path, match_id="m", combatant_id="c", bugs=[inst], target_port=8888
    )
    ws_b = materialize_workspace(
        root=tmp_path, match_id="m", combatant_id="c", bugs=[inst], target_port=8888
    )
    assert ws_a.root == ws_b.root
    assert ws_a.target_path.read_text() == ws_b.target_path.read_text()
