#!/bin/bash
# Reuse installed runtimes across WSL distros at the same canonical absolute paths.
set -euo pipefail
mode="${1:?Expected export or import}"
base="${2:?Expected the existing absolute runtime base}"
[[ "$base" == /home/*/.local/share/kmb-live ]] || { echo 'Expected /home/<user>/.local/share/kmb-live' >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || { echo 'Run this mount helper as root inside WSL.' >&2; exit 2; }
case "$mode" in
export)
    for name in openclaw hermes-source hermes-home; do
        [[ -d "$base/$name" ]] || { echo "Missing existing runtime: $base/$name" >&2; exit 2; }
        mkdir -p "/mnt/wsl/kmb-runtime/$name"
        if ! mountpoint -q "/mnt/wsl/kmb-runtime/$name"; then
            mount --bind "$base/$name" "/mnt/wsl/kmb-runtime/$name"
            mount -o remount,bind,ro "/mnt/wsl/kmb-runtime/$name"
        fi
    done
    mkdir -p /mnt/wsl/kmb-hermes-installs
    if ! mountpoint -q /mnt/wsl/kmb-hermes-installs; then
        mount --bind "$base/hermes-home/installs" /mnt/wsl/kmb-hermes-installs
    fi
    ;;
import)
    for name in openclaw hermes-source hermes-home; do
        [[ -d "/mnt/wsl/kmb-runtime/$name" ]] || { echo 'Export source runtime first.' >&2; exit 2; }
        target="$base/$name"
        [[ ! -L "$target" ]] || { echo "Refusing to replace symlink: $target" >&2; exit 2; }
        mkdir -p "$target"
        if ! mountpoint -q "$target"; then
            [[ -z "$(ls -A "$target")" ]] || { echo "Refusing to hide nonempty directory: $target" >&2; exit 2; }
            mount --bind "/mnt/wsl/kmb-runtime/$name" "$target"
            mount -o remount,bind,ro "$target"
        fi
    done
    # Hermes needs lease/lock writes in its dependency generation directory.
    if ! mountpoint -q "$base/hermes-home/installs"; then
        mount --bind /mnt/wsl/kmb-hermes-installs "$base/hermes-home/installs"
    fi
    ;;
*) echo 'Expected export or import' >&2; exit 2;;
esac
printf 'Runtime %s ready at %s\n' "$mode" "$base"
