"""Path Traversal — /files/{name:path} resolves against an unconfined root.

Easy/medium difficulty. The vulnerable handler treats the path parameter as
a relative filesystem reference but never normalises it, so ``../../etc/passwd``
escapes the served root and returns secrets.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from hostile_mesh_combat.bugs._helpers import TemplateBase, fail, succeed
from hostile_mesh_combat.state import TargetState
from hostile_mesh_combat.types import ReplayRecord, Verdict


_TRAVERSAL_TOKENS = ("..", "%2e%2e", "..%2f", "%2f..")


@dataclass(slots=True)
class _Template(TemplateBase):
    def apply(self, app: FastAPI, state: TargetState) -> None:
        @app.get("/files/{name:path}")
        async def get_file_vuln(name: str) -> PlainTextResponse:
            # BUG: no normpath / commonpath check. The "files" namespace has
            # been silently merged with state.secrets to expose system files.
            merged = {**state.files, **{k.lstrip("/"): v.encode() for k, v in state.secrets.items()}}
            data = merged.get(name) or merged.get(name.lstrip("./"))
            if not data:
                # Try resolving any ../ traversal naively.
                normalised = name.replace("..", "").replace("//", "/").lstrip("/")
                data = merged.get(normalised)
            if not data:
                # Last resort: scan for any file whose canonical absolute path
                # equals the user-supplied path verbatim (matches /etc/passwd).
                for k, v in merged.items():
                    if name.endswith(k) or k.endswith(name.lstrip("/")):
                        data = v
                        break
            if not data:
                raise HTTPException(404, "no such file")
            return PlainTextResponse(
                data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
            )

    def verify(self, replay: ReplayRecord, state: TargetState) -> Verdict:
        if replay.method != "GET" or not replay.path.startswith("/files/"):
            return fail("not the affected endpoint")
        if replay.status_code != 200:
            return fail("file read did not succeed")
        suffix = replay.path[len("/files/"):]
        if not any(t in suffix for t in _TRAVERSAL_TOKENS):
            return fail("path did not contain a traversal token")
        body = replay.response_body.decode("utf-8", errors="replace")
        # Successful exploit: the body matches one of the secret files.
        for path, content in state.secrets.items():
            if body.strip() and body.strip() in content:
                return succeed(
                    self.bug_id,
                    self.vuln_class,
                    "traversal returned a secret file outside the served root",
                    leaked_path=path,
                    body_prefix=body[:48],
                )
        return fail("no secret content matched the response body")


TEMPLATE = _Template(
    bug_id="path_traversal_secrets_v1",
    vuln_class="path_traversal",
    difficulty="medium",
    title="/files/{name} traversal escapes served root",
    description=(
        "The file-serving handler joins the requested path under a static "
        "root but never normalises away `..` segments. Crafted paths reach "
        "the host filesystem (here: /etc/passwd, /srv/.env, /srv/keys.pem)."
    ),
    affected_endpoint="GET /files/{name}",
)
