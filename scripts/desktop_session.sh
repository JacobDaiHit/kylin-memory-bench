#!/bin/bash
# Called by start_desktop.sh, all components share one D-Bus session.
set -u
children=()
cleanup() { for child in "${children[@]}"; do kill "$child" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM
mkdir -p "$HOME/Desktop" "$HOME/Documents" "$HOME/Downloads" "$HOME/.config"
if [[ ! -f "$HOME/.config/user-dirs.dirs" ]]; then
printf 'XDG_DESKTOP_DIR="$HOME/Desktop"\nXDG_DOCUMENTS_DIR="$HOME/Documents"\nXDG_DOWNLOAD_DIR="$HOME/Downloads"\n' > "$HOME/.config/user-dirs.dirs"
fi
gsettings set org.mate.background picture-filename /usr/share/backgrounds/fluent-color.png
gsettings set org.mate.background draw-background true
gsettings set org.mate.background show-desktop-icons true
gsettings set org.gnome.desktop.background picture-uri file:///usr/share/backgrounds/fluent-color.png
kwin_x11 --replace >"$KMB_DESKTOP_LOG/kwin.log" 2>&1 &
children+=("$!")
ukui-settings-daemon >"$KMB_DESKTOP_LOG/settings.log" 2>&1 &
children+=("$!")
peony-qt-desktop -w -d >"$KMB_DESKTOP_LOG/peony.log" 2>&1 &
children+=("$!")
ukui-panel >"$KMB_DESKTOP_LOG/panel.log" 2>&1 &
children+=("$!")
sleep 2
xterm -fa 'DejaVu Sans Mono' -fs 12 -geometry 95x25+80+70 -title 'openKylin / Kylin Memory Bench' -e bash -lc 'cat /etc/os-release; python3 --version; cd "$KMB_PROJECT_ROOT"; python3 -m kylin_memory_bench --version; exec bash' >"$KMB_DESKTOP_LOG/terminal.log" 2>&1 &
children+=("$!")
wait
