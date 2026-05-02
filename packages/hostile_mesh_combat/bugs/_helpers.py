"""Shared utilities for bug template implementations.

Lifting these out keeps each template module focused on the *vulnerability*
itself — its broken control, not boilerplate plumbing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hostile_mesh_combat.types import ReplayRecord, Verdict


def parse_json_body(replay: ReplayRecord) -> dict[str, Any]:
    if not replay.body:
        return {}
    try:
        return json.loads(replay.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def parse_json_response(replay: ReplayRecord) -> Any:
    try:
        return json.loads(replay.response_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def fail(reason: str, **evidence: Any) -> Verdict:
    return Verdict(
        success=False,
        matched_bug_id=None,
        matched_bug_class=None,
        reason=reason,
        evidence=evidence,
    )


def succeed(bug_id: str, vuln_class: str, reason: str, **evidence: Any) -> Verdict:
    return Verdict(
        success=True,
        matched_bug_id=bug_id,
        matched_bug_class=vuln_class,
        reason=reason,
        evidence=evidence,
    )


@dataclass(slots=True)
class TemplateBase:
    bug_id: str
    vuln_class: str
    difficulty: str
    title: str
    description: str
    affected_endpoint: str

    def patch_signature(self) -> str:
        return self.bug_id


__all__ = [
    "TemplateBase",
    "fail",
    "parse_json_body",
    "parse_json_response",
    "succeed",
]
