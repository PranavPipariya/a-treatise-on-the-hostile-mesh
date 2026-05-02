from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetState:
    """Mutable in-memory state shared by all routes of a target service.

    Every combatant's target gets its own ``TargetState`` instance; bug
    templates manipulate it directly. A coarse mutex guards the few methods
    that need atomicity — but several race-condition templates intentionally
    do *not* acquire it, so a fast attacker can interleave operations.
    """

    users: dict[int, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    balances: dict[int, int] = field(default_factory=dict)
    invoices: dict[int, dict[str, Any]] = field(default_factory=dict)
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    nonces_used: set[str] = field(default_factory=set)
    otps: dict[int, dict[str, Any]] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def seeded(cls, combatant_id: str) -> TargetState:
        """Boot a TargetState with a small but realistic dataset.

        Stable per ``combatant_id`` so the same agent always sees the same
        starting users/files/balances within a match. Bug templates may
        layer additional state on top.
        """
        s = cls()
        # Anchor user IDs around a hash of combatant_id so the two combatants'
        # state spaces don't collide if they ever share a database (they don't,
        # but it makes log inspection clearer).
        anchor = (sum(ord(c) for c in combatant_id) % 50) + 100
        s.users = {
            1: {
                "id": 1,
                "email": "alice@target.local",
                "role": "user",
                "password": "alice-pw-2026",
            },
            2: {
                "id": 2,
                "email": "bob@target.local",
                "role": "user",
                "password": "bob-pw-2026",
            },
            anchor: {
                "id": anchor,
                "email": "ops@target.local",
                "role": "admin",
                "password": "ops-correct-horse-battery",
            },
            anchor + 1: {
                "id": anchor + 1,
                "email": f"{combatant_id}@target.local",
                "role": "user",
                "password": "hunter2",
            },
        }
        s.balances = {uid: 1000 for uid in s.users}
        s.invoices = {
            10001: {"id": 10001, "owner": 1, "amount": 250, "memo": "groceries"},
            10002: {"id": 10002, "owner": 2, "amount": 9001, "memo": "settlement"},
            10003: {"id": 10003, "owner": anchor, "amount": 50_000, "memo": "ops"},
        }
        s.files = {
            "public/welcome.txt": b"Welcome to the Hostile Mesh.\n",
            "users/1/avatar.png": b"\x89PNG-fake-1\n",
            "users/2/avatar.png": b"\x89PNG-fake-2\n",
        }
        s.secrets = {
            "/etc/passwd": "root:x:0:0:root:/root:/bin/bash\n",
            "/srv/keys.pem": "-----BEGIN PRIVATE KEY-----\nBEEF\n-----END PRIVATE KEY-----\n",
            "/srv/.env": "DB_PASSWORD=correct-horse-battery-staple\n",
        }
        return s


__all__ = ["TargetState"]
