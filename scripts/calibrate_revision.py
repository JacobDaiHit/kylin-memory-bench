#!/usr/bin/env python3
"""Evaluate the sixteen prespecified revision fixtures; no model or network calls."""
import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.math_memory.memory_v31 import grade
from kylin_memory_bench.scoring import evaluate


def calculate(path=ROOT/'docs/evidence/scoring-revision-fixtures.jsonl'):
    fixtures=[json.loads(line) for line in Path(path).read_text().splitlines() if line]
    if len(fixtures)!=16 or len({r['id'] for r in fixtures})!=16:
        raise ValueError('Expected sixteen unique frozen fixtures')
    results=[]
    for row in fixtures:
        if row['kind']=='response_envelope':
            result=grade(row['case'],row['gold'],row['response'])
            actual={k:result[k] for k in ('correct_count','observed_count','format_status')}
        else:
            result=evaluate(row['check'],row['event'])
            actual={k:result[k] for k in ('status','category')}
        results.append({**row,'actual':actual,'matched':actual==row['expected']})
    false_passes=sum(r['kind']!='response_envelope' and r['actual']['status']=='pass' and r['expected']['status']!='pass' for r in results)
    return {'kind':'offline_fixed_revision_calibration','paid_calls':0,'fixtures':results,
            'summary':{'count':16,'matched':sum(r['matched'] for r in results),'false_passes':false_passes},
            'passed':all(r['matched'] for r in results) and false_passes==0,
            'fixture_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'scope':'AI-assisted prespecified contract fixtures, not independent human accuracy, native memory health or difficulty evidence.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check',action='store_true')
    args=p.parse_args();report=calculate()
    if args.check:
        if json.loads((args.output/'results.json').read_text())!=report:raise ValueError('Calibration report differs from replay')
    else:
        args.output.mkdir(parents=True,exist_ok=False)
        (args.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        body=''.join('<tr><td>'+html.escape(r['id'])+'</td><td>'+html.escape(r['rationale'])+'</td><td>'+html.escape(json.dumps(r['expected'],ensure_ascii=False))+'</td><td>'+html.escape(json.dumps(r['actual'],ensure_ascii=False))+'</td></tr>' for r in report['fixtures'])
        (args.output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>修订契约校准</title><h1>16条固定修订校准</h1><p>离线构造样例；不代表独立人审、原生能力或难度通过。</p><table border="1"><tr><th>编号</th><th>预设理由</th><th>预期</th><th>实际</th></tr>'+body+'</table>',encoding='utf-8')
    print(json.dumps(report['summary']));return 0 if report['passed'] else 3


if __name__=='__main__':raise SystemExit(main())
