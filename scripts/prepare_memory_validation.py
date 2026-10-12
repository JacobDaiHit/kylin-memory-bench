#!/usr/bin/env python3
"""Prepare frozen health/pilot/formal datasets or analyze evidence. Never invokes a model."""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.math_memory import memory_v31 as research
from experiments.math_memory import memory_only as v3
from kylin_memory_bench.common import digest, strict_json
from kylin_memory_bench.dataset import load_dataset
from kylin_memory_bench.generate import save_dataset
from kylin_memory_bench.runner import read_run, verify_run
from kylin_memory_bench.adapters import redact


def config_signature(config):
    """Ignore install paths and loopback port; retain model, tool and inference controls."""
    from urllib.parse import urlsplit
    result=copy.deepcopy(redact(config))
    for agent in result['agents']:
        for key in ('executable','dependency_home','validation_backend'):
            agent.pop(key,None)
    def normalize(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('baseUrl','base_url'):
                    if item!='KMB_PROXY_BASE_URL' and urlsplit(item).hostname not in ('127.0.0.1','localhost','::1'):
                        raise ValueError('Prepared native run requires the loopback budget endpoint')
                    value[key]='LOOPBACK_BUDGET_ENDPOINT'
                else:normalize(item)
        elif isinstance(value,list):
            for item in value:normalize(item)
    normalize(result)
    return result


def health_cases():
    target = 'SCHUR-HEALTH-A'
    initial = {'id':'HEALTH-C0', 'project':target, 'kind':'patch', 'status':'accepted',
               'checkpoint':'C0', 'revision':'v0', 'payload':{'d1':'7','branch':'branch-green-health'}}
    update = {'id':'HEALTH-UPDATE', 'project':target, 'kind':'patch', 'status':'accepted',
              'revision':'v1', 'payload':{'d1':'2'}}
    unrelated = {'id':'HEALTH-B-C0', 'project':'SCHUR-HEALTH-B', 'kind':'patch', 'status':'accepted',
                 'payload':{'d1':'31','branch':'branch-other-health'}}
    query = research.RULES + '\nHEALTH_QUERY='+target+'\nq01=当前D1；q02=当前分支；q03=C0当时的D1。只返回这三项JSON，未知值为null。'
    result = []
    for name, records, values in [('persistence', [initial,update], ['2','branch-green-health','7']),
                                   ('isolation', [unrelated], [None,None,None])]:
        steps = []
        for i, record in enumerate(records):
            s = research.lesson(record, i)
            steps.append({'id':'note'+str(i), 'session':s['session'], 'day':i, 'kind':'message',
                          'prompt':s['prompt'], 'checks':[], 'output_tokens':1024})
        steps.append({'id':'final','session':'final','day':len(records),'kind':'probe','prompt':query,
            'output_tokens':4096,'checks':[{'id':'q'+str(i+1).zfill(2),'source':'response','op':'equals',
                'pointer':'/q'+str(i+1).zfill(2),'value':value,'failure':'confusion'} for i,value in enumerate(values)]})
        result.append({'schema_version':'1.0','id':'research-v31-health-'+name,'title':'数学档案健康检查：'+name,
                       'dimension':'retention','synthetic':True,'steps':steps,'health_kind':name})
    return result


def prepare(output, stage='pilot', seed=20261011):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if stage == 'health':
        cases = health_cases()
        gold = {c['id']:{v['id']:v['value'] for v in c['steps'][-1]['checks']} for c in cases}
        learner = None; repeats = 2
    else:
        all_cases, all_gold = research.build(seed)
        families = ['updates'] if stage=='pilot' else ['binding','updates','scope']
        learner = [c for c in all_cases if c['family'] in families and c['condition'] in ('memory','stateless','open_book')]
        gold = {c['id']:all_gold[c['id']] for c in learner}
        cases = research.native_dataset(learner, gold)
        repeats = 1 if stage=='pilot' else 3
        v3.dump(output/'learner-cases.json', learner)
        v3.dump(output/'answer-trace.evaluator.json', {c['id']:v3.answer_trace(c, gold[c['id']]) for c in learner})
    save_dataset(output/'dataset.evaluator.jsonl', cases)
    load_dataset(output/'dataset.evaluator.jsonl')
    v3.dump(output/'gold.json', gold)
    config = json.loads((ROOT/'configs/deepseek-research-v31.example.json').read_text())
    v3.dump(output/'config.template.json', config)
    finals = len(cases)*2*repeats
    protocol = {'version':'3.1','stage':stage,'status':'prepared_not_executed','paid_calls':0,'seed':seed,
                'agents':['openclaw','hermes'],'repeats':repeats,'jobs':1,'scheduled_final_slots':finals,
                'checks_per_final':3 if stage=='health' else 18,
                'selection':'Frozen before model calls. No result-selected replacement or automatic case rerun.',
                'output_limits':{'lesson':1024,'final':4096},
                'gates':{'health': 'Both systems, both repeats: all persistence and isolation answers correct; actual native writes visible; native wrapper isolation verified.',
                         'pilot':'Both open-book controls 18/18; memory content coverage >=90%; no execution errors.',
                         'formal':'Each discussed family/agent content coverage >=90%; three family mean difficulty drops >=15pp and at least two of three round directions positive; system differences reported separately.'},
                'paid_policy':'No live call in preparation. Require separately recorded current prices, remaining cumulative authorization and successful live native health before a paid pilot.',
                'scope':'Persistent-state availability control, not a pure native memory-module switch; byte/slot matching is not native context-token matching.',
                'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
                'implementation_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    [Path(__file__),ROOT/'experiments/math_memory/memory_v31.py',ROOT/'scripts/isolated_native_v31.sh',
                     ROOT/'scripts/live_deepseek.py',ROOT/'kylin_memory_bench/adapters.py',ROOT/'kylin_memory_bench/runner.py',
                     ROOT/'kylin_memory_bench/scoring.py',ROOT/'kylin_memory_bench/dataset.py']}}
    v3.dump(output/'protocol.json', protocol)
    return protocol


