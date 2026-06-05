#!/bin/sh
# Run build_picker_project.py inside the QGIS bundle's Python environment.
# Mirrors the env recipe in ~/mcp/qgis_mcp/__main__.py (_reexec_into_bundle).
# Build the .gpkg first with: ~/.local/share/gis-venv/bin/python build_basin_gpkg.py
set -eu
BUNDLE=/Applications/QGIS-final-4_0_1.app
RES="$BUNDLE/Contents/Resources"
PYHOME=$([ -d "$RES/python" ] && echo "$RES/python" || ls -d "$RES"/python3* 2>/dev/null | tail -1)
PYBIN=$(ls "$BUNDLE/Contents/MacOS"/python3* 2>/dev/null | head -1)
FW="$BUNDLE/Contents/Frameworks"
HERE=$(cd "$(dirname "$0")" && pwd)

env -i HOME="$HOME" \
  PYTHONPATH="$PYHOME:$PYHOME/lib-dynload:$PYHOME/site-packages" \
  DYLD_FRAMEWORK_PATH="$FW" DYLD_LIBRARY_PATH="$FW" \
  QT_QPA_PLATFORM=offscreen QGIS_MCP_LAUNCHED=1 \
  PROJ_LIB="$RES/qgis/proj" \
  "$PYBIN" "$HERE/build_picker_project.py"
