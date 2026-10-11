#!/bin/bash
# Open a local run report in the dedicated recording profile on the prepared desktop.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
report="${1:-$repo/examples/openkylin-core/report.html}"
[[ -f "$report" ]] || { echo "Report does not exist: $report" >&2; exit 2; }
unset WAYLAND_DISPLAY
export DISPLAY=":${KMB_DISPLAY_NUMBER:-14}" MOZ_ENABLE_WAYLAND=0
export XDG_RUNTIME_DIR="$HOME/.cache/kmb-desktop/runtime-${KMB_DISPLAY_NUMBER:-14}"
profile="$HOME/.cache/kmb-desktop/firefox-profile"
mkdir -p "$profile"
chmod 700 "$profile"
uri="$(python3 -c 'import sys; from pathlib import Path; print(Path(sys.argv[1]).resolve().as_uri())' "$report")"
exec firefox --no-remote --new-instance --profile "$profile" "$uri"
