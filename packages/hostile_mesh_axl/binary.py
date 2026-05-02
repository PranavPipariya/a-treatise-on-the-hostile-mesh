from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

GENSYN_AXL_REPO = "https://github.com/gensyn-ai/axl.git"


@dataclass(slots=True)
class AxlBinary:
    """Resolved location of the AXL ``node`` Go binary plus the source tree
    we built it from. Either path may be ``None`` if not yet materialised."""

    binary_path: Path
    source_dir: Path | None = None

    @property
    def exists(self) -> bool:
        return self.binary_path.is_file() and os.access(self.binary_path, os.X_OK)


def _has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def ensure_binary(
    target_dir: Path,
    *,
    rebuild: bool = False,
) -> AxlBinary:
    """Materialise the AXL ``node`` binary at ``target_dir/node``.

    Strategy:
        1. If ``HOSTILE_MESH_AXL_BINARY`` env var points to an existing binary,
           use it (used in CI / when prebuilt).
        2. Else, clone https://github.com/gensyn-ai/axl into
           ``target_dir/axl-source`` (shallow), ``go build`` ``./cmd/node``,
           and copy the result to ``target_dir/node``.

    If ``go`` is missing, raises ``RuntimeError`` with an actionable message.
    Returns an ``AxlBinary`` either way.
    """

    env_path = os.getenv("HOSTILE_MESH_AXL_BINARY", "").strip()
    if env_path and not rebuild:
        binary = Path(env_path).expanduser().resolve()
        if binary.is_file() and os.access(binary, os.X_OK):
            return AxlBinary(binary_path=binary)

    target_dir = target_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    binary_path = target_dir / "node"
    source_dir = target_dir / "axl-source"

    if binary_path.exists() and not rebuild:
        return AxlBinary(binary_path=binary_path, source_dir=source_dir if source_dir.is_dir() else None)

    if not _has_command("go"):
        raise RuntimeError(
            "AXL requires the Go toolchain (1.25.5+) to build the node binary, "
            "but `go` is not on PATH. Install Go (https://go.dev/dl) and re-run "
            "`make bootstrap`, or set HOSTILE_MESH_AXL_BINARY to a prebuilt binary."
        )

    if not source_dir.is_dir():
        if not _has_command("git"):
            raise RuntimeError("git is required to clone the AXL repo.")
        subprocess.run(
            ["git", "clone", "--depth", "1", GENSYN_AXL_REPO, str(source_dir)],
            check=True,
        )

    env = os.environ.copy()
    env.setdefault("GOTOOLCHAIN", "go1.25.5")
    subprocess.run(
        ["go", "build", "-o", str(binary_path), "./cmd/node"],
        cwd=source_dir,
        env=env,
        check=True,
    )

    if not binary_path.is_file():
        raise RuntimeError(f"AXL build appeared to succeed but {binary_path} is missing")

    return AxlBinary(binary_path=binary_path, source_dir=source_dir)


__all__ = ["AxlBinary", "ensure_binary"]
