"""Independently solve serialized short-pilot inputs; no models or suite Oracle."""
import argparse,json,hashlib
from pathlib import Path

def check(root):
    cases=json.loads((root/'cases.evaluator.json').read_text());catalog=json.loads((root/'catalog.evaluator.json').read_text());checks=[]
    for case in cases.values():
     if not case['id'].startswith('reader'):continue
     prompt=case['steps'][-1]['prompt'];events=[json.loads(l[6:]) for l in prompt.splitlines() if l.startswith('EVENT=')]
     cancelled=set()
     for e in events:
      if e['kind']=='cancel' and e['status']=='accepted':cancelled.update((e['target_id'],key) for key in e['fields'])
     def field(subject,scope,key):
      values=[e['fields'][key] for e in events if e['status']=='accepted' and e['kind'] in ('assert','feedback') and e['subject']==str(subject) and e['scope']==scope and key in e['fields'] and (e['id'],key) not in cancelled]
      return values[-1] if values else None
     task=next((json.loads(l[5:]) for l in prompt.splitlines() if l.startswith('TASK=')),None)
     if task:
      values=dict(task['provided'])
      for key in task['required_fields']:values[key]=field(task['subject'],task['scope'],key)
      matches=[o['id'] for o in task['options'] if dict(zip(task['option_fields'],o['values']))==values]
      answer=matches[0] if len(matches)==1 else None
     else:
      q=json.loads(next(l[len('查询：'):] for l in prompt.splitlines() if l.startswith('查询：')));subject,scope=q['subject'],q['scope'];seen=set();answer=None
      for i in range(10):
       if (str(subject),scope) in seen:raise AssertionError('Cycle')
       seen.add((str(subject),scope));value=field(subject,scope,'directory')
       if value is not None:answer=value;break
       keys=[k for k in ('d1','customer','profile','template','bundle','route') if field(subject,scope,k) is not None]
       if len(keys)!=1:raise AssertionError('Ambiguous graph edge')
       subject=field(subject,scope,keys[0]);scope='registry'
     meta=catalog[case['id']];checks.append({'case_id':case['id'],'family':meta['family'],'tier':meta['tier'],'match':answer==meta['expected'],'raw_evidence_records':len(events)})
     if answer!=meta['expected']:raise AssertionError('Independent input/gold mismatch')
    summary={'method':'Independent serialized-prompt state ledger and candidate/graph resolution; does not call suite Oracle or models.','checked':len(checks),'matched':sum(c['match'] for c in checks),'checks':checks,'cases_file_sha256':hashlib.sha256((root/'cases.evaluator.json').read_bytes()).hexdigest()}
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument("--run",type=Path,required=True);p.add_argument("--output",type=Path);a=p.parse_args();result=check(a.run)
    if a.output:a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result))

if __name__=="__main__":main()
