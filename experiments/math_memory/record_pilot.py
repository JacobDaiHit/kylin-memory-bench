"""Prepare and independently score the V3 native memory pilot; never send gold."""
import argparse
import hashlib
import html
import json
from pathlib import Path

from .memory_only import answer_trace, build, dump, grade, native_dataset, parse_response

SELECTED = ('research-v3-combined-high-open_book', 'research-v3-combined-high-memory',
            'research-v3-combined-high-no_history')
ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen(frozen):
    protocol = json.loads((frozen/'protocol.json').read_text())
    for name, fingerprint in protocol['data_sha256'].items():
        if sha(frozen/name) != fingerprint:
            raise ValueError('Frozen pilot material changed: '+name)
    return protocol


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    cases, answers = build(20261011)
    chosen = [next(c for c in cases if c['id'] == cid) for cid in SELECTED]
    gold = {c['id']:answers[c['id']] for c in chosen}
    dump(output/'learner-cases.json', chosen)
    dump(output/'gold.json', gold)
    dump(output/'answer-trace.evaluator.json', {c['id']:answer_trace(c,gold[c['id']]) for c in chosen})
    dataset = output/'dataset.evaluator.jsonl'
    dataset.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in native_dataset(chosen,gold)),encoding='utf-8')
    from kylin_memory_bench.dataset import load_dataset
    load_dataset(dataset)
    config = json.loads((ROOT/'configs/deepseek-live.example.json').read_text())
    for agent in config['agents']:
        agent['executable'] = '/home/kmb/runs/kmb-research-v3-native/bin/'+agent['id']+'-isolated'
        agent['timeout'] = 600
        if agent['id'] == 'hermes':
            agent['dependency_home'] = '/home/maedaily/.local/share/kmb-live/hermes-home'
    dump(output/'config.template.json', config)
    protocol = {'status':'frozen-before-paid-run','version':3,'seed':20261011,
                'selected_cases':SELECTED,'repeats':1,'agents':['openclaw','hermes'],
                'scheduled_final_slots':6,'checks_per_slot':18,'primary_condition':'memory',
                'selection':'One predeclared composite high-load example with two matched controls; no result-selected cases or retries.',
                'claim_limit':'One-round feasibility only; no low/high difficulty effect, repetition stability, ranking or final-release gate.',
                'controls':'memory/open_book have identical prior sessions in separate workspaces; no_history removes every queried project.',
                'scoring':'V3 independent semantic grading; core strict JSON equality retained as supplemental evidence.',
                'isolation':'Unprivileged user/mount/PID namespaces; only current workspace and installed runtimes exposed; no-new-privileges and capabilities dropped.',
                'data_sha256':{p.name:sha(p) for p in output.iterdir() if p.is_file()},
                'implementation_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (
                    Path(__file__),ROOT/'experiments/math_memory/memory_only.py',ROOT/'scripts/isolated_native.sh')},
                'budget':'Retain cumulative ledger; additional authorization and execution freeze required before live run; video allowance excluded.'}
    dump(output/'protocol.json', protocol)
    print(json.dumps({'frozen':str(output),'cases':len(chosen),'final_slots':6,
                      'historical_sessions':[len(c['sessions'])-1 for c in chosen],'paid_calls':0}))


