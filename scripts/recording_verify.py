"""Offline recording command: originals pass, a changed disposable copy fails."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import BenchError
from kylin_memory_bench.runner import verify_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = ROOT/'examples/openkylin-core'
    original = verify_run(source)
    print('ORIGINAL VERIFIED:', original['run_id'])
    for name in ('manifest.json', 'config.json', 'dataset.jsonl', 'scores.json', 'evidence.jsonl'):
        shutil.copyfile(source/name, args.output/name)
    lines = (args.output/'evidence.jsonl').read_text(encoding='utf-8').splitlines()
    event = json.loads(lines[0])
    event['prompt'] += ' RECORDING_TAMPER_TEST'
    lines[0] = json.dumps(event, ensure_ascii=False)
    (args.output/'evidence.jsonl').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    try:
        verify_run(args.output)
    except BenchError as exc:
        print('TAMPER REJECTED:', str(exc))
    else:
        raise RuntimeError('Tampered copy unexpectedly passed')
    print('Historical original was not modified; no model calls.')


if __name__ == '__main__':
    main()
