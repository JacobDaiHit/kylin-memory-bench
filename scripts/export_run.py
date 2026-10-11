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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    checked = verify_run(args.source)
    manifest, cases, events, scores = read_run(args.source)
    if manifest['status'] not in ('completed', 'completed_with_errors'):
        parser.error('Only finished runs can be exported; interrupted evidence stays at its original location.')
    if args.destination.exists():
        parser.error('Destination exists; use a new export directory.')
    args.destination.mkdir(parents=True)
    for name in ('manifest.json','dataset.jsonl','config.json','evidence.jsonl','scores.json'):
        shutil.copyfile(args.source/name, args.destination/name)
    render_report(scores, args.destination)
    metadata = {'run_id':manifest['run_id'], 'environment':manifest['environment'],
                'dataset_sha256':manifest['dataset_sha256'], 'implementation_sha256':manifest['implementation_sha256'],
                'cases':len(cases), 'events':len(events), 'repeats':manifest['repeats'],
                'execution_errors':manifest['execution_errors'],
                'presentation_note':'HTML/SVG regenerated with delivery source; original evidence and scores unchanged.',
                'model':'deepseek-flash', 'parameters':{'thinking':'disabled','temperature':0,'max_tokens':2048},
                'retry_policy':'No selective rerun or replacement of failed cases.',
                'native_versions':{'openclaw':'2026.9.8 (fc23bc8)','hermes_commit':'4b8a43719b2a259cea88a72f9f13a2b6962e7ac3'}}
    if args.audit:
        records=[json.loads(line) for line in args.audit.read_text(encoding='utf-8').splitlines() if line]
        metadata['audit_counts']=dict(collections.Counter(r['event'] for r in records))
        usage=collections.Counter()
        for row in records:
            if row['event']=='completion':
                for key,value in row.get('usage',{}).items():
                    if type(value) is int: usage[key]+=value
        metadata['usage']=dict(usage)
        metadata['network_or_guard_failures']=[r for r in records if r['event'] in ('rejected','budget_stop')]
        shutil.copyfile(args.audit, args.destination/'api-audit.jsonl')
    write_json(args.destination/'experiment.json', metadata)
    print(json.dumps(verify_run(args.destination),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
