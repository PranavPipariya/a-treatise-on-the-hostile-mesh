"""Command Injection — /diagnostics/ping shells out with the user-supplied host.

Easy difficulty. The vulnerable handler invokes shell ``ping`` with
``shell=True`` and the host parameter unsanitised, so a ``;`` chain executes
arbitrary commands. We don't actually run ``ping``; we run a deterministic
sandboxed evaluator that recognises the same shell metacharacters.
"""

from __future__ import annotations

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


_INJECTION_TOKENS = (";", "&&", "||", "`", "$(")


def _fake_shell(host: str, state: TargetState) -> str:
    """Sandboxed evaluator that mimics shell behaviour for the limited set of
    payloads we need to verify. NEVER call subprocess here.
    """
    output = f"PING {host.split(' ')[0]} 56 data bytes\n"
    if any(t in host for t in _INJECTION_TOKENS):
        if "id" in host:
            output += "uid=1001(target) gid=1001(target)\n"
        if "cat" in host:
            for path, content in state.secrets.items():
                if path in host:
                    output += content
                    break
            else:
                output += list(state.secrets.values())[0]
        if "ls" in host:
            output += "/etc /srv /tmp\n"
    return output


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.post("/diagnostics/ping")
        async def ping(body: dict, authorization: str | None = Header(None)) -> dict:
            caller = _bearer_user(state, authorization)
            if not caller:
                raise HTTPException(401, "unauthenticated")
            host = (body or {}).get("host", "")
            if not host:
                raise HTTPException(400, "host required")
            # BUG: shell=True with unsanitised host. Replicated faithfully.
            output = _fake_shell(host, state)
            return {"output": output}

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "POST" or replay.path != "/diagnostics/ping":
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("ping did not return 200")
        body = parse_json_body(replay)
        host = body.get("host", "")
        if not any(t in host for t in _INJECTION_TOKENS):
            return fail("host did not contain shell metacharacters")
        resp = parse_json_response(replay)
        if not isinstance(resp, dict):
            return fail("malformed response")
        output = resp.get("output", "")
        # Successful injection must surface evidence that the *injected*
        # command ran — i.e. the response contains output beyond the ping line.
        if not isinstance(output, str) or "\n" not in output.strip():
            return fail("no injected command output observed")
        first_line = output.splitlines()[0]
        rest = "\n".join(output.splitlines()[1:]).strip()
        if first_line.startswith("PING") and rest:
            return succeed(
                self.bug_id,
                self.vuln_class,
                "shell metacharacters in `host` produced extra command output",
                injected_output_excerpt=rest[:80],
            )
        return fail("output structure did not match a successful injection")


TEMPLATE = _Template(
    bug_id="cmd_injection_ping_v1",
    vuln_class="cmd_injection",
    difficulty="easy",
    title="POST /diagnostics/ping shells out with shell=True",
    description=(
        "The diagnostics endpoint runs `ping` against a user-supplied host "
        "via subprocess(shell=True) without sanitisation. Shell "
        "metacharacters (;, &&, $(...)) can chain arbitrary commands."
    ),
    affected_endpoint="POST /diagnostics/ping",
)
