#!/usr/bin/env bash
#
# Build and pack the deck Stream Deck plugin into a distributable
# .streamDeckPlugin file (double-click to install — no dev mode needed).
#
# Usage:
#   streamdeck-plugin/scripts/pack.sh            # build + pack to dist/
#   streamdeck-plugin/scripts/pack.sh 1.2.0.0    # also stamp this version
#
# Output: streamdeck-plugin/dist/ai.technologylab.deck.streamDeckPlugin
set -euo pipefail

# Resolve the plugin dir (this script lives in <plugin>/scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
SDPLUGIN="ai.technologylab.deck.sdPlugin"
OUT_DIR="dist"
VERSION="${1:-}"

cd "$PLUGIN_DIR"

# Preflight: need node (to build) and the Elgato CLI (to pack).
command -v node >/dev/null 2>&1 || { echo "error: node not found (needed to build)"; exit 1; }
command -v streamdeck >/dev/null 2>&1 || {
  echo "error: streamdeck CLI not found. Install it with: npm i -g @elgato/cli"; exit 1;
}

echo "==> Installing deps (npm ci if lockfile present, else npm install)"
if [ -f package-lock.json ]; then npm ci; else npm install; fi

echo "==> Building bin/plugin.js"
npm run build

echo "==> Packing $SDPLUGIN -> $OUT_DIR/"
PACK_ARGS=("$SDPLUGIN" -o "$OUT_DIR" --force)
[ -n "$VERSION" ] && PACK_ARGS+=(--version "$VERSION")
streamdeck pack "${PACK_ARGS[@]}"

echo
echo "Done. Distributable:"
ls -1 "$PLUGIN_DIR/$OUT_DIR"/*.streamDeckPlugin
echo "Install by double-clicking it (or: open the .streamDeckPlugin file)."
