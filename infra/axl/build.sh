#!/usr/bin/env bash
# Build the Gensyn AXL `node` binary from source into infra/axl/node.
#
# Idempotent: skips clone+build if the binary already exists and `--rebuild`
# wasn't requested. Honoured by Makefile target `make build-axl`.

set -euo pipefail

cd "$(dirname "$0")"
INFRA_DIR=$(pwd)
SOURCE_DIR="$INFRA_DIR/axl-source"
BINARY="$INFRA_DIR/node"

REBUILD=0
if [[ "${1:-}" == "--rebuild" ]]; then REBUILD=1; fi

if [[ -x "$BINARY" && "$REBUILD" -eq 0 ]]; then
  echo "✓ AXL node binary already built at $BINARY"
  exit 0
fi

if ! command -v go >/dev/null 2>&1; then
  echo "✗ Go is required to build AXL (≥ 1.25.5). Install from https://go.dev/dl"
  exit 1
fi

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  echo "→ Cloning gensyn-ai/axl"
  git clone --depth 1 https://github.com/gensyn-ai/axl.git "$SOURCE_DIR"
else
  echo "→ AXL source present, fetching latest"
  git -C "$SOURCE_DIR" fetch --depth=1 origin
  git -C "$SOURCE_DIR" reset --hard origin/HEAD
fi

echo "→ Building"
(cd "$SOURCE_DIR" && GOTOOLCHAIN=go1.25.5 go build -o "$BINARY" ./cmd/node)

if [[ ! -x "$BINARY" ]]; then
  echo "✗ AXL build did not produce $BINARY"
  exit 2
fi

echo "✓ AXL node binary built at $BINARY"
