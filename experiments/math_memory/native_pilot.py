"""Frozen small native feasibility pilot. Never feeds gold to adapters."""
import argparse
import hashlib
import html
import json
from pathlib import Path

from .prototype import build, grade, dump
from .math_core import rational_equal

SELECTED = ('reasoning-low--memory', 'reasoning-low--oracle',
            'reasoning-high--memory', 'reasoning-high--oracle',
            'reasoning-high--no_history', 'applicability-singular--oracle')
SUPPORT = '''\n统一数学支持（公式不是本题答案）：c2=κ，c4=-κ*r11；
六阶c6=κ*r11²-κ²*t11+κ²*r12²/(κ-κ*)。使用精确有理数计算。
请先重建并核对完整输入，随后计算证书。不能把资料缺失当作方法不适用。
若缺少计算工具，仍需如实返回结果，不得宣称运行了不存在的工具。\n'''


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    cases, answers = build(20261012)
    chosen = [c for cid in SELECTED for c in cases if c['id'] == cid]
    dataset = []
    for case in chosen:
        steps = []
        sessions = case['sessions']
        # No-history low-noise cases would have one session; these selected cases have fillers.
        for index, session in enumerate(sessions):
            final = index == len(sessions)-1
            prompt = session['prompt'] + (SUPPORT if final else '\n请将这份记录可靠地保留到后续独立会话；不要提前计算答案。')
            steps.append({'id': 'final' if final else 'note-'+str(index),
                          'kind': 'task' if final else 'message', 'session': 'session-'+str(index),
                          'day': index, 'prompt': prompt,
                          'checks': ([{'id': 'status', 'source': 'response', 'op': 'equals',
                                       'pointer': '/result/status', 'value': answers[case['id']]['result']['status'],
                                       'failure': 'wrong_reuse', 'measurement_domain': 'content'},
                                      {'id': 'actual-file', 'source': 'artifact', 'op': 'exists',
                                       'path': 'deliverables/research-certificate.json',
                                       'failure': 'wrong_reuse', 'measurement_domain': 'artifact'}] if final else [])})
        dataset.append({'schema_version': '1.0', 'id': case['id'], 'title': case['id'],
                        'dimension': 'reuse', 'synthetic': True, 'steps': steps,
                        'math_profile': case['profile'], 'math_condition': case['condition'],
                        'math_order': case['order']})
    target = output/'dataset.jsonl'
    target.write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in dataset))
    dump(output/'learner-cases.json', chosen)
    dump(output/'gold.json', {c['id']: answers[c['id']] for c in chosen})
    from kylin_memory_bench.dataset import load_dataset
    load_dataset(target)
    dump(output/'protocol.json', {'status': 'frozen-before-paid-run', 'seed': 20261012,
        'selected_cases': SELECTED, 'selection': 'predeclared feasibility subset, not result-selected',
        'repeats': 1, 'support': 'same explicit coefficient formula for all final prompts',
        'claim_limit': 'feasibility only; no repeat stability or difficulty gate claim',
        'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}})


def analyze(frozen, run, output):
    from kylin_memory_bench.runner import read_run, verify_run
    verification = verify_run(run)
    protocol = json.loads((frozen/'protocol.json').read_text())
    for name, sha in protocol['sha256'].items():
        if hashlib.sha256((frozen/name).read_bytes()).hexdigest() != sha:
            raise ValueError('Frozen file changed: '+name)
    manifest, dataset, events, raw_scores = read_run(run)
    cases = {c['id']: c for c in json.loads((frozen/'learner-cases.json').read_text())}
    gold = json.loads((frozen/'gold.json').read_text())
    rows = []
    for event in events:
        if event['step_id'] != 'final':
            continue
        case = cases[event['case_id']]
        row = {'agent': event['agent_id'], 'case': case['id'], 'condition': case['condition'],
               'event_id': event['event_id'], 'trial': event['trial'],
               'observation_status': 'execution_error' if event.get('error') else 'observed',
               'execution_error': event.get('error')}
        if event.get('error'):
            row.update({'format': None, 'inputs': None, 'math': None, 'artifact': None})
        else:
            row.update(grade(case, gold[case['id']], event['response']['text']))
            try:
                submitted = json.loads(event['response']['text'])['inputs']
                expected = gold[case['id']]['inputs']
                if expected is not None and isinstance(submitted, dict):
                    row['input_fields'] = {k:rational_equal(expected[k],submitted.get(k))
                                           for k in ('A','B','D','branch')}
                    row['input_fields']['version'] = expected['version'] == submitted.get('version')
                    # Additional unordered-source diagnostic; original strict grade remains intact.
                    sources = submitted.get('sources')
                    row['input_fields']['source_set'] = isinstance(sources,list) and len(sources)==3 and set(expected['sources'])==set(sources)
                    numeric = all(row['input_fields'][k] for k in ('A','B','D','branch'))
                    row['math_given_correct_numeric_inputs'] = row['math'] if numeric else None
            except (ValueError,TypeError,KeyError):
                pass
            artifact = event.get('artifacts', {}).get('deliverables/research-certificate.json')
            row['artifact_evidence'] = artifact
            row['artifact'] = artifact.get('exists') if isinstance(artifact, dict) else None
            row['tool_trace'] = {'actions': len(event['response'].get('actions', [])),
                                 'provenance': event['response'].get('provenance')}
            # Immutable artifact snapshots are analyzed separately from conversational JSON.
            if isinstance(artifact, dict) and isinstance(artifact.get('text'), str):
                row['artifact_grade'] = grade(case, gold[case['id']], artifact['text'])
                try:
                    row['artifact_response_equal'] = json.loads(artifact['text']) == json.loads(event['response']['text'])
                except ValueError:
                    row['artifact_response_equal'] = False
        rows.append(row)
    observed = {(r['agent'],r['case'],r['trial']) for r in rows}
    for agent in manifest['agents']:
        for trial in range(manifest['repeats']):
            for case in cases.values():
                if (agent['id'],case['id'],trial) not in observed:
                    rows.append({'agent':agent['id'],'case':case['id'],'condition':case['condition'],
                                 'trial':trial,'event_id':None,'observation_status':'unknown_missing_event',
                                 'execution_error':None,'format':None,'inputs':None,'math':None,'artifact':None})
    output.mkdir(parents=True, exist_ok=False)
    dump(output/'results.json', {'verification': verification, 'run_id': manifest['run_id'],
                                'status': manifest['status'], 'rows': rows,
                                'analysis_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                'claim_limit': 'one trial feasibility; not a ranking or validated difficulty'})
    table = ''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k)))+'</td>' for k in
                    ('agent','case','event_id','format','inputs','math','consistent_with_reported_inputs',
                     'algebra_residual','artifact','artifact_response_equal'))+'</tr>' for r in rows)
    page = '<!doctype html><html lang="zh"><meta charset="utf-8"><title>数学记忆真实试测</title>'
    page += '<style>body{font:15px/1.6 sans-serif;margin:30px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:8px}</style>'
    page += '<h1>数学研究记忆：真实可行性试测</h1><p>两款原生智能体、同一模型、各一轮。不是稳定排名或难度门槛验证。</p>'
    page += '<p><a href="results.json">逐项结果与文件证据</a></p><table><tr>'
    page += ''.join('<th>'+k+'</th>' for k in ('系统','实例','事件','格式','条件恢复','数学结果','按自述条件成立','代数余项','实际文件','文件与回答一致'))
    page += '</tr>'+table+'</table></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({'status': manifest['status'], 'final_events': sum(r['event_id'] is not None for r in rows),
                      'scheduled_final_slots': len(rows),
                      'rows': [{k: r.get(k) for k in ('agent','case','format','inputs','math','execution_error')} for r in rows]}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare', 'analyze'])
    p.add_argument('--frozen', type=Path, required=True)
    p.add_argument('--run', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a.frozen)
    else:
        analyze(a.frozen, a.run, a.output)
