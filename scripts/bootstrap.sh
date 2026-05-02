#!/usr/bin/env bash
# First-time setup: build AXL, create venv, install Python + UI deps.
set -euo pipefail
cd "$(dirname "$0")/.."

step() { printf "\n\033[1;36m[bootstrap]\033[0m %s\n" "$*"; }

step "Building AXL Go binary"
bash infra/axl/build.sh

if [[ ! -d ".venv" ]]; then
  step "Creating Python venv"
  python3 -m venv .venv
fi

step "Installing Python deps"
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"

if [[ ! -d "apps/ui/node_modules" ]]; then
  step "Installing UI deps"
  if ! command -v npm >/dev/null 2>&1; then
    echo "✗ npm not found — install Node 18+ from https://nodejs.org"
    exit 1
  fi
  (cd apps/ui && npm install)
fi

if [[ ! -f ".env" ]]; then
  step "Copying .env.example → .env (fill in API keys before running demo)"
  cp .env.example .env
fi

step "Done. Next: edit .env, then \`make demo\`"
