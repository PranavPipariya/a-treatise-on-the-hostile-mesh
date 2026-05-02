#!/usr/bin/env bash
# Spin up the full Hostile Mesh demo — arena API + UI dev server.
#
# The arena process owns the entire process tree (target services, AXL nodes,
# combatant agents, chorus agents). Killing it tears everything down.

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f ".env" ]]; then
  set -a; . .env; set +a
fi

if [[ ! -d ".venv" ]]; then
  echo "✗ .venv not found — run \`make bootstrap\` first."
  exit 1
fi

cleanup() {
  trap - EXIT
  echo
  echo "→ Stopping demo"
  [[ -n "${ARENA_PID:-}" ]] && kill "$ARENA_PID" 2>/dev/null || true
  [[ -n "${UI_PID:-}"    ]] && kill "$UI_PID"    2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

. .venv/bin/activate
export PYTHONPATH="$PWD/packages:$PWD/services:${PYTHONPATH:-}"

echo "→ Starting arena API on :${HOSTILE_MESH_ARENA_PORT:-8787}"
python -m arena.main &
ARENA_PID=$!

echo "→ Starting UI on :5173"
(cd apps/ui && npm run dev) &
UI_PID=$!

echo
echo "============================================================"
echo " Arena API:  http://${HOSTILE_MESH_ARENA_HOST:-127.0.0.1}:${HOSTILE_MESH_ARENA_PORT:-8787}"
echo " UI:         http://127.0.0.1:5173"
echo " POST /api/match/start to begin a match."
echo "============================================================"
echo

wait
