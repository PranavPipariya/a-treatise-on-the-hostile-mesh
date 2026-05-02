"""Per-combatant per-match writable workspace.

The arena materialises a directory like
``.match-state/<match_id>/<combatant>/`` that contains:

  - ``target.py``                 — generated FastAPI entrypoint
  - ``bugs/<bug_id>.py``          — copies of seeded bug template modules
  - ``bugs/__init__.py``          — re-exports just the seeded subset
  - ``bugs/_helpers.py``          — copy of the shared helpers

The combatant's ``inspect_self`` and ``patch_self`` operate against this
directory; the target subprocess runs uvicorn with the workspace prepended
to ``sys.path``, so a patched bug module wins over the canonical one.
"""

from __future__ import annotations

import importlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from hostile_mesh_combat.types import BugInstance

logger = logging.getLogger(__name__)


TARGET_PY_TEMPLATE = '''\
"""Generated target service for combatant {combatant_id}.

Match: {match_id}
Seeded bugs ({bug_count}):
{bug_summary}

Run:  uvicorn target:app --host 127.0.0.1 --port {port}

This file is the inspect_self() entrypoint — combatants read it to
understand which vulnerabilities they're defending against. Each seeded
bug imports its own module under bugs/, so patches to those modules take
effect when the target subprocess restarts.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from hostile_mesh_combat.types import BugInstance
from hostile_mesh_combat.target_factory import build_target_service


_WORKSPACE = Path(__file__).resolve().parent
sys.path.insert(0, str(_WORKSPACE))


def _load(bug_id: str):
    overlay = _WORKSPACE / "bugs" / f"{{bug_id}}.py"
    if overlay.is_file():
        spec = importlib.util.spec_from_file_location(
            f"workspace.bugs.{{bug_id}}", overlay
        )
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tpl = getattr(mod, "TEMPLATE", None)
            if tpl is not None:
                return tpl
    from hostile_mesh_combat.bug_bank import default_bank
    return default_bank().by_id[bug_id]


_BUGS = {bug_ids!r}
_INSTANCES = [BugInstance(template=_load(b), seed_id=f"{combatant_id}:{match_id}:" + b) for b in _BUGS]
_SERVICE = build_target_service("{combatant_id}", _INSTANCES)
app = _SERVICE.app
'''


@dataclass(slots=True)
class CombatantWorkspace:
    combatant_id: str
    match_id: str
    root: Path
    bug_ids: list[str]
    target_path: Path
    bugs_dir: Path


def _copy_bug_module(bug_id: str, dest_dir: Path) -> None:
    """Copy the canonical bug template module into the workspace bugs dir."""
    module = importlib.import_module(f"hostile_mesh_combat.bugs.{bug_id}")
    src = Path(module.__file__)  # type: ignore[arg-type]
    shutil.copy(src, dest_dir / src.name)


def materialize_workspace(
    *,
    root: Path,
    match_id: str,
    combatant_id: str,
    bugs: list[BugInstance],
    target_port: int,
) -> CombatantWorkspace:
    workspace_root = root / match_id / combatant_id
    workspace_root.mkdir(parents=True, exist_ok=True)
    bugs_dir = workspace_root / "bugs"
    bugs_dir.mkdir(parents=True, exist_ok=True)

    # Copy the bug template modules + shared helpers.
    for inst in bugs:
        # The actual file path is hostile_mesh_combat/bugs/<file>.py — the
        # bug_id may not match the file name 1:1 (e.g. "auth_bypass_login_empty_password_v1"
        # lives in "auth_bypass_login_empty_password.py"). We resolve via the
        # canonical module that defines TEMPLATE.
        module_name = _module_name_for_template(inst.template.bug_id)
        module = importlib.import_module(f"hostile_mesh_combat.bugs.{module_name}")
        src = Path(module.__file__)  # type: ignore[arg-type]
        shutil.copy(src, bugs_dir / src.name)

    # Copy shared helpers so the bug modules import successfully.
    helpers = importlib.import_module("hostile_mesh_combat.bugs._helpers")
    shutil.copy(Path(helpers.__file__), bugs_dir / "_helpers.py")  # type: ignore[arg-type]

    # Workspace bugs/__init__.py re-exports just the seeded subset.
    seeded_imports = "\n".join(f"from . import {_module_name_for_template(b.template.bug_id)}" for b in bugs)
    seeded_list = ",\n    ".join(f"{_module_name_for_template(b.template.bug_id)}.TEMPLATE" for b in bugs)
    (bugs_dir / "__init__.py").write_text(
        f'"""Workspace overlay — seeded subset only."""\n\n'
        f"{seeded_imports}\n\n"
        f"SEEDED_TEMPLATES = [\n    {seeded_list},\n]\n"
    )

    # Generate target.py — this is the canonical inspect_self() artifact.
    summary = "\n".join(
        f"  - {b.template.bug_id} ({b.template.vuln_class}, {b.template.difficulty}): "
        f"{b.template.title}"
        for b in bugs
    )
    target_path = workspace_root / "target.py"
    target_path.write_text(
        TARGET_PY_TEMPLATE.format(
            combatant_id=combatant_id,
            match_id=match_id,
            bug_count=len(bugs),
            bug_summary=summary,
            bug_ids=[b.template.bug_id for b in bugs],
            port=target_port,
        )
    )

    return CombatantWorkspace(
        combatant_id=combatant_id,
        match_id=match_id,
        root=workspace_root,
        bug_ids=[b.template.bug_id for b in bugs],
        target_path=target_path,
        bugs_dir=bugs_dir,
    )


def _module_name_for_template(bug_id: str) -> str:
    """Strip ``_vN`` suffixes to recover the module file stem."""
    parts = bug_id.split("_")
    if parts and parts[-1].startswith("v") and parts[-1][1:].isdigit():
        return "_".join(parts[:-1])
    return bug_id


__all__ = ["CombatantWorkspace", "materialize_workspace"]
