#!/bin/bash
# Run in the dedicated openKylin test distribution, after final package build.
set -euo pipefail
deb="$(readlink -f "${1:?Pass the final .deb path}")"
test_user="${2:-kmb}"
[[ "$(id -u)" == 0 ]] || { echo 'Run as root for package lifecycle validation.' >&2; exit 2; }
[[ "$(dpkg-deb -f "$deb" Package)" == kylin-memory-bench ]] || { echo 'Unexpected package name.' >&2; exit 2; }
grep -Eq '^ID=("?openkylin"?)$' /etc/os-release || { echo 'Expected actual openKylin.' >&2; exit 2; }
test_home="$(getent passwd "$test_user" | cut -d: -f6)"
[[ -d "$test_home" ]] || { echo 'Test user home unavailable.' >&2; exit 2; }
output="$test_home/runs/package-validation-$(date +%Y%m%d-%H%M%S)-$$"
printf 'UTC=%s\n' "$(date -u +%FT%TZ)"
printf 'DEB_SHA256=%s\n' "$(sha256sum "$deb" | cut -d' ' -f1)"
dpkg-deb --info "$deb"
dpkg -i "$deb"
kmb --version
runuser -u "$test_user" -- kmb demo --output "$output" --quiet
runuser -u "$test_user" -- kmb verify "$output"
printf 'Installed implementation: '
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["implementation_sha256"])' "$output/manifest.json"
dpkg -r kylin-memory-bench
[[ ! -e /usr/bin/kmb ]] || { echo 'Package launcher survived removal.' >&2; exit 1; }
dpkg -i "$deb"
kmb --version
dpkg-query -W kylin-memory-bench
dpkg --audit
printf 'LIFECYCLE PASS\n'
