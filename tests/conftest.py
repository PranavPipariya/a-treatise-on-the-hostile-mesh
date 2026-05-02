import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("packages", "services"):
    path = str(ROOT / sub)
    if path not in sys.path:
        sys.path.insert(0, path)

# Tests must never reach for real networks unless explicitly opted in.
os.environ.setdefault("HOSTILE_MESH_KEYSTORE_PASSPHRASE", "test-passphrase")