def analyze(frozen, run, output):
    from kylin_memory_bench.runner import read_run, verify_run
    from kylin_memory_bench.common import digest
    from kylin_memory_bench.dataset import load_dataset
    protocol = verify_frozen(frozen)
    verification = verify_run(run)
    manifest, dataset, events, raw_scores = read_run(run)
    if digest(load_dataset(frozen/'dataset.evaluator.jsonl')) != manifest['dataset_sha256']:
        raise ValueError('Run did not use the frozen pilot dataset')
    cases = {c['id']:c for c in json.loads((frozen/'learner-cases.json').read_text())}
    gold = json.loads((frozen/'gold.json').read_text())
    if {c['id'] for c in dataset} != set(cases) or manifest['repeats'] != 1:
        raise ValueError('Run selection or repeats differ from pilot freeze')
    if {a['id'] for a in manifest['agents']} != set(protocol['agents']):
        raise ValueError('Run agents differ from pilot freeze')
    finals = {(e['agent_id'],e['case_id'],e['trial']):e for e in events if e['step_id']=='final'}
    rows=[]
    for agent in protocol['agents']:
        for cid in protocol['selected_cases']:
            case=cases[cid]
            event=finals.get((agent,cid,0))
            response=event.get('response') if event else None
            text=response.get('text') if response else None
            error=event.get('error') if event else 'missing_final_event'
            result=grade(case,gold[cid],text,error=error)
            result.update({'agent':agent,'trial':0,'event_id':event['event_id'] if event else None,
                           'observation_status':'execution_error' if error else 'observed',
                           'response_text':text,'actual_answers':None})
            if not error:
                try: result['actual_answers']=parse_response(text)[0]
                except (ValueError,TypeError,RecursionError): pass
            for check in result['checks']:
                check['expected']=gold[cid][check['qid']]
                check['actual']=result['actual_answers'].get(check['qid']) if result['actual_answers'] else None
                check['literal_evidence']=answer_trace(case,gold[cid])[check['qid']]
            previous=[e for e in events if e['agent_id']==agent and e['case_id']==cid and e['step_id']!='final']
            actions=lambda es:sum(len((e.get('response') or {}).get('actions') or []) for e in es)
            result['tool_evidence']={'historical_events':len(previous),
                                     'historical_execution_errors':sum(bool(e.get('error')) for e in previous),
                                     'historical_tool_actions':actions(previous),
                                     'final_tool_actions':actions([event]) if event else 0,
                                     'provenance':response.get('provenance') if response else None}
            result['claim_limit']='Native single-trial record-memory feasibility; no mathematical result or stable capacity estimate.'
            rows.append(result)
    summary={}
    for agent in protocol['agents']:
        by_condition={r['condition']:r for r in rows if r['agent']==agent}
        summary[agent]={'conditions':{k:{x:r[x] for x in ('correct_count','observed_count','check_count','coverage','correct_over_all')}
                                     for k,r in by_condition.items()},
                        'open_book_reading_gate_pass':by_condition['open_book']['correct_over_all']>=0.95,
                        'memory_interpretation':'Descriptive retrieval only; open-book results and execution/format failures must be considered together.'}
    output.mkdir(parents=True,exist_ok=False)
    dump(output/'results.json',{'verification':verification,'run_id':manifest['run_id'],'status':manifest['status'],
                               'rows':rows,'summary':summary,'protocol':protocol,
                               'analysis_sha256':sha(Path(__file__)),
                               'claim_limit':protocol['claim_limit']})
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k)))+'</td>' for k in
                               ('agent','condition','event_id','format','correct_count','observed_count','execution_error'))+'</tr>' for r in rows)
    page='<!doctype html><html lang="zh"><meta charset="utf-8"><title>研究档案记忆 V3 真实试测</title>'
    page+='<style>body{font:16px/1.6 sans-serif;margin:28px}table{border-collapse:collapse}th,td{border:1px solid #bcc8d2;padding:9px}</style>'
    page+='<h1>研究档案记忆 V3：真实付费小试测</h1><p>综合高负载，78次历史会话，三个项目、18项登记事实。完整记录和缺资料对照单独报告；不求解数学题。</p>'
    page+='<p>两款原生系统各一轮。这不是难度验收或稳定排名。<a href="results.json">逐项答案、证据和控制结果</a></p>'
    page+='<table><tr>'+''.join('<th>'+s+'</th>' for s in ('系统','资料条件','最终事件','格式','正确/18','观测/18','执行错误'))+'</tr>'+table+'</table></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'status':manifest['status'],'summary':summary},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','analyze'])
    p.add_argument('--frozen',type=Path,required=True)
    p.add_argument('--run',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.command=='prepare': prepare(args.frozen)
    elif args.run is None or args.output is None: p.error('--run and --output required')
    else: analyze(args.frozen,args.run,args.output)


if __name__=='__main__':main()
