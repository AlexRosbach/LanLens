#!/usr/bin/env bash
set -euo pipefail

# Keep the Windows executable and Installed Apps icon aligned with the web logo.
# Requires Python with CairoSVG and ImageMagick. Installation/build uses the
# checked-in ICO and does not need either image-conversion dependency.
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v magick >/dev/null 2>&1; then
  converter=(magick)
elif command -v convert >/dev/null 2>&1; then
  converter=(convert)
else
  echo 'ImageMagick is required to regenerate the Windows agent icon.' >&2
  exit 1
fi

icon_png="$(mktemp --suffix=.png)"
trap 'rm -f -- "$icon_png"' EXIT
python3 -m cairosvg "$repo_root/frontend/public/logo.svg" \
  --output-width 256 --output-height 256 --output "$icon_png"
"${converter[@]}" "$icon_png" \
  -define icon:auto-resize=256,128,64,48,32,24,16 \
  "$repo_root/backend/assets/windows_agent/LanLensAgent.ico"
