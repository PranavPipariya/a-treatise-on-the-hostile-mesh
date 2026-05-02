from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover — reference-only
    pass


class VulnerabilityClass(str, Enum):
    AUTH_BYPASS = "auth_bypass"
    IDOR = "idor"
    SQLI = "sqli"
    CMD_INJECTION = "cmd_injection"
    PATH_TRAVERSAL = "path_traversal"
    RACE_CONDITION = "race_condition"
    BROKEN_ACCESS = "broken_access"
    SIGNATURE_REPLAY = "signature_replay"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(slots=True)
class ReplayRecord:
    """The exact request/response pair the verifier replays for a public
    exploit attempt. Captured by the arena when it forwards an
    ``exploit()`` call to the target."""

    method: str
    path: str
    headers: dict[str, str]
    query: dict[str, str]
    body: bytes | None
    status_code: int
    response_body: bytes
    response_headers: dict[str, str]


@dataclass(slots=True)
class ExploitClaim:
    """What the combatant publicly committed to. Verifier judges against
    the live replay; if claim matches outcome, it's a wound."""

    vuln_class: str  # VulnerabilityClass value
    target_endpoint: str  # e.g. "GET /users/123"
    summary: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Verdict:
    """Verifier output for one exploit attempt."""

    success: bool
    matched_bug_id: str | None
    matched_bug_class: str | None
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


class _TargetStateLike(Protocol):
    """Structural typing for what bug templates expect from TargetState.

    Defined as a Protocol so bug modules don't have to import the concrete
    class (avoids circular imports and keeps templates testable in isolation).
    """

    users: dict[int, dict[str, Any]]
    sessions: dict[str, dict[str, Any]]
    files: dict[str, bytes]
    balances: dict[int, int]
    invoices: dict[int, dict[str, Any]]
    audit_log: list[dict[str, Any]]


class BugTemplate(Protocol):
    """The contract every entry in the bug bank conforms to.

    Implementations live as small modules under ``bugs/``; each exposes a
    module-level ``TEMPLATE`` constant that satisfies this Protocol.

    A template is *seeded* into a target's FastAPI app via :meth:`apply`.
    When an exploit attempt is replayed, :meth:`verify` is called with the
    replay + the target's mutated state. The verdict bubbles up to scoring.
    """

    bug_id: str
    vuln_class: str
    difficulty: str
    title: str
    description: str  # surfaced in inspect_self()
    affected_endpoint: str  # e.g. "GET /users/{id}"

    def apply(self, app: Any, state: _TargetStateLike) -> None: ...

    def patch_signature(self) -> str:
        """A short token a combatant's patch must contain in its diff to
        count as closing this specific bug. Defaults to the bug_id; some
        templates override (e.g. when there are multiple acceptable fixes).
        """
        ...

    def verify(self, replay: ReplayRecord, state: _TargetStateLike) -> Verdict: ...


@dataclass(slots=True)
class BugInstance:
    """A bug template instantiated for a specific (combatant, match).

    Lives here (rather than in ``bug_bank``) because the target factory and
    the bug template modules both reference it; keeping it dependency-free
    avoids a circular import between ``bug_bank``, ``bugs/*``, and
    ``target_factory``.
    """

    template: BugTemplate
    seed_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "BugInstance",
    "BugTemplate",
    "Difficulty",
    "ExploitClaim",
    "ReplayRecord",
    "Verdict",
    "VulnerabilityClass",
]
