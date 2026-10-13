"""Frozen 160-history native memory + isolated reader-only comparison.

No cumulative monetary/request cap. Every case runs once. A STOP file prevents
new cases; completed/failed/interrupted shards are never silently rerun.
"""
import argparse
import concurrent.futures
import copy
import datetime
import hashlib
import json
import os
import random
import shutil
import threading
import time
from collections import Counter
from pathlib import Path

from kylin_memory_bench.common import canonical,digest,read_json,write_json
from kylin_memory_bench.runner import execute,read_run,verify_run
from experiments.memory_stress.v2.suite import build_case,collect_slots,verify_prepared
from experiments.memory_stress.v2.calibrate_stress import grouped_summary
from scripts.chatgpt_plan import atomic_private,TARGET
from scripts.chatgpt_plan_bridge import Bridge,append
from scripts.plan_native_config import full_configurations
from scripts.plan_reader_replay import read_reader,verify_reader
from scripts.run_plan_health import ROOT,RUNTIME

DATA=ROOT/'experiments/memory_stress/v2/development-v2'


def validate_preflight(memory_record,health_record):
    status=json.loads(memory_record['results'][1]['output'])[0]
    hits=json.loads(memory_record['results'][2]['output'])['results']
    if not status['embeddingProbe']['ok'] or not status['status']['vector']['semanticAvailable'] or not hits:
        raise ValueError('Native vector search preflight failed')
    if status['status']['model']!='BAAI/bge-small-zh-v1.5': raise ValueError('Embedding model changed')
    for agent in ('openclaw','hermes'):
        rows={r['stage']:r for r in health_record['results'] if r['agent']==agent}
        if set(rows)!={'learn','recall','isolation'} or any(r['status']!='completed' for r in rows.values()):
            raise ValueError('Native health incomplete')
        if not all(rows[s].get('exact_content_match') for s in ('recall','isolation')):
            raise ValueError('Native memory/isolated refusal health failed')
    return True


