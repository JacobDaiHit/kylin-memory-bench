#!/bin/sh
# Native acceptance: fails explicitly on any other distribution.
set -eu
cd "$(dirname "$0")/.."
python3 -c 'from kylin_memory_bench.runner import platform_info; import sys; p=platform_info(); print(p); sys.exit(0 if p["is_openkylin"] else 2)'
python3 -m unittest discover -s tests -v
OUT="${1:-runs/openkylin-$(date +%Y%m%d-%H%M%S)}"
python3 -m kylin_memory_bench demo --output "$OUT/baselines" --repeats 3
python3 -m kylin_memory_bench verify "$OUT/baselines"
if [ "$#" -ge 2 ]; then
    python3 -m kylin_memory_bench doctor --config "$2"
    python3 -m kylin_memory_bench run --config "$2" --output "$OUT/agents" --repeats 3
    python3 -m kylin_memory_bench verify "$OUT/agents"
fi
