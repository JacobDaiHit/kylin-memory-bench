"""Six preselected oracle-evidence reader checks, separate from agent memory."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.chatgpt_plan import atomic_private, TARGET
from scripts.chatgpt_plan_bridge import Bridge, append
from experiments.memory_stress.v2.calibrate_stress import grade

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'experiments/memory_stress/v2/development-v1-1/pilot'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-six-requests',action='store_true')
    args=parser.parse_args()
    if not args.allow_six_requests: parser.error('Explicit --allow-six-requests required.')
    args.output.mkdir(parents=True,exist_ok=False,mode=0o700)
    rows=[json.loads(s) for s in (DATA/'reader-only.learner.jsonl').read_text().splitlines()]
    gold=json.loads((DATA/'reader-only.gold.evaluator.json').read_text())
    if len(rows)!=6 or set(gold)!={r['id'] for r in rows}: raise ValueError('preselected_manifest_changed')
    bridge=Bridge(args.output/'requests',limit=6)
    atomic_private(args.output/'protocol.json',{'protocol':'luna-reader-only-0.1','model':TARGET,'server_output_cap':None,
        'benchmark_memory_score':False,'ids':[r['id'] for r in rows],'sha256':{
        name:hashlib.sha256((DATA/name).read_bytes()).hexdigest() for name in ['reader-only.learner.jsonl','reader-only.gold.evaluator.json']}})
    results=[]
    try:
        for row in rows:
            bridge.context=row['id'];entry={'id':row['id'],'status':'started'}
            append(args.output/'events.jsonl',entry)
            try:
                # Only learner messages reach the model. No gold or evaluator files.
                response=bridge.invoke({'model':TARGET,'messages':row['messages']})
                text=response['choices'][0]['message']['content']
                entry.update(status='completed',text=text,grade=grade(gold[row['id']]['expected'],text,output_type=gold[row['id']]['answer_type']))
            except Exception as exc:
                entry.update(status='execution_error',error_type=type(exc).__name__,grade=grade(gold[row['id']]['expected'],'',error=type(exc).__name__,output_type=gold[row['id']]['answer_type']))
            append(args.output/'events.jsonl',entry);results.append(entry)
            print(row['id'],entry['status'],entry['grade']['status'],flush=True)
    finally: atomic_private(args.output/'results.json',{'benchmark_memory_score':False,'planned':6,'results':results})

if __name__=='__main__':main()
