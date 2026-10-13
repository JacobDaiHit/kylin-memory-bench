"""Two-hour, preselected short-history native calibration; no case retries."""
import concurrent.futures
import argparse
import copy
import datetime
import hashlib
import json
import os
import shutil
import threading
import time
import random
from pathlib import Path

from kylin_memory_bench.common import digest, read_json, write_json
from kylin_memory_bench.runner import execute, read_run, verify_run
from kylin_memory_bench.adapters import External
from experiments.memory_stress.v2.oracle import oracle_records, resolve
from experiments.memory_stress.v2.suite import build_case, collect_slots
from scripts.chatgpt_plan import TARGET, atomic_private
from scripts.chatgpt_plan_bridge import Bridge
from scripts.plan_native_config import full_configurations
from scripts.plan_reader_replay import verify_reader, read_reader

ROOT = Path(__file__).resolve().parents[1]
RUN = Path('/home/maedaily/.local/share/kmb-live/runs/kmb-plan-submission-pilot-20261013')


def prepare(seed_offset=0, pooled=False, compact_options=False,jobs=4):
    RUN.mkdir(parents=True, exist_ok=False, mode=0o700)
    data = ROOT/'experiments/memory_stress/v2/development-v2/worlds.evaluator.jsonl'
    worlds = [json.loads(l) for l in data.read_text().splitlines()]
    selected, cases, catalog, tasks = [], {}, {}, []
    for family in ('multihop', 'updates', 'collections', 'feedback'):
        for tier in ('low', 'high'):
            w = copy.deepcopy(sorted((w for w in worlds if w['family']==family and w['tier']==tier and w['split']=='development'), key=lambda w:w['seed'])[seed_offset])
            q = next(q for q in w['queries'] if q['role']=='primary')
            expected = resolve(w,q)['value']
            if compact_options and q.get('options'):
                right=next(o for o in q['options'] if o['id']==expected)
                fields=list(q['choices']);vectors=[]
                def add_pair(values):
                    opposite={key:next(x for x in q['choices'][key] if x!=values[key]) for key in fields}
                    for v in (values,opposite):
                        if v not in vectors:vectors.append(v)
                add_pair(right['values'])
                for key in q['required_fields']:
                    v=dict(right['values']);v[key]=next(x for x in q['choices'][key] if x!=v[key]);add_pair(v)
                for o in q['options']:
                    if len(vectors)==16:break
                    add_pair(o['values'])
                q['options']=[o for o in q['options'] if o['values'] in vectors]
                if len(q['options'])!=16:raise ValueError('Compact candidate table is not balanced')
                for key in fields:
                    if sum(o['values'][key]==right['values'][key] for o in q['options'])!=8:raise ValueError('Unbalanced candidates')
                for key in q['required_fields']:
                    if not any(o['values'][key]!=right['values'][key] and all(o['values'][k]==right['values'][k] for k in fields if k!=key) for o in q['options']):raise ValueError('A historical constraint became unnecessary')
                if resolve(w,q)['value']!=expected:raise ValueError('Candidates changed answer')
                w['loads'].update(diagnostic_candidate_count=16,source_candidate_count=256 if family=='collections' else 64)
            keep = {r['id'] for r in oracle_records(w,q)}
            keep.update(r['id'] for r in w['events'] if r['subject']==q['subject'])
            # Preserve cancellation targets rather than leaving dangling references.
            for r in w['events']:
                if r['id'] in keep and r.get('target_id'): keep.add(r['target_id'])
            if len(keep)>24: raise ValueError('Essential chronology exceeds short protocol')
            candidates = [r for r in w['events'] if r['id'] not in keep]
            candidates.sort(key=lambda r:(r['kind']=='discussion', r['id']))
            for r in candidates:
                if len(keep)==24: break
                if r.get('target_id') and r['target_id'] not in keep: continue
                keep.add(r['id'])
            w['events'] = [r for r in w['events'] if r['id'] in keep]
            if len(w['events'])!=24 or resolve(w,q)['value']!=expected:
                raise ValueError('Shortening changed answer or session count')
            w['scenario_id']=('short24-candidates16-' if compact_options else 'short24-')+w['scenario_id']
            w['split_group']=w['scenario_id'];w['contract']='memory-stress-short24-submission-1'
            w['loads'].update(short_history_sessions=24, source_history_sessions=128)
            selected.append(w)
            for condition in ('reader_only','memory'):
                c,m=build_case(w,q['id'],'oracle_evidence' if condition=='reader_only' else 'memory')
                if compact_options and q.get('options'):
                    c['steps'][-1]['prompt']+='\n本题answer必须返回options中唯一匹配方案的id；provided是当前有效约束，required_fields从历史恢复。不要返回目录或文件名。transfer任务还须生成对应文件。'
                    m['case_sha256']=digest(c)
                if condition=='reader_only':
                    c['id']='reader-'+c['id'];c['title']=c['id'];c['steps']=c['steps'][-1:]
                    m.update(case_id=c['id'], condition=condition,case_sha256=digest(c),history_utf8_bytes=0)
                cases[c['id']]=c;catalog[c['id']]=m
                for agent in ('openclaw','hermes'):
                    tasks.append({'id':f'{len(selected)-1:02d}-{agent}-{condition}','agent':agent,'case_id':c['id'],'condition':condition})
    (RUN/'bin').mkdir()
    for agent in ('openclaw','hermes'):
        f=RUN/'bin'/(agent+'-isolated');shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh',f);f.chmod(0o700)
    for name,value in [('worlds.json',selected),('cases.json',cases),('catalog.json',catalog)]:atomic_private(RUN/name,value)
    source={}
    for directory in ('scripts','kylin_memory_bench','experiments','configs'):
        for f in (ROOT/directory).rglob('*'):
            if f.is_file() and (f.suffix in ('.py','.sh') or f.name.endswith('.example.json')):
                rel=f.relative_to(ROOT);dest=RUN/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
                source[str(rel)]=hashlib.sha256(f.read_bytes()).hexdigest()
    protocol={'protocol':'luna-short24-submission-1','model':TARGET,'histories':8,'tasks':tasks,'jobs':jobs,'history_sessions':24,
              'memory_turns':400,'reader_turns':16,'cases_sha256':digest(cases),'source_sha256':source,
              'selection':f'Development seed index {seed_offset} per family and low/high tier; fixed before this pilot. Source suite and prior traces are public; not blind.',
              'pooled_https_connections':pooled,
              'compact_candidate_diagnostic':compact_options,
              'bridge_error_contract':'provider-and-transport-status-v2',
              'transport_read_timeout_seconds':120,'native_turn_timeout_seconds':180,'case_retry':False,
              'deadline_seconds':6300 if pooled else 6900,'request_cap':None,'output_cap':None,
              'tls_warmup':'When pooled, up to four unauthenticated GET attempts establish TLS; inference requests are not retried.',
              'acceptance':{'reader_observed_minimum':14,'reader_content_minimum':14,'memory_observed_minimum':14,
                            'meaning':'Operational calibration only. No ranking or claim that original difficulty gate was met.'},
              'scope':'Standalone 24-session revision. Does not replace or merge 128-session results. Native tools retained; WSL, not native openKylin.'}
    atomic_private(RUN/'protocol.json',protocol)
    return protocol,cases,catalog