def prepare(root,embedding_url,jobs):
    verify_prepared(DATA)
    root.mkdir(parents=True,exist_ok=False,mode=0o700)
    frozen=root/'frozen';shutil.copytree(DATA,frozen/'data')
    # Exact source snapshot remains runnable if the working tree changes later.
    source_sha={}
    for directory in ['kylin_memory_bench','experiments','scripts','configs']:
        for p in (ROOT/directory).rglob('*'):
            if not p.is_file() or not (p.suffix in ('.py','.sh') or p.name.endswith('.example.json') or p.name=='viewer.html'): continue
            name=p.relative_to(ROOT);target=frozen/'source'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(p,target);source_sha[name.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    worlds=[json.loads(x) for x in (DATA/'worlds.evaluator.jsonl').read_text().splitlines()]
    if len(worlds)!=160: raise ValueError('Expected all 160 histories')
    random.Random(20261013).shuffle(worlds)
    original_cases={c['id']:c for file in DATA.glob('native-*.jsonl')
                    for c in (json.loads(line) for line in file.read_text().splitlines())}
    original_catalog=read_json(DATA/'case-catalog.evaluator.json')
    tasks=[];catalog={};cases={}
    for index,world in enumerate(worlds):
        query=next(q for q in world['queries'] if q['role']=='primary')
        memory,meta=build_case(world,query['id'],'memory')
        # Preserve the exact original prompt bytes, including EVENT key order.
        memory=copy.deepcopy(original_cases[memory['id']]);meta=copy.deepcopy(original_catalog[memory['id']])
        reader,reader_meta=build_case(world,query['id'],'oracle_evidence')
        reader['id']='reader-'+reader['id'];reader['title']=reader['id'];reader['steps']=reader['steps'][-1:]
        reader['score_note']='Native one-turn oracle-evidence reader-only control; not the historical five-condition protocol.'
        reader_meta.update(case_id=reader['id'],condition='reader_only',case_sha256=digest(reader),history_utf8_bytes=0)
        for case,detail in [(memory,meta),(reader,reader_meta)]: cases[case['id']]=case;catalog[case['id']]=detail
        agents=('openclaw','hermes') if index%2==0 else ('hermes','openclaw')
        for agent in agents:
            for condition,case in [('reader_only',reader),('memory',memory)]:
                tasks.append({'id':'%04d-%s-%s'%(index,agent,condition),'agent':agent,'case_id':case['id'],
                              'scenario_id':world['scenario_id'],'condition':condition,'trial':0})
    bins=root/'bin';bins.mkdir()
    for kind in ('openclaw','hermes'):
        target=bins/(kind+'-isolated');shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh',target);target.chmod(0o700)
    write_json(frozen/'cases.json',cases);write_json(frozen/'catalog.json',catalog)
    write_json(root/'protocol.json',{'protocol':'luna-native-stress-full-1','status':'frozen','model':TARGET,
        'histories':160,'repeats':1,'conditions':['memory','reader_only'],'jobs':jobs,'tasks':tasks,
        'memory_agent_turns':sum(len(cases[t['case_id']]['steps']) for t in tasks if t['condition']=='memory'),
        'reader_agent_turns':sum(len(cases[t['case_id']]['steps']) for t in tasks if t['condition']=='reader_only'),
        'cumulative_request_cap':None,'server_output_cap':None,'embedding_url':embedding_url,
        'embedding_model':'BAAI/bge-small-zh-v1.5','cases_sha256':digest(cases),'catalog_sha256':digest(catalog),
        'source_sha256':source_sha,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'limits':['Native turn timeout 180 seconds. No automatic reruns. Three consecutive execution-error cases stop new scheduling; ordinary incorrect answers do not.','Native tools and memory mechanisms differ and remain disclosed.',
        'Reader-only supplies raw necessary evidence with native tools, including artifact tasks, in a fresh workspace.',
        'Public reserved split is reported separately; not a blind test. One repetition cannot establish stable ranking.',
        'Transport/configuration failures and unexecuted slots stay in the planned denominator.']})
    return root


def checkpoint(root,protocol):
    states={};observed=0;started_turns=0
    for task in protocol['tasks']:
        record=root/'task-state'/(task['id']+'.json')
        state=read_json(record) if record.exists() else {'status':'not_started'}
        states[task['id']]=state['status']
        manifest=root/'shards'/task['id']/'manifest.json'
        if manifest.exists():
            try: observed+=read_json(manifest).get('event_count',0)
            except (OSError,ValueError): pass
    payload={'status':'stopping' if (root/protocol.get('stop_file','STOP')).exists() else 'running','planned_cases':len(states),
             'case_status_counts':dict(Counter(states.values())),'observed_agent_turns':observed,
             'planned_agent_turns':protocol['memory_agent_turns']+protocol['reader_agent_turns'],
             'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    atomic_private(root/protocol.get('progress_file','progress.json'),payload)
    return payload


def report(root):
    protocol=read_json(root/'protocol.json');cases=read_json(root/'frozen/cases.json');catalog=read_json(root/'frozen/catalog.json')
    rows=[];verification=[]
    for task in protocol['tasks']:
        shard=root/'shards'/task['id'];case=cases[task['case_id']]
        if (shard/'scores.json').exists():
            if task['condition']=='reader_only':
                validity=verify_reader(shard,case);manifest,recorded,events,_=read_reader(shard,case)
            else:
                validity=verify_run(shard);manifest,recorded,events,_=read_run(shard)
            if recorded != [case]: raise ValueError('Shard differs from frozen case')
            verification.append({'task':task['id'],**validity})
            collected=collect_slots(manifest,recorded,events,catalog)
        else:
            manifest={'agents':[{'id':task['agent']}],'repeats':1}
            collected=collect_slots(manifest,[case],[],catalog)
        for row in collected: row['task_id']=task['id'];rows.append(row)
    result={'protocol':protocol['protocol'],'histories':160,'planned_cases':640,'rows':rows,
            'summary':grouped_summary(rows),'verification':verification,
            'claim_limit':'One round, whole histories. Report development/reserved and reader/memory separately. No stable ranking.'}
    write_json(root/'analysis.json',result)
    # A small portable local report; raw native prompts stay in private shards.
    from html import escape
    lines=['<!doctype html><meta charset="utf-8"><title>Luna 全量测试</title>',
           '<h1>Luna 全量测试</h1><p>160 条历史；两款 Agent；一轮。memory 与 reader_only 分开报告。</p>',
           '<p>未完成和执行错误保留在分母；单轮不支持稳定排名。所有数字对应 analysis.json。</p>',
           '<table border="1"><tr><th>Agent</th><th>条件</th><th>内容正确</th><th>任务成功</th><th>有效观测</th><th>计划数</th></tr>']
    for agent in ['openclaw','hermes']:
        for condition in ['memory','reader_only']:
            batch=[r for r in rows if r['agent']==agent and r['condition']==condition]
            counts=[sum(r['grade']['content_task_success'] for r in batch),sum(r['action']['whole_task_success'] for r in batch),sum(r['grade']['observed'] for r in batch),len(batch)]
            lines.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [agent,condition,*counts])+'</tr>')
    lines.append('</table><p><a href="analysis.json">逐题结果与复核状态</a></p>')
    (root/'report.html').write_text('\n'.join(lines),encoding='utf-8')
    return result


