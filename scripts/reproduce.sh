#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
OUT="${1:-runs/reproduce-$(date +%Y%m%d-%H%M%S)}"
python3 -m kylin_memory_bench doctor
python3 -m kylin_memory_bench validate kylin_memory_bench/data/sample.jsonl
python3 -m unittest discover -s tests -v
python3 -m kylin_memory_bench demo --output "$OUT" --repeats 3
python3 -m kylin_memory_bench verify "$OUT"
printf '\nOpen %s/report.html in your browser.\n' "$OUT"
