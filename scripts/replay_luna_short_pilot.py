"""Offline regrade of public final observations; no native execution claim."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kylin_memory_bench.common import digest
from experiments.memory_stress.v2.calibrate_stress import grade,action_grade


def replay(data,evidence):
    cases=json.loads((data/'cases.evaluator.json').read_text())
    catalog=json.loads((data/'catalog.evaluator.json').read_text())
    payload=json.loads(evidence.read_text())
    if digest(cases)!=payload['cases_sha256']:raise ValueError('Frozen cases differ')
    rows=[];seen=set()
    for item in payload['rows']:
        identity=(item['case_id'],item['agent'])
        if identity in seen:raise ValueError('Duplicate observation')
        seen.add(identity);meta=catalog[item['case_id']]
        if item['condition']!=meta['condition']:raise ValueError('Observation condition changed')
        case=cases[item['case_id']]
        gold=next(c['value']['answer'] for c in case['steps'][-1]['checks'] if c['id']=='strict-answer')
        if gold!=meta['expected']:raise ValueError('Catalog/gold mismatch')
        for artifact in item['artifacts'].values():
            if 'text' in artifact:
                raw=artifact['text'].encode()
                if len(raw)!=artifact['bytes'] or hashlib.sha256(raw).hexdigest()!=artifact['sha256']:raise ValueError('Artifact changed')
        response_grade=grade(gold,item['text'],error=item['error'],output_type=meta['answer_type'])
        final={'error':item['error'],'response':{'text':item['text'],'actions':None},'artifacts':item['artifacts']}
        action=action_grade(meta,final,response_grade)
        rows.append({'task_id':item['task_id'],'agent':item['agent'],'condition':item['condition'],'observed':response_grade['observed'],'content':response_grade['content_task_success'],'task':action['whole_task_success']})
    if len(rows)!=32:raise ValueError('Missing planned final observations')
    groups=[]
    for agent in ('openclaw','hermes'):
        for condition in ('reader_only','memory'):
            batch=[r for r in rows if r['agent']==agent and r['condition']==condition]
            if len(batch)!=8:raise ValueError('Planned denominator changed')
            groups.append({'agent':agent,'condition':condition,'planned':len(batch),'observed':sum(r['observed'] for r in batch),'content_correct':sum(r['content'] for r in batch),'task_success':sum(r['task'] for r in batch)})
    return groups


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--check',type=Path)
    a=p.parse_args();groups=replay(a.data,a.evidence)
    if a.check and groups!=json.loads(a.check.read_text())['groups']:raise ValueError('Published scores differ from regrade')
    print(json.dumps({'valid':True,'groups':groups,'scope':'Final content/format/file results only; full private native chain and redacted tool visibility are not reverified.'}))

if __name__=='__main__':main()
