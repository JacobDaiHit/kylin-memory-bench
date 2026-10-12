"""Subprocess reference for offline plumbing checks; never a native-agent score."""
import json
import os
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.math_memory.memory_only import view


def main():
    request=json.load(sys.stdin)
    path=Path(request['workspace'])/'reference-records.json'
    records=json.loads(path.read_text()) if path.exists() else []
    before=len(records)
    for line in request['prompt'].splitlines():
        if line.startswith('RECORD='):
            record=json.loads(line[7:])
            if record['id'] not in {r['id'] for r in records}:records.append(record)
    path.write_text(json.dumps(records,ensure_ascii=False))
    match=re.search(r'^HEALTH_QUERY=(.+)$',request['prompt'],re.MULTILINE)
    if match:
        state,_,_=view(records,match[1]);old,_,_=view(records,match[1],historical=True)
        answer={'q01':state.get('d1'),'q02':state.get('branch'),'q03':old.get('d1')}
    else:answer={'stored':True}
    actions=[{'name':'write_file','arguments':{'path':path.name},'status':'success'}] if len(records)>before else []
    print(json.dumps({'text':json.dumps(answer),'actions':actions,
        'memory':{'text':json.dumps(records,ensure_ascii=False),'complete':True},
        'provenance':'offline_reference_subprocess_pid='+str(os.getpid())}))


if __name__=='__main__':main()
