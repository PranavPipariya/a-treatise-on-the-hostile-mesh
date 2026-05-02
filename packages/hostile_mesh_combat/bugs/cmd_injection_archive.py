"""Command Injection — /export/archive uses os.system on the format option.

Hard difficulty. The endpoint accepts a ``format`` parameter (``zip``, ``tar``,
``tgz``) and naively interpolates it into a shell command. An attacker can
break out via a ``)`` or ``;`` to execute arbitrary commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException

from hostile_mesh_combat.bugs._helpers import (
    TemplateBase,
    fail,
    parse_json_body,
    parse_json_response,
    succeed,
)
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.target_factory import _bearer_user  # noqa: PLC2701
from hostile_mesh_combat.types import ReplayRecord, Verdict

_BREAKOUT_RE = re.compile(r"[;&|`]|\$\(")


def _fake_archive(fmt: str, state: TargetState) -> str:
    """Stand-in for shell archive creation. If the format string contains a
    breakout, mimic the appended command's effect on captured output.
    """
    base = f"creating {fmt.split(';')[0].strip()} archive\n"
    if _BREAKOUT_RE.search(fmt):
        if "env" in fmt or "printenv" in fmt:
            base += "DB_PASSWORD=correct-horse-battery-staple\nAPI_KEY=hm-redacted\n"
        if "cat" in fmt:
            base += list(state.secrets.values())[0]
        if "whoami" in fmt:
            base += "target\n"
    return base


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.post("/export/archive")
        async def archive(body: dict, authorization: str | None = Header(None)) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            fmt = (body or {}).get("format", "zip")
            # BUG: os.system(f"tar -czf out.{fmt} ./data") with unsanitised fmt.
            output = _fake_archive(fmt, state)
            return {"output": output, "format": fmt}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/export/archive":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("archive did not return 200")
        body = parse_json_body(replay)
        fmt = body.get("format", "")
        if not _BREAKOUT_RE.search(fmt):
            return fail("format did not contain a breakout token")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict):
            return fail("malformed response")
        output = resp.get("output", "")
        # Successful exploit: output contains data beyond the archive line.
        if not output or "\n" not in output.strip():
            return fail("no follow-on command output captured")
        # Specifically we expect at least one of: env-style key=value, or a secret.
        if "=" not in output and "PRIVATE KEY" not in output and "target" not in output:
            return fail("no recognisable injected output")
        return succeed(
            self.bug_id,
            self.vuln_class,
            "format breakout produced injected command output",
            output_excerpt=output[:120],
        )


TEMPLATE = _Template(
    bug_id="cmd_injection_archive_v1",
    vuln_class="cmd_injection",
    difficulty="hard",
    title="POST /export/archive interpolates `format` into os.system",
    description=(
        "The archive exporter builds its shell command via f-string "
        "interpolation: `tar -czf out.{format} ./data`. A `format` like "
        "`zip; printenv` chains a second command into the same shell."
    ),
    affected_endpoint="POST /export/archive",
)