def summarize(protocol,cases,catalog):
    rows=[]
    for t in protocol['tasks']:
        p=RUN/'shards'/t['id'];c=cases[t['case_id']]
        if (p/'scores.json').exists():
            if t['condition']=='reader_only':verify_reader(p,c);manifest,recorded,events,_=read_reader(p,c)
            else:verify_run(p);manifest,recorded,events,_=read_run(p)
            if recorded != [c]:raise ValueError('Frozen case mismatch')
        else:manifest={'agents':[{'id':t['agent']}],'repeats':1};events=[]
        for row in collect_slots(manifest,[c],events,catalog):
            row['task_id']=t['id'];rows.append(row)
    groups=[]
    for a in ('openclaw','hermes'):
        for cond in ('reader_only','memory'):
            v=[r for r in rows if r['agent']==a and r['condition']==cond]
            groups.append({'agent':a,'condition':cond,'planned':len(v),'observed':sum(r['grade']['observed'] for r in v),
                           'content_correct':sum(r['grade']['content_task_success'] for r in v),
                           'task_success':sum(r['action']['whole_task_success'] for r in v)})
    reader=[g for g in groups if g['condition']=='reader_only'];memory=[g for g in groups if g['condition']=='memory']
    gate=sum(g['observed'] for g in reader)>=14 and sum(g['content_correct'] for g in reader)>=14 and sum(g['observed'] for g in memory)>=14
    result={'groups':groups,'rows':rows,'pilot_operational_gate':gate,
            'claim_limit':'Eight development histories, one round, revised short protocol. No stable ranking, no original difficulty-gate claim.',
            'submission_scope':'Existing formal results and offline stress-suite engineering may be submitted with limitations. Packaging/video acceptance remains separate.'}
    atomic_private(RUN/'analysis.json',result)
    safe=[{k:r[k] for k in ('task_id','agent','condition','family','tier','phase','grade','action')} for r in rows]
    stem='luna-short24-candidates16-results' if protocol.get('compact_candidate_diagnostic') else 'luna-short24-status-results' if protocol.get('bridge_error_contract')=='provider-and-transport-status-v2' else 'luna-short24-pooled-results' if protocol.get('pooled_https_connections') else 'luna-short24-results'
    write_json(ROOT/('docs/evidence/'+stem+'.json'),{k:v for k,v in result.items() if k!='rows'}|{'rows':safe,'pooled_https_connections':protocol.get('pooled_https_connections',False)})
    text=['# Luna 短历史提交校题','',f'模型 `{TARGET}`；8 条开发历史，每条 24 次学习；两款原生 Agent；一轮。',
          '这是独立修订协议，不能与原 128 会话全量成绩混算。测试环境是 WSL。','',
          '| Agent | 条件 | 计划 | 有效观测 | 内容正确 | 整体任务成功 |','|---|---|---:|---:|---:|---:|']
    text += ['| '+ ' | '.join(str(g[k]) for k in ('agent','condition','planned','observed','content_correct','task_success'))+' |' for g in groups]
    text += ['',f'预先声明的运行校题门槛：{"通过" if gate else "未通过"}。',
             '单轮小样本不支持稳定排名，也不证明原难度验收门槛已经达到。历史正式实验继续保留。',
             '可提交范围为已有正式实验和新增题库的软件成果，并公开测量局限；完整交付还需安装包、离线复核和视频验收。']
    (ROOT/('docs/'+stem+'.md')).write_text('\n'.join(text)+'\n')
    return result


