#!/usr/bin/env bash
#
# Download Tailwind standalone binary and compile CSS.
# No Node.js required.
#
set -euo pipefail

ARCH="${BUILD_ARCH:-linux-x64}"
BINARY="tailwindcss-${ARCH}"
URL="https://github.com/tailwindlabs/tailwindcss/releases/latest/download/${BINARY}"

cd "$(dirname "$0")/.."

if [ ! -f "$BINARY" ]; then
    echo "Downloading Tailwind standalone (${ARCH})..."
    curl -sLO "$URL"
    chmod +x "$BINARY"
fi

echo "Compiling CSS..."
./"$BINARY" -i static/css/input.css -o static/css/output.css --minify
echo "Done: static/css/output.css"
