#!/bin/bash
# Minimal UKUI X11 desktop for recording on an existing openKylin WSL2 install.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
display_number="${KMB_DISPLAY_NUMBER:-14}"
web_port="${KMB_WEB_PORT:-6084}"
vnc_port="${KMB_VNC_PORT:-5914}"
for value in "$display_number" "$web_port" "$vnc_port"; do
    [[ "$value" =~ ^[0-9]+$ ]] || { echo "Ports/display must be numeric" >&2; exit 2; }
done
if [[ -e "/tmp/.X11-unix/X$display_number" ]]; then
    echo "Display :$display_number already exists; keep its current session or select another number." >&2
    exit 2
fi
for command in Xvfb x11vnc websockify dbus-run-session kwin_x11 peony-qt-desktop ukui-panel xterm firefox; do
    command -v "$command" >/dev/null || { echo "Missing component: $command (see docs/openkylin.md)" >&2; exit 2; }
done
unset WAYLAND_DISPLAY
export DISPLAY=":$display_number"
export XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=UKUI XDG_SESSION_DESKTOP=UKUI
export QT_QPA_PLATFORM=xcb QT_XCB_GL_INTEGRATION=none KWIN_COMPOSE=N
export XDG_RUNTIME_DIR="$HOME/.cache/kmb-desktop/runtime-$display_number"
export KMB_DESKTOP_LOG="$HOME/.cache/kmb-desktop/logs-$display_number"
export KMB_PROJECT_ROOT="$repo"
mkdir -p "$XDG_RUNTIME_DIR" "$KMB_DESKTOP_LOG"
chmod 700 "$XDG_RUNTIME_DIR" "$KMB_DESKTOP_LOG"
children=()
cleanup() { for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
Xvfb "$DISPLAY" -screen 0 1600x900x24 -ac -nolisten tcp >"$KMB_DESKTOP_LOG/xvfb.log" 2>&1 &
children+=("$!")
for attempt in {1..30}; do
    [[ -S "/tmp/.X11-unix/X$display_number" ]] && break
    sleep .2
done
dbus-run-session -- bash "$repo/scripts/desktop_session.sh" >"$KMB_DESKTOP_LOG/session.log" 2>&1 &
children+=("$!")
x11vnc -display "$DISPLAY" -localhost -rfbport "$vnc_port" -nopw -forever -shared -noxdamage >"$KMB_DESKTOP_LOG/vnc.log" 2>&1 &
children+=("$!")
websockify --web=/usr/share/novnc "127.0.0.1:$web_port" "127.0.0.1:$vnc_port" >"$KMB_DESKTOP_LOG/web.log" 2>&1 &
children+=("$!")
printf '\nDesktop: http://127.0.0.1:%s/vnc.html?autoconnect=1&resize=scale\n' "$web_port"
printf 'Leave this terminal running. Ctrl+C closes only this desktop. Logs: %s\n' "$KMB_DESKTOP_LOG"
wait -n "${children[@]}"
