from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from hostile_mesh_runtime.tools.base import ToolKind


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    NEEDS_CONFIRMATION = "needs_confirmation"
    REJECTED = "rejected"


@dataclass(slots=True)
class ApprovalContext:
    tool_name: str
    kind: ToolKind
    params: dict[str, Any]
    affected_paths: list[Path] = field(default_factory=list)
    command: str | None = None
    is_dangerous: bool = False


class PermissionManager:
    """Six-mode permission engine.

    Hostile Mesh agents are sandboxed by design — they can only touch their
    own service workspace and only speak HTTP through AXL or to their own
    target service. So the default policy auto-approves every kind that's
    been declared safe in ``RuntimeConfig.auto_approve_kinds``. Anything
    explicitly forbidden returns ``REJECTED``.

    The engine exists so the *same* runtime can be reused for non-combat
    contexts (e.g. running Godel against a real workspace) by simply
    tightening the policy.
    """

    def __init__(
        self,
        auto_approve_kinds: tuple[str, ...] = (),
        forbidden_kinds: tuple[str, ...] = (),
        forbidden_path_prefixes: tuple[str, ...] = (),
    ) -> None:
        self._auto = {ToolKind(k) for k in auto_approve_kinds}
        self._forbidden = {ToolKind(k) for k in forbidden_kinds}
        self._forbidden_paths = tuple(Path(p).resolve() for p in forbidden_path_prefixes)

    def decide(self, ctx: ApprovalContext) -> ApprovalDecision:
        if ctx.kind in self._forbidden:
            return ApprovalDecision.REJECTED
        if ctx.is_dangerous:
            return ApprovalDecision.NEEDS_CONFIRMATION
        for path in ctx.affected_paths:
            resolved = path.resolve()
            if any(str(resolved).startswith(str(p)) for p in self._forbidden_paths):
                return ApprovalDecision.REJECTED
        if ctx.kind in self._auto:
            return ApprovalDecision.APPROVED
        return ApprovalDecision.NEEDS_CONFIRMATION


__all__ = ["ApprovalContext", "ApprovalDecision", "PermissionManager"]
