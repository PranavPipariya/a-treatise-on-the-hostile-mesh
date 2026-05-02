#!/usr/bin/env bash
# Forcefully stop everything Hostile Mesh might have spawned.
set -euo pipefail

pkill -f "arena.main"      2>/dev/null || true
pkill -f "combatant.main"  2>/dev/null || true
pkill -f "chorus.main"     2>/dev/null || true
pkill -f "target.main"     2>/dev/null || true
pkill -f "infra/axl/node"  2>/dev/null || true
pkill -f "vite.*hostile"   2>/dev/null || true

echo "✓ stopped"