def main():
    global RUN
    parser=argparse.ArgumentParser();parser.add_argument('--seed-offset',type=int,default=0,choices=range(8));parser.add_argument('--pooled',action='store_true');parser.add_argument('--output',type=Path,default=RUN);parser.add_argument('--deadline-epoch',type=float);parser.add_argument('--compact-options',action='store_true');parser.add_argument('--jobs',type=int,choices=range(1,7),default=4);parser.add_argument('--external-progress',type=Path)
    args=parser.parse_args();RUN=args.output
    protocol,cases,catalog=prepare(args.seed_offset,args.pooled,args.compact_options,args.jobs);started=time.time();deadline=started+(6300 if args.pooled else 6900)
    if args.deadline_epoch is not None:
        deadline=min(deadline,args.deadline_epoch)
        protocol['deadline_epoch']=deadline;protocol['deadline_seconds']=max(0,deadline-started)
        atomic_private(RUN/'protocol.json',protocol)
    # This protocol changes only the fixed read timeout, not provider retries or content.
    import requests
    original_request=requests.request
    local=threading.local();pooled=args.pooled
    def transport(*args,**kwargs):
        kwargs['timeout']=(10,120)
        if not pooled:return original_request(*args,**kwargs)
        if not hasattr(local,'session'):
            local.session=requests.Session()
            # No inference or credentials: establish a reusable TLS connection.
            attempts=[]
            for i in range(4):
                try:
                    probe=local.session.get('https://api.openai.com/v1/models',timeout=(10,15))
                    attempts.append({'status':probe.status_code});probe.close();break
                except requests.RequestException as e:attempts.append({'error_type':type(e).__name__})
            atomic_private(RUN/('tls-warmup-'+str(threading.get_ident())+'.json'),attempts)
        return local.session.request(*args,**kwargs)
    requests.request=transport
    original_turn=External.turn
    def timed_turn(self,request):
        if time.time()>=deadline:raise TimeoutError('Predeclared pilot deadline; unexecuted steps remain unknown')
        return original_turn(self,request)
    External.turn=timed_turn
    (RUN/'shards').mkdir();(RUN/'states').mkdir()
    lock=threading.Lock();pending=iter(protocol['tasks']);states={};workers=[]
    for i in range(args.jobs):
        bridge=Bridge(RUN/'requests'/str(i),limit=None,deadline_seconds=6900)
        key='KMB_PILOT_KEY_'+str(i);os.environ[key]=bridge.key
        server=bridge.server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        configs=full_configurations(RUN/'bin',f'http://127.0.0.1:{server.server_port}/v1','http://127.0.0.1:18789/v1')
        configs=json.loads(json.dumps(configs).replace('KMB_PROXY_KEY',key));workers.append((bridge,server,thread,{c['id']:c for c in configs}))
    def worker(i):
        bridge,server,thread,configs=workers[i]
        while time.time()<deadline:
            task=None
            with lock:
                external=read_json(args.external_progress) if args.external_progress and args.external_progress.exists() else {}
                active=sum(v['status']=='running' for v in states.values())+sum(v['status']=='running' for v in external.get('states',{}).values())
                if active<args.jobs:
                    task=next(pending,None)
                    if task is None:return
                    states[task['id']]={'status':'running','started_at':time.time()};atomic_private(RUN/'states'/(task['id']+'.json'),states[task['id']])
            if task is None:time.sleep(.5);continue
            bridge.context=task['id'];bridge.replay.clear();state={'status':'interrupted'}
            print('START',task['id'],flush=True)
            try:
                execute([cases[task['case_id']]],{'schema_version':'1.0','agents':[configs[task['agent']]]},RUN/'shards'/task['id'])
                state['status']=(verify_reader(RUN/'shards'/task['id'],cases[task['case_id']]) if task['condition']=='reader_only' else verify_run(RUN/'shards'/task['id']))['status']
            except BaseException as e:state['error_type']=type(e).__name__
            state['finished_at']=time.time()
            with lock:states[task['id']]=state;atomic_private(RUN/'states'/(task['id']+'.json'),state)
            print('END',task['id'],state['status'],flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            fs=[pool.submit(worker,i) for i in range(args.jobs)]
            while not all(f.done() for f in fs):
                with lock:atomic_private(RUN/'progress.json',{'status':'running','elapsed_seconds':time.time()-started,'states':copy.deepcopy(states),'planned':32})
                time.sleep(5)
            for f in fs:f.result()
    finally:
        for bridge,server,thread,configs in workers:server.shutdown();server.server_close()
        atomic_private(RUN/'progress.json',{'status':'finished','elapsed_seconds':time.time()-started,'states':states,'planned':32})
        result=summarize(protocol,cases,catalog);print(json.dumps({'gate':result['pilot_operational_gate'],'groups':result['groups']}),flush=True)

if __name__=='__main__':main()