def run(root):
    protocol=read_json(root/'protocol.json');cases=read_json(root/'frozen/cases.json')
    if digest(cases)!=protocol['cases_sha256']: raise ValueError('Frozen cases changed')
    for name,expected in protocol['source_sha256'].items():
        path=ROOT/name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Execution source changed; use the frozen source snapshot: '+name)
    (root/'task-state').mkdir(exist_ok=True);(root/'requests').mkdir(exist_ok=True)
    (root/'shards').mkdir(exist_ok=True)
    # Each worker has a distinct local key. OAuth access is serialized by the
    # bridge module lock; no bearer is passed to agents or the embedding service.
    workers=[]
    for i in range(protocol['jobs']):
        sequence=sum(1 for _ in (root/'requests').glob('worker-%d-*'%i))
        bridge=Bridge(root/'requests'/('worker-%d-%03d'%(i,sequence)),limit=None,deadline_seconds=None)
        key_name='KMB_PLAN_KEY_%d'%i;os.environ[key_name]=bridge.key
        server=bridge.server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        configs=full_configurations(root/'bin','http://127.0.0.1:%d/v1'%server.server_port,protocol['embedding_url'])
        configs=json.loads(json.dumps(configs).replace('KMB_PROXY_KEY',key_name))
        workers.append((bridge,server,thread,{r['id']:r for r in configs}))
    atomic_private(root/('worker-configs-%s.json'%int(time.time())),{str(i):list(w[3].values()) for i,w in enumerate(workers)})
    lock=threading.Lock();pending=iter(protocol['tasks']);consecutive_errors=[0]
    def worker(index):
        bridge,server,thread,configs=workers[index]
        while True:
            task=None
            with lock:
                if (root/protocol.get('stop_file','STOP')).exists(): return
                active=sum(read_json(p).get('status')=='running' for p in (root/'task-state').glob('*.json'))
                if active<protocol['jobs']:
                    while True:
                        task=next(pending,None)
                        if task is None:return
                        state_file=root/'task-state'/(task['id']+'.json')
                        if not state_file.exists():break
                    atomic_private(state_file,{'status':'running','task':task,'started_at':time.time(),'owner_pid':os.getpid()})
            if task is None:
                time.sleep(.2);continue
            shard=root/'shards'/task['id'];bridge.context=task['id'];bridge.replay.clear()
            print('START',task['id'],flush=True)
            state={'task':task,'status':'interrupted'}
            try:
                execute([cases[task['case_id']]],{'schema_version':'1.0','agents':[configs[task['agent']]]},shard)
                state['status']=(verify_reader(shard,cases[task['case_id']]) if task['condition']=='reader_only' else verify_run(shard))['status']
            except BaseException as exc:
                state.update(status='interrupted',error_type=type(exc).__name__)
                (root/protocol.get('stop_file','STOP')).touch()
            finally:
                state['finished_at']=time.time();atomic_private(state_file,state)
            print('END',task['id'],state['status'],flush=True)
            # Stop scheduling on infrastructure failure. Ordinary wrong answers
            # never trigger this, and the failed case remains in the denominator.
            with lock:
                consecutive_errors[0]=consecutive_errors[0]+1 if state['status']!='completed' else 0
                if consecutive_errors[0]>=3: (root/protocol.get('stop_file','STOP')).touch()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(workers)) as pool:
            futures=[pool.submit(worker,i) for i in range(len(workers))]
            while not all(f.done() for f in futures):
                checkpoint(root,protocol);time.sleep(5)
            for future in futures: future.result()
    finally:
        for bridge,server,thread,configs in workers: server.shutdown();server.server_close();thread.join()
        status=checkpoint(root,protocol)
        status['status']='complete' if sum(status['case_status_counts'].get(k,0) for k in ('completed','completed_with_errors'))==len(protocol['tasks']) else 'incomplete'
        atomic_private(root/protocol.get('progress_file','progress.json'),status)
        report(root)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','run','status','report'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--embedding-url',default='http://127.0.0.1:18789/v1')
    parser.add_argument('--jobs',type=int,choices=range(1,9),default=4)
    args=parser.parse_args();root=args.output.resolve()
    if args.command=='prepare':
        memory=read_json(ROOT/'tmp/local-memory-preflight.json');health=read_json(ROOT/'tmp/plan-vector-health-01/results.json')
        validate_preflight(memory,health)
        prepare(root,args.embedding_url,args.jobs)
        write_json(root/'preflight.json',{'vector':memory,'native_health':health,
                   'embedding_runtime':read_json(ROOT/'tmp/local-embedding-ready.json')})
    elif args.command=='run':run(root)
    elif args.command=='report':report(root)
    else:
        protocol=read_json(root/'protocol.json')
        print(json.dumps(read_json(root/protocol.get('progress_file','progress.json')),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
