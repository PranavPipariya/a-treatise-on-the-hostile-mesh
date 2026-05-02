"""Arena process entrypoint — runs uvicorn with the FastAPI app from
``arena.api.build_app``.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

logging.basicConfig(
    level=os.getenv("HOSTILE_MESH_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    host = os.getenv("HOSTILE_MESH_ARENA_HOST", "127.0.0.1")
    port = int(os.getenv("HOSTILE_MESH_ARENA_PORT", "8787"))
    uvicorn.run(
        "arena.api:build_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
        reload=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
