"""V3.1 record-memory contract and matched persistent-state controls; offline only."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

from kylin_memory_bench.common import strict_json
from . import memory_only as v3

CONDITIONS = ('memory', 'stateless', 'open_book', 'no_history')
REVISION_RULE = ('patch只替换列出的字段，其余字段保持不变；revision只有在accepted patch/cancel明确提供标签时才更新。'
                 '未提供revision的补丁保留已有标签；不能按版本号大小选择。')
RULES = v3.RULES.replace(v3.RULES.splitlines()[2], REVISION_RULE)


def records_of(case):
    return [strict_json(line[7:]) for s in case['sessions'][:-1]
            for line in s['prompt'].splitlines() if line.startswith('RECORD=')]


def lesson(record, index):
    return {'day': index, 'session': 's'+str(index),
            'prompt': '请按自身机制保存这份研究记录，供后续独立会话使用。不要计算或推导。\nRECORD='+json.dumps(record, ensure_ascii=False)}


def history_bytes(records):
    return sum(len(lesson(r, i)['prompt'].encode()) for i, r in enumerate(records))


def matched_histories(low, high, family):
    """Same slots/UTF-8 input bytes; neutral padding is explicit and non-factual."""
    if family not in ('binding', 'updates', 'scope'):
        return low, high, {'matched': False, 'reason': 'Delay or composite manipulation; not a token-matched single-factor claim.'}
    low = copy.deepcopy(low)
    high = copy.deepcopy(high)
    insertion = {'binding': 9, 'updates': 3, 'scope': 15}[family]
    count = len(high)-len(low)
    neutral = [{'id': 'NEUTRAL-'+family+'-'+str(i), 'project': 'neutral-administration',
                'kind': 'discussion', 'status': 'accepted',
                'payload': {'note': '中性长度配平；不新增、修改或撤销任何研究事实。'}} for i in range(count)]
    low[insertion:insertion] = neutral
    delta = history_bytes(high)-history_bytes(low)
    padding = neutral if delta >= 0 else [r for r in high if r['kind']=='discussion']
    amount = abs(delta)
    for i, r in enumerate(padding):
        r['payload']['note'] = r['payload'].get('note', '') + '.'*(amount//len(padding) + (i < amount % len(padding)))
    if len(low) != len(high) or history_bytes(low) != history_bytes(high):
        raise AssertionError('Pair length matching failed')
    return low, high, {'matched': True, 'historical_sessions': len(high), 'historical_input_utf8_bytes': history_bytes(high),
                       'neutral_padding_disclosed': True, 'token_claim': 'UTF-8 bytes are matched, not tokenizer output or native tool/context tokens.'}


def final_prompt(projects, records, condition, plan):
    text = v3.query(projects, records, 'open_book' if condition == 'open_book' else 'memory', plan)
    return text.replace(v3.RULES, RULES) + '\n最终只输出18项短值；不附过程、证明或解释。'


def scope_case(seed, level, base):
    """Three independent bound lookups among 18 questions; no computed answers."""
    projects, parts = [], []
    for offset in (0,101,202):
        project, records, _ = v3.history(seed+offset, 'scope', level)
        projects.append(project)
        for record in records:
            record['id'] = project+'-'+record['id']
            payload = record['payload']
            if 'adoption' in payload:payload['adoption']['lemma_id']='L-Schur-shared'
            if record['kind']=='lemma':payload['lemma_id']='L-Schur-shared'
        parts.append(records)
    records=[part[i] for i in range(max(map(len,parts))) for part in parts if i<len(part)]
    base=copy.deepcopy(base)
    base.update(project=projects[0],target_projects=projects,query_plan=v3.plan_for(projects))
    base['loads'].update(queried_projects=3,additional_lemma_records=18 if level=='high' else 0)
    return base, records


def build(seed=20261011):
    original, original_gold = v3.build(seed)
    cases, gold = [], {}
    for family in v3.FAMILIES:
        pair = [next(c for c in original if c['family']==family and c['level']==level and c['condition']=='memory')
                for level in ('low', 'high')]
        if family=='scope':
            pair[0], low = scope_case(seed,'low',pair[0])
            pair[1], high = scope_case(seed,'high',pair[1])
        else:low, high=records_of(pair[0]),records_of(pair[1])
        low, high, matching = matched_histories(low, high, family)
        pair_gold=[v3.planned_answers(r,b['target_projects'],b['query_plan']) for b,r in zip(pair,(low,high))]
        if pair_gold[0]!=pair_gold[1]:raise AssertionError('Low/high gold differs')
        for base, records, current_gold in zip(pair, (low, high), pair_gold):
            for condition in CONDITIONS:
                shown = records if condition != 'no_history' else [r for r in records if r['project'] not in base['target_projects']]
                case = copy.deepcopy(base)
                case.update(id=base['id'].replace('research-v3-', 'research-v31-').rsplit('-', 1)[0]+'-'+condition,
                            condition=condition, pair_control=matching,
                            state_policy='fresh_each_session' if condition=='stateless' else 'persistent')
                case['sessions'] = [lesson(r, i) for i, r in enumerate(shown)]
                case['sessions'].append({'day':len(shown), 'session':'final',
                                        'prompt':final_prompt(base['target_projects'], shown, condition, base['query_plan'])})
                expected = current_gold if condition!='no_history' else {q[0]:None for q in v3.QUESTIONS}
                case['query_gold_policy'] = 'same_historical_fact_gold_for_memory_and_stateless; no_history_null_policy_separate'
                cases.append(case); gold[case['id']] = copy.deepcopy(expected)
    return cases, gold


def extract_answer(text):
    """One declared envelope only; never choose between competing answer blocks."""
    if not isinstance(text, str) or len(text)>100000:
        raise ValueError('Response must be bounded text')
    blocks = list(re.finditer(r'```([^\n`]*)\n(.*?)\n```', text, re.DOTALL))
    if len(blocks)>1:
        raise ValueError('Multiple answer blocks are ambiguous')
    try:
        parsed, mode = v3.parse_response(text)
        return parsed, mode, True
    except (ValueError, TypeError):
        if len(blocks)!=1 or blocks[0][1].strip().lower() not in ('', 'json'):
            raise ValueError('No unique declared answer envelope') from None
        parsed = strict_json(blocks[0][2])
        if not isinstance(parsed, dict):
            raise ValueError('Answer block must contain an object')
        conforms = text.strip()==blocks[0][0]
        return parsed, 'json' if conforms else 'json_with_prose', conforms


def grade(case, expected, text, error=None):
    parsed, envelope, conforms = None, None, False
    problem = None
    if not error:
        try:
            parsed, envelope, conforms = extract_answer(text)
        except (ValueError, TypeError, RecursionError) as exc:
            problem = str(exc)
    # Reuse the frozen value/alias/type contract, not its whole-response parser.
    result = v3.grade(case, expected, json.dumps(parsed, ensure_ascii=False) if parsed is not None else None, error)
    extras = sorted(set(parsed)-{q['qid'] for q in case['query_plan']}) if parsed is not None else []
    result.update(grading_contract='3.1', format=envelope, format_error=problem,
                  format_status='error' if error else 'pass' if conforms and not extras else 'fail',
                  content_envelope_observed=parsed is not None, extra_fields=extras,
                  claim_limit='Predeclared content and format scoring; no inference of native memory capacity or global deletion.')
    return result


def native_dataset(cases, gold):
    rows = v3.native_dataset(cases, gold)
    for case, row in zip(cases, rows):
        row['state_policy'] = case['state_policy']
        row['score_note'] = 'Core strict JSON equality remains supplemental. Primary V3.1 content/envelope grading is separate.'
        for step in row['steps']:
            step['output_tokens'] = 4096 if step['id']=='final' else 1024
    return rows


def reference(case, policy):
    return v3.reference(case, 'stateless' if case['condition']=='stateless' else policy)


def generate(output, seed=20261011):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases, gold = build(seed)
    v3.dump(output/'learner-cases.json', cases)
    v3.dump(output/'gold.json', gold)
    v3.dump(output/'answer-trace.evaluator.json', {c['id']:v3.answer_trace(c, gold[c['id']]) for c in cases})
    (output/'inputs.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in cases), encoding='utf-8')
    (output/'native-dataset.evaluator.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in native_dataset(cases, gold)), encoding='utf-8')
    results = []
    for policy in v3.POLICIES:
        for case in cases:
            row = grade(case, gold[case['id']], json.dumps(reference(case, policy)))
            row.update(policy=policy)
            results.append(row)
    v3.dump(output/'reference-results.json', results)
    protocol = {'version':'3.1', 'status':'offline_prepared_no_paid_run', 'seed':seed, 'paid_calls':0,
                'conditions':CONDITIONS, 'cases':len(cases), 'checks_per_case':18,
                'formal_families':['binding','updates','scope'], 'difficulty_gate':{'coverage_min':0.9,'effect_pp_min':15,'families_required':3,'directions_required_of_three':2},
                'pilot':{'family':'updates','levels':['low','high'],'conditions':['memory','stateless','open_book'],'repeats':1,'agents':['openclaw','hermes'],'final_slots':12},
                'formal':{'families':['binding','updates','scope'],'levels':['low','high'],'conditions':['memory','stateless','open_book'],'repeats':3,'final_slots':108},
                'control_scope':'Persistent-state availability, not a native module-only switch; general model/tool config is shared and previous session files must be hidden by namespace.',
                'claim_limit':'Reference strategies are software checks. Native health, genuine difficulty, repeated differences and release readiness remain untested.',
                'data_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
                'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'v3_unchanged_source_sha256':hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest()}
    v3.dump(output/'protocol.json', protocol)
    v3.write_viewer(output, cases, gold, results)
    page = (output/'index.html').read_text().replace('memory-v3-design.md','memory-v31-design.md').replace('研究档案记忆 V3','研究档案记忆 V3.1')
    page = page.replace('<option value="open_book">', '<option value="stateless">无跨会话持久状态</option><option value="open_book">')
    page = page.replace('这是一版设计与离线原型。未调用付费模型；', 'V3.1仅完成离线修订，未进行付费实测；无持久状态组与记忆组收到相同历史。')
    table='<h2>人工策略检查</h2><p>无持久状态组使用相同历史事实答案评价恢复率；它与目标资料从未提供的拒答组分开。</p><table><tr><th>预设策略</th><th>历史组</th><th>无持久状态组</th><th>完整记录组</th><th>缺资料组</th></tr>'
    for policy in v3.POLICIES:
        table+='<tr><td>'+policy+'</td>'
        for condition in CONDITIONS:
            selected=[r for r in results if r['policy']==policy and r['condition']==condition]
            table+='<td>'+str(sum(r['correct_count'] for r in selected))+'/'+str(sum(r['check_count'] for r in selected))+'</td>'
        table+='</tr>'
    page=re.sub(r'<h2>人工策略检查</h2>.*?</table>',table+'</table>',page,flags=re.DOTALL)
    page=page.replace('；每例查询18项。负载：','；每例查询18项。状态策略：${c.state_policy}。负载：')
    (output/'index.html').write_text(page, encoding='utf-8')
    return protocol


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261011)
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.seed), ensure_ascii=False))