def verify_prepared(directory):
    directory = Path(directory)
    protocol = strict_json((directory/'protocol.json').read_text())
    for name, expected in protocol['data_sha256'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Prepared material changed: '+name)
    return protocol


def health_grade(expected, text, error):
    parsed = None; conforming = False
    if not error:
        try:parsed, _, conforming = research.extract_answer(text)
        except (ValueError,TypeError):pass
    checks=[]
    for qid,value in expected.items():
        actual=parsed.get(qid) if parsed is not None else None
        status=('error' if error else 'unknown' if parsed is None or qid not in parsed else
                'pass' if v3.same(value,actual,qid,'text' if qid=='q02' else 'rational') else 'fail')
        checks.append({'qid':qid,'status':status,'expected':value,'actual':actual})
    return {'check_count':len(checks),'observed_count':sum(c['status'] in ('pass','fail') for c in checks),
            'correct_count':sum(c['status']=='pass' for c in checks),'checks':checks,
            'format_status':'error' if error else 'pass' if conforming else 'fail','execution_error':error}


def analyze(prepared, run, output, mode='offline', isolation_proof=None):
    prepared, run, output = map(Path,(prepared,run,output))
    protocol = verify_prepared(prepared)
    verified = verify_run(run)
    manifest, cases, events, _ = read_run(run)
    if manifest['dataset_sha256'] != digest(load_dataset(prepared/'dataset.evaluator.jsonl')):
        raise ValueError('Run differs from the prepared dataset')
    if manifest['repeats']!=protocol['repeats'] or {a['id'] for a in manifest['agents']}!=set(protocol['agents']):
        raise ValueError('Run repeats or agent identities differ from the frozen selection')
    gold=json.loads((prepared/'gold.json').read_text())
    learner={c['id']:c for c in json.loads((prepared/'learner-cases.json').read_text())} if protocol['stage']!='health' else {}
    finals={(e['agent_id'],e['trial'],e['case_id']):e for e in events if e['step_id']=='final'}
    rows=[]
    for agent in protocol['agents']:
        for trial in range(protocol['repeats']):
            for case in cases:
                e=finals.get((agent,trial,case['id']))
                response=(e or {}).get('response') or {}
                error=e.get('error') if e else 'missing_final_event'
                if protocol['stage']=='health':r=health_grade(gold[case['id']],response.get('text'),error)
                else:r=research.grade(learner[case['id']],gold[case['id']],response.get('text'),error)
                r.update(agent=agent,trial=trial,case=case['id'],event_id=e['event_id'] if e else None)
                if learner:r.update(family=learner[case['id']]['family'],level=learner[case['id']]['level'],condition=learner[case['id']]['condition'])
                rows.append(r)
    native=all(a['kind'] in ('openclaw','hermes') for a in manifest['agents'])
    stub_backend=any(a.get('validation_backend')=='offline_stub' for a in manifest['agents'])
    if mode=='live' and native:
        if config_signature(json.loads((prepared/'config.template.json').read_text()))!=config_signature(json.loads((run/'config.json').read_text())):
            raise ValueError('Live model/tool/inference configuration differs from preparation')
        if any(Path(a.get('executable','')).name!=a['id']+'-isolated' for a in manifest['agents']):
            raise ValueError('Live validation requires the declared isolated executables')
    actual_writes={agent:sum(a['name'] in ('write_file','edit','memory') for e in events if e['agent_id']==agent and e['step_id']!='final'
                        for a in (e.get('response') or {}).get('actions') or []) for agent in protocol['agents']}
    target_write_checks=[]
    if protocol['stage']=='health':
        for agent in protocol['agents']:
            for trial in range(protocol['repeats']):
                learning=[e for e in events if e['agent_id']==agent and e['trial']==trial and
                          e['case_id']=='research-v31-health-persistence' and e['step_id']!='final']
                wrote=any(a.get('status')!='failed' and (a['name'] in ('write_file','edit') or
                    (a['name']=='memory' and a.get('arguments',{}).get('action') in ('add','replace','save')))
                    for e in learning for a in (e.get('response') or {}).get('actions') or [])
                visible=any('SCHUR-HEALTH-A' in ((e.get('response') or {}).get('memory') or {}).get('text','') and
                            'branch-green-health' in ((e.get('response') or {}).get('memory') or {}).get('text','') for e in learning)
                target_write_checks.append({'agent':agent,'trial':trial,'write_action_observed':wrote,'target_store_visible':visible})
    isolated=False
    if isolation_proof is not None:
        proof=json.loads(Path(isolation_proof).read_text())
        isolated=proof.get('wrapper_sha256')==protocol['implementation_sha256']['scripts/isolated_native_v31.sh'] and bool(proof.get('isolation')) and all(proof['isolation'].values())
    all_correct=all(r['correct_count']==r['check_count'] for r in rows)
    errors=sum(bool(e.get('error')) for e in events)
    content_gate=all_correct if protocol['stage']=='health' else all(r['correct_count']==18 for r in rows if r['condition']=='open_book') and all(
        r['observed_count']/18>=.9 for r in rows if r['condition']=='memory') and not errors
    if protocol['stage']=='health':content_gate=content_gate and all(r['write_action_observed'] and r['target_store_visible'] for r in target_write_checks) and not errors
    report={'stage':protocol['stage'],'mode':mode,'paid_calls_by_analyzer':0,'verification':verified,'rows':rows,
            'scheduled_final_slots':protocol['scheduled_final_slots'],'scheduled_checks':protocol['scheduled_final_slots']*protocol['checks_per_final'],
            'content_gate_pass':content_gate,'actual_native_agents':native,'observed_write_actions':actual_writes,
            'health_target_writes':target_write_checks,'native_isolation_verified':isolated,
            'offline_stub_backend':stub_backend,
            'eligible_for_next_paid_stage':bool(mode=='live' and native and not stub_backend and isolated and content_gate and protocol['stage']!='formal'),
            'claim_limit':'Offline references/stubs cannot establish native memory health or capacity. Live mode is an evidence label, not a signature of honest provider or adapter behaviour.'}
    if protocol['stage']=='formal':
        effects=[]
        for family in ('binding','updates','scope'):
            diffs=[];coverage_ok=True
            for trial in range(3):
                per_agent=[]
                for agent in protocol['agents']:
                    low=next(r for r in rows if r['family']==family and r['trial']==trial and r['agent']==agent and r['condition']=='memory' and r['level']=='low')
                    high=next(r for r in rows if r['family']==family and r['trial']==trial and r['agent']==agent and r['condition']=='memory' and r['level']=='high')
                    coverage_ok &= min(low['coverage'],high['coverage'])>=.9
                    per_agent.append((low['correct_count']-high['correct_count'])/18)
                diffs.append(sum(per_agent)/len(per_agent))
            mean=sum(diffs)/3
            effects.append({'family':family,'round_drops':diffs,'mean_drop':mean,'coverage_gate_pass':coverage_ok,
                            'effect_gate_pass':coverage_ok and mean>=.15 and sum(d>0 for d in diffs)>=2})
        report['difficulty_effects']=effects
        report['difficulty_gate_pass']=content_gate and all(e['effect_gate_pass'] for e in effects)
        report['formal_claim_supported']=bool(mode=='live' and native and not stub_backend and isolated and report['difficulty_gate_pass'])
        comparisons=[]
        for family in ('binding','updates','scope'):
            for level in ('low','high'):
                gains={}
                system_deltas=[]
                for agent in protocol['agents']:
                    gains[agent]=[]
                    for trial in range(3):
                        on=next(r for r in rows if r['family']==family and r['level']==level and r['agent']==agent and r['trial']==trial and r['condition']=='memory')
                        off=next(r for r in rows if r['family']==family and r['level']==level and r['agent']==agent and r['trial']==trial and r['condition']=='stateless')
                        gains[agent].append((on['correct_count']-off['correct_count'])/18)
                for trial in range(3):
                    pair=[next(r for r in rows if r['family']==family and r['level']==level and r['agent']==agent and r['trial']==trial and r['condition']=='memory') for agent in protocol['agents']]
                    system_deltas.append((pair[0]['correct_count']-pair[1]['correct_count'])/18)
                comparisons.append({'family':family,'level':level,'persistent_state_gains':gains,
                    'system_delta_agent_order':protocol['agents'],'system_deltas':system_deltas,
                    'system_direction_repeats':{'positive':sum(d>0 for d in system_deltas),'negative':sum(d<0 for d in system_deltas)},
                    'claim_limit':'Descriptive paired state-availability gains and native-system differences; no module-only causal claim or statistical significance.'})
        report['paired_comparisons']=comparisons
    output.mkdir(parents=True,exist_ok=False)
    v3.dump(output/'results.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','analyze'])
    p.add_argument('--stage',choices=['health','pilot','formal'],default='pilot')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--prepared',type=Path)
    p.add_argument('--run',type=Path)
    p.add_argument('--mode',choices=['offline','live'],default='offline')
    p.add_argument('--isolation-proof',type=Path)
    args=p.parse_args()
    if args.command=='prepare':result=prepare(args.output,args.stage)
    elif args.prepared is None or args.run is None:p.error('--prepared and --run are required')
    else:result=analyze(args.prepared,args.run,args.output,args.mode,args.isolation_proof)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','data_sha256','implementation_sha256')},ensure_ascii=False))


if __name__=='__main__':main()
