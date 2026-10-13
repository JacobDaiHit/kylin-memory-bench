#!/usr/bin/env python3
"""Export immutable run evidence and regenerate only presentation files."""
import argparse
import collections
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.runner import verify_run, read_run
from kylin_memory_bench.report import render_report
from kylin_memory_bench.common import read_json, write_json

PUBLIC_AUDIT_FIELDS = frozenset(('at', 'event', 'model', 'thinking', 'temperature',
    'max_output_tokens', 'request_limit', 'stream_transport', 'balance_check_interval_seconds',
    'price_bound_cny_per_million', 'request_sha256', 'started_at', 'usage',
    'finish_reasons', 'context', 'balance_fresh', 'model_response_preserved'))


def public_audit(records):
    """Whitelist generated metadata; never export account values or free-form errors."""
    return [{**{k: v for k, v in row.items() if k in PUBLIC_AUDIT_FIELDS},
             'private_fields_removed': sorted(set(row) - PUBLIC_AUDIT_FIELDS)}
            for row in records]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--chatgpt-plan', action='store_true',
                        help='Label the opt-in Luna route accurately; no enforced sampling/output cap')
    parser.add_argument('--allow-interrupted', action='store_true',
                        help='Explicitly preserve an aborted attempt; never call it a finished experiment')
    args = parser.parse_args()
    manifest, cases, events, scores = read_run(args.source)
    if (args.source/'scores.json').exists():
        verify_run(args.source)
    elif manifest['status'] != 'interrupted':
        parser.error('Finished source is missing original scores.')
    if manifest['status'] not in ('completed', 'completed_with_errors') and not (
            args.allow_interrupted and manifest['status'] == 'interrupted'):
        parser.error('Only finished runs can be exported; interrupted evidence stays at its original location.')
    if args.destination.exists():
        parser.error('Destination exists; use a new export directory.')
    args.destination.mkdir(parents=True)
    for name in ('manifest.json','dataset.jsonl','config.json','evidence.jsonl'):
        shutil.copyfile(args.source/name, args.destination/name)
    if (args.source/'scores.json').exists():
        shutil.copyfile(args.source/'scores.json', args.destination/'scores.json')
    else:
        write_json(args.destination/'scores.json', scores)
    render_report(scores, args.destination)
    metadata = {'run_id':manifest['run_id'], 'environment':manifest['environment'],
                'dataset_sha256':manifest['dataset_sha256'], 'implementation_sha256':manifest['implementation_sha256'],
                'cases':len(cases), 'events':len(events), 'repeats':manifest['repeats'],
                'execution_errors':manifest['execution_errors'],
                'presentation_note':'HTML/SVG regenerated with delivery source; original evidence and scores unchanged.',
                'model':'deepseek-flash', 'parameters':{'thinking':'disabled','temperature':0,'max_tokens':2048},
                'retry_policy':'No selective rerun or replacement of failed cases.',
                'native_versions':{'openclaw':'2026.9.8 (fc23bc8)','hermes_commit':'4b8a43719b2a259cea88a72f9f13a2b6962e7ac3'}}
    metadata['status'] = manifest['status']
    if args.chatgpt_plan:
        from scripts.chatgpt_plan import TARGET
        metadata['model'] = TARGET
        metadata['parameters'] = {'reasoning_effort': 'none', 'server_output_cap': None,
                                  'sampling_parameters_enforced': False}
        metadata['scope'] = 'Single-round operational demonstration; not merged with historical statistics.'
    limits = {step['id']:step['output_tokens'] for case in cases for step in case['steps'] if 'output_tokens' in step}
    if limits and not args.chatgpt_plan:
        metadata['parameters']['max_tokens'] = max(limits.values())
        metadata['parameters']['per_step_output_tokens'] = limits
        metadata['parameters']['source'] = 'Frozen dataset and loopback proxy cap; verify actual audit as well.'
    metadata['scores_origin'] = ('original' if (args.source/'scores.json').exists() else
                                'derived independent replay of interrupted evidence; missing steps remain unknown; not a completed three-trial result')
    if args.audit:
        records=public_audit([json.loads(line) for line in args.audit.read_text(encoding='utf-8').splitlines() if line])
        metadata['audit_counts']=dict(collections.Counter(r['event'] for r in records))
        usage=collections.Counter()
        for row in records:
            if row['event']=='completion':
                for key,value in row.get('usage',{}).items():
                    if type(value) is int: usage[key]+=value
        metadata['usage']=dict(usage)
        metadata['network_or_guard_failures']=[r for r in records if r['event'] in ('rejected','budget_stop')]
        (args.destination/'api-audit.jsonl').write_text(
            ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in records), encoding='utf-8')
        metadata['audit_privacy_note']='Whitelist metadata export; private account values and free-form errors removed. Original local audit is retained.'
    write_json(args.destination/'experiment.json', metadata)
    print(json.dumps(verify_run(args.destination),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
