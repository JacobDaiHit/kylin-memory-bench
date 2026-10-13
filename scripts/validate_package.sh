#!/bin/bash
# Run in the dedicated openKylin test distribution, after final package build.
set -euo pipefail
deb="$(readlink -f "${1:?Pass the final .deb path}")"
test_user="${2:-kmb}"
[[ "$(id -u)" == 0 ]] || { echo 'Run as root for package lifecycle validation.' >&2; exit 2; }
[[ "$(dpkg-deb -f "$deb" Package)" == kylin-memory-bench ]] || { echo 'Unexpected package name.' >&2; exit 2; }
expected_version="$(dpkg-deb -f "$deb" Version)"
launcher=/usr/bin/kmb
grep -Eq '^ID=("?openkylin"?)$' /etc/os-release || { echo 'Expected actual openKylin.' >&2; exit 2; }
test_home="$(getent passwd "$test_user" | cut -d: -f6)"
[[ -d "$test_home" ]] || { echo 'Test user home unavailable.' >&2; exit 2; }
output="$test_home/runs/package-validation-$(date +%Y%m%d-%H%M%S)-$$"
printf 'UTC=%s\n' "$(date -u +%FT%TZ)"
printf 'DEB_SHA256=%s\n' "$(sha256sum "$deb" | cut -d' ' -f1)"
dpkg-deb --info "$deb"
dpkg -i "$deb"
[[ "$($launcher --version)" == "$expected_version" ]] || { echo 'Installed launcher version mismatch.' >&2; exit 1; }
printf 'INSTALLED_LAUNCHER=%s\nINSTALLED_VERSION=%s\n' "$launcher" "$expected_version"
printf 'PATH_KMB=%s\n' "$(command -v kmb)"
runuser -u "$test_user" -- "$launcher" demo --output "$output" --quiet
runuser -u "$test_user" -- "$launcher" verify "$output"
printf 'Installed implementation: '
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["implementation_sha256"])' "$output/manifest.json"
python3 - "$output/manifest.json" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '/usr/share/kylin-memory-bench')
from kylin_memory_bench.common import digest
root = Path('/usr/share/kylin-memory-bench/kylin_memory_bench')
expected = digest({p.name: p.read_text(encoding='utf-8') for p in sorted(root.glob('*.py'))})
assert json.loads(Path(sys.argv[1]).read_text())['implementation_sha256'] == expected
print('INSTALLED_IMPLEMENTATION_MATCH=1')
PY
dpkg -r kylin-memory-bench
[[ ! -e /usr/bin/kmb ]] || { echo 'Package launcher survived removal.' >&2; exit 1; }
dpkg -i "$deb"
[[ "$($launcher --version)" == "$expected_version" ]] || { echo 'Reinstalled launcher version mismatch.' >&2; exit 1; }
"$launcher" --version
dpkg-query -W kylin-memory-bench
dpkg --audit
printf 'LIFECYCLE PASS\n'
