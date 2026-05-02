"""Vulnerable target service process entrypoint.

Hosted on a per-combatant port. Reads the seeded bug list from an env var,
constructs a TargetService via the combat factory, and exposes the FastAPI
app over uvicorn. The arena restarts this process after each accepted patch.

Critically, the combatant's *workspace* is `sys.path`'d in first so any
patch the combatant writes to the workspace overrides the installed copy
of the same bug template module on import.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=os.getenv("HOSTILE_MESH_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hostilemesh.target")


def _load_bug_template_overlay(workspace: Path, bug_id: str):
    """If the combatant has patched the bug template in their workspace,
    return that patched version; otherwise return the canonical one.
    """
    overlay = workspace / "bugs" / f"{bug_id}.py"
    if overlay.is_file():
        spec = importlib.util.spec_from_file_location(
            f"workspace.bugs.{bug_id}", overlay
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tpl = getattr(module, "TEMPLATE", None)
            if tpl is not None:
                logger.info("loaded patched template %s from workspace", bug_id)
                return tpl
    from hostile_mesh_combat.bug_bank import default_bank
    return default_bank().by_id[bug_id]


def build_app():
    from hostile_mesh_combat.target_factory import build_target_service
    from hostile_mesh_combat.types import BugInstance

    combatant_id = os.environ["HOSTILE_MESH_TARGET_COMBATANT_ID"]
    workspace = Path(os.environ["HOSTILE_MESH_WORKSPACE"]).resolve()
    bug_ids: list[str] = json.loads(os.environ["HOSTILE_MESH_TARGET_BUGS_JSON"])

    instances: list[BugInstance] = []
    for bug_id in bug_ids:
        tpl = _load_bug_template_overlay(workspace, bug_id)
        instances.append(
            BugInstance(template=tpl, seed_id=f"workspace:{combatant_id}:{bug_id}")
        )

    service = build_target_service(combatant_id, instances)
    # Stash on app state so the arena's patch handler can poke at it later.
    service.app.state.target_service = service
    return service.app


def main() -> int:
    host = os.environ.get("HOSTILE_MESH_TARGET_HOST", "127.0.0.1")
    port = int(os.environ.get("HOSTILE_MESH_TARGET_PORT", "8800"))
    workspace = Path(os.environ["HOSTILE_MESH_WORKSPACE"]).resolve()
    sys.path.insert(0, str(workspace))

    app = build_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
