#!/usr/bin/env python3
"""Read-only comparison with the frozen 0.2.0 scorer; never rewrite old scores."""
import argparse
import hashlib
import sys
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import canonical, file_digest, read_json, write_json
from kylin_memory_bench.runner import read_run
from kylin_memory_bench.scoring import evaluate, score_run


def legacy_scorer():
    archive = ROOT / 'reproducibility/experiment-source-0.2.0.zip'
    with zipfile.ZipFile(archive) as source:
        code = source.read('experiment-source-0.2.0/kylin_memory_bench/scoring.py')
    module = types.ModuleType('kylin_memory_bench.frozen_scoring_020')
    exec(compile(code, 'frozen-0.2.0/scoring.py', 'exec'), module.__dict__)
    return module, hashlib.sha256(code).hexdigest()


def calculate():
    old, old_hash = legacy_scorer()
    comparisons = []
    for name in ('openkylin-core', 'openkylin-challenge'):
        directory = ROOT / 'examples' / name
        manifest, cases, events, current = read_run(directory)
        previous = old.score_run(manifest, cases, events)
        saved = read_json(directory / 'scores.json')
        changes = []
        for a, b in zip(previous['agents'], current['agents']):
            for before, after in zip(a['cases'], b['cases']):
                for x, y in zip(before['checks'], after['checks']):
                    if canonical(x) != canonical(y):
                        changes.append({'agent_id': a['id'], 'trial': before['trial'],
                                        'case_id': before['case_id'], 'before': x, 'after': y})
        comparisons.append({'suite': name, 'run_id': manifest['run_id'],
                            'frozen_scores_match_020': canonical(saved) == canonical(previous),
                            'current_scores_match_020': canonical(previous) == canonical(current),
                            'changed_checks': changes,
                            'source_sha256': {n: file_digest(directory / n) for n in
                                              ('manifest.json', 'dataset.jsonl', 'evidence.jsonl', 'scores.json')}})
    fixtures = [read_json_row for read_json_row in
                (__import__('json').loads(line) for line in
                 (ROOT / 'docs/evidence/scoring-calibration.jsonl').read_text().splitlines() if line.strip())]
    fixture_changes = []
    for row in fixtures:
        before, after = old.evaluate(row['check'], row['event']), evaluate(row['check'], row['event'])
        if canonical(before) != canonical(after):
            fixture_changes.append({'id': row['id'], 'expected': row['expected'],
                                    'before': before, 'after': after})
    return {'schema_version': '1.0', 'kind': 'versioned_scoring_comparison',
            'old_version': '0.2.0', 'new_version': '0.2.1',
            'old_scorer_sha256': old_hash,
            'new_scorer_sha256': file_digest(ROOT / 'kylin_memory_bench/scoring.py'),
            'scope': 'Strict JSON artifact parsing; response code-fence acceptance remains unchanged. Original results are read only.',
            'historical_runs': comparisons, 'calibration_changed_fixtures': fixture_changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--check', type=Path)
    args = parser.parse_args()
    result = calculate()
    if args.check:
        if canonical(read_json(args.check)) != canonical(result):
            raise SystemExit('Scorer comparison differs from independent replay')
    else:
        if args.output.exists():
            raise SystemExit('Refusing to overwrite comparison')
        write_json(args.output, result)
    print('SCORER COMPARISON: {} historical changed checks; {} calibration fixture changes.'.format(
        sum(len(r['changed_checks']) for r in result['historical_runs']),
        len(result['calibration_changed_fixtures'])))


if __name__ == '__main__':
    main()
