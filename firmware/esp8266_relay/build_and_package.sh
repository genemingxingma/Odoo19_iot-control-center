#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKETCH_DIR="$ROOT_DIR/esp8266_relay"
SKETCH_FILE="$SKETCH_DIR/esp8266_relay.ino"
OUT_DIR="$ROOT_DIR/out"
LIB_DIR="/Users/mingxingmac/Documents/Codex/.local/arduino-libs"
FQBN="esp8266:esp8266:generic"

CLI="${ARDUINO_CLI_PATH:-/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli}"
if [[ ! -x "$CLI" ]]; then
  echo "arduino-cli not found: $CLI"
  exit 1
fi

if [[ ! -f "$SKETCH_FILE" ]]; then
  echo "sketch not found: $SKETCH_FILE"
  exit 1
fi

VERSION="$(awk -F'\"' '/FIRMWARE_VERSION/{print $2; exit}' "$SKETCH_FILE")"
if [[ -z "${VERSION:-}" ]]; then
  echo "cannot parse FIRMWARE_VERSION from $SKETCH_FILE"
  exit 1
fi

mkdir -p "$OUT_DIR"

"$CLI" compile \
  --fqbn "$FQBN" \
  --libraries "$LIB_DIR" \
  --output-dir "$OUT_DIR" \
  "$SKETCH_DIR"

BIN_SRC="$OUT_DIR/esp8266_relay.ino.bin"
BIN_DST="$OUT_DIR/esp8266_relay_v${VERSION}.bin"
cp "$BIN_SRC" "$BIN_DST"

echo "Build ok"
echo "Version: $VERSION"
echo "Output:  $BIN_DST"
