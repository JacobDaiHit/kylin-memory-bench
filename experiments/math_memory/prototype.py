"""Generate and inspect a research-workflow memory benchmark, without API calls.

python -m experiments.math_memory.prototype --output experiments/math_memory/demo
The public JSONL is an INPUT-only protocol. gold.json is evaluator-only.
"""
import argparse
import copy
import hashlib
import html
import json
import random
from pathlib import Path

from .math_core import make_inputs, solve, rational_equal, determinant_series


PROFILES = [('interference-low', 0, 1, 4, False),
            ('interference-high', 12, 1, 4, False),
            ('revisions-low', 2, 1, 6, False),
            ('revisions-high', 2, 4, 6, False),
            ('reasoning-low', 2, 1, 4, False),
            ('reasoning-high', 2, 1, 6, False),
            ('applicability-regular', 2, 1, 6, False),
            ('applicability-singular', 2, 1, 6, True)]
METHOD = '''研究方法约定：H(e)=[[e²A,eB],[eBᵀ,diag(D)]]，P维数2。
若D可逆且K=A-BD⁻¹Bᵀ的指定分支为简单特征值，可以使用Schur消元展开。
按指定阶数求λ(e)=c2 e²+c4 e⁴+c6 e⁶；四阶任务c6=null。
证书需包含K、r11=uᵀBD⁻²Bᵀu/(uᵀu)、r12=uᵀBD⁻²Bᵀv/(uᵀu)、
t11=uᵀBD⁻³Bᵀu/(uᵀu)，v=(-u2,u1)。令t=e²，mu=c2+t*c4+t²*c6，
证书residual为det(A-mu I-B(diag(D)-t*mu I)⁻¹Bᵀ)的常数、一阶、二阶系数；
四阶只提交常数与一阶。必须检查方法适用性，不要求在不适用时解另一种展开。
只有accepted研究记录有效，draft不覆盖accepted；记录编号大小不代表批准。
同一项目后来到达的accepted snapshot替代此前快照，按会话时间顺序确定当前版本。
sources顺序固定为B记录、branch记录、当前snapshot记录。
不要借用相近项目。资料不齐返回insufficient；D奇异/分支不简单返回method_invalid。
''' 
SCHEMA = {'inputs': {'A': '2x2有理数数组', 'B': '2xq有理数数组',
                     'D': 'q个有理数', 'branch': {'vector': '2个有理数',
                     'kappa': '有理数', 'other': '有理数'},
                     'version': '当前批准版本', 'sources': '三份有效记录ID'},
          'result': {'status': 'ok|method_invalid|insufficient', 'c2': '有理数|null',
                     'c4': '有理数|null', 'c6': '有理数|null',
                     'certificate': {'K': '2x2数组|null', 'r11': '有理数|null',
                     'r12': '有理数|null', 't11': '有理数|null', 'residual': '数组|null'}}}


def record(project, kind, payload, source, status='accepted'):
    return {'project': project, 'kind': kind, 'payload': payload,
            'source': source, 'status': status}


def notes(project, inputs, version, status='accepted'):
    return [record(project, 'coupling', {'B': inputs['B']}, project+'-B'),
            record(project, 'branch', {'branch': inputs['branch']}, project+'-branch'),
            record(project, 'snapshot', {k: inputs[k] for k in ('A', 'D')} |
                   {'version': version}, project+'-'+version, status)]


def build(seed=20261011):
    rng = random.Random(seed)
    project = 'SCHUR-'+str(rng.randrange(100000, 999999))
    B = [[rng.choice([-2, -1, 1, 2]) for _ in range(3)] for _ in range(2)]
    vector = (1, 2)
    versions = []
    for index in range(5):
        versions.append(make_inputs(B, [2+index, 5+index, 9+index], vector,
                                   2, 7, 'v'+str(index),
                                   [project+'-B', project+'-branch', project+'-v'+str(index)]))
    cases, gold = [], {}
    for name, interference, revisions, order, singular in PROFILES:
        final = copy.deepcopy(versions[4])
        if singular:
            final['D'][0] = '0'
        snapshots = [versions[0]] + ([versions[4]] if revisions == 1 else versions[1:])
        snapshots = copy.deepcopy(snapshots)
        snapshots[-1] = copy.deepcopy(final)
        history = notes(project, versions[0], 'v0')
        history += [notes(project, item, item['version'])[-1] for item in snapshots[1:]]
        # A tempting, later draft changes all blocks but must never become current.
        draft = make_inputs(B, [17, 19, 23], vector, 2, 7, 'v99')
        history.append(notes(project, draft, 'v99', 'draft')[-1])
        distractors = []
        for j in range(interference):
            nearby = project+'-archive-'+str(j)
            other = make_inputs([[1, 2, 1], [2, -1, j+1]], [3, 7, 11],
                                vector, 3, 8, 'v4')
            distractors += notes(nearby, other, 'v4')
        history += distractors
        for condition in ('memory', 'oracle', 'no_history'):
            cid = name+'--'+condition
            selected = history if condition != 'no_history' else distractors
            prompt = METHOD + '\n目标项目：'+project+'；展开至'+str(order)+'阶。\n'
            prompt += '输出严格JSON，形状：'+json.dumps(SCHEMA, ensure_ascii=False)+'\n'
            prompt += '资料不足时inputs=null，所有系数与证书字段=null。方法不适用时保留inputs，其余同前。\n'
            prompt += '把完整回答写入deliverables/research-certificate.json，并返回同一JSON。\n'
            if condition == 'oracle':
                prompt += '本次直接提供完整的当前有效输入（不含答案）：\nCURRENT_INPUTS='+json.dumps(final)+'\n'
            cases.append({'id': cid, 'profile': name, 'condition': condition,
                          'project': project, 'order': order,
                          'sessions': [{'day': i+1, 'prompt': '研究笔记，请保留：\nRECORD='+
                                        json.dumps(item, ensure_ascii=False)} for i, item in enumerate(selected)] +
                                      [{'day': len(selected)+1, 'prompt': prompt}],
                          'loads': {'distractor_projects': interference,
                                    'accepted_updates': revisions}})
            expected_inputs = None if condition == 'no_history' else final
            gold[cid] = {'inputs': expected_inputs, 'result': solve(expected_inputs, order)}
    return cases, gold


def recall(case, policy='complete'):
    """Synthetic baselines read only learner prompts, never gold.json."""
    states = {}
    for session in case['sessions']:
        prompt = session['prompt']
        if 'CURRENT_INPUTS=' in prompt:
            return json.loads(prompt.split('CURRENT_INPUTS=', 1)[1].splitlines()[0])
        if 'RECORD=' not in prompt or policy == 'stateless':
            continue
        item = json.loads(prompt.split('RECORD=', 1)[1])
        if item['status'] != 'accepted':
            continue
        key = '*' if policy == 'scope_blind' else item['project']
        state = states.setdefault(key, {})
        if policy == 'stale' and item['kind'] == 'snapshot' and 'A' in state:
            continue
        state.update(item['payload'])
        state.setdefault('sources_by_kind', {})[item['kind']] = item['source']
    state = states.get('*' if policy == 'scope_blind' else case['project'])
    if not state or not all(k in state for k in ('A', 'B', 'D', 'branch', 'version')):
        return None
    state = copy.deepcopy(state)
    sources = state.pop('sources_by_kind')
    state['sources'] = [sources[k] for k in ('coupling', 'branch', 'snapshot')]
    return state


def input_equal(expected, actual):
    if expected is None:
        return actual is None
    if not isinstance(actual, dict) or set(expected) != set(actual):
        return False
    return all(rational_equal(expected[k], actual[k]) for k in ('A', 'B', 'D', 'branch')) and all(
        expected[k] == actual[k] for k in ('version', 'sources'))


def result_equal(expected, actual):
    return isinstance(actual, dict) and set(actual) == set(expected) and actual.get('status') == expected['status'] and all(
        rational_equal(expected[k], actual[k]) for k in ('c2', 'c4', 'c6', 'certificate'))


def grade(case, expected, answer, artifact=None):
    try:
        value = json.loads(answer) if isinstance(answer, str) else answer
        if not isinstance(value, dict) or set(value) != {'inputs', 'result'}:
            raise ValueError('Top-level schema mismatch')
        result = value['result']
        if not isinstance(result, dict) or set(result) != set(SCHEMA['result']):
            raise ValueError('Result schema mismatch')
        certificate = result['certificate']
        if not isinstance(certificate, dict) or set(certificate) != set(SCHEMA['result']['certificate']):
            raise ValueError('Certificate schema mismatch')
        if result['status'] not in ('ok', 'method_invalid', 'insufficient'):
            raise ValueError('Unknown status')
        if value['inputs'] is not None and (not isinstance(value['inputs'], dict) or
                                           set(value['inputs']) != set(SCHEMA['inputs'])):
            raise ValueError('Inputs schema mismatch')
        input_ok = input_equal(expected['inputs'], value['inputs'])
        result_ok = result_equal(expected['result'], value['result'])
        try:
            self_consistent = result_equal(solve(value['inputs'], case['order']), value['result'])
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
            self_consistent = False
        # Do not trust a self-reported zero residual: recompute with submitted coefficients.
        algebra = None
        if value['result'].get('status') == 'ok' and value['inputs'] is not None:
            try:
                coeffs = [value['result']['c2'], value['result']['c4'], value['result']['c6'] or '0']
                residual = determinant_series(value['inputs'], coeffs)
                algebra = all(x == 0 for x in residual[:3 if case['order'] == 6 else 2])
            except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError):
                algebra = False
        file_ok = None
        if artifact is not None:
            try:
                file_ok = json.loads(Path(artifact).read_text()) == value
            except (OSError, ValueError):
                file_ok = False
        return {'format': True, 'inputs': input_ok, 'math': result_ok,
                'math_given_correct_inputs': result_ok if input_ok and expected['inputs'] is not None else None,
                'consistent_with_reported_inputs': self_consistent, 'algebra_residual': algebra,
                'abstention': result_ok if case['condition'] == 'no_history' else None,
                'artifact': file_ok, 'tool_trace': 'not_observed'}
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return {'format': False, 'inputs': None, 'math': None,
                'math_given_correct_inputs': None, 'consistent_with_reported_inputs': None,
                'algebra_residual': None, 'abstention': None, 'artifact': None,
                'tool_trace': 'not_observed'}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('experiments/math_memory/demo'))
    parser.add_argument('--seed', type=int, default=20261011)
    parser.add_argument('--grade-case', help='Grade an external answer using existing frozen files')
    parser.add_argument('--answer', type=Path)
    parser.add_argument('--artifact', type=Path)
    args = parser.parse_args()
    if args.grade_case:
        if args.answer is None:
            parser.error('--grade-case requires --answer')
        freeze = json.loads((args.output/'freeze.json').read_text())
        for name, key in [('inputs.jsonl', 'input_sha256'), ('gold.json', 'gold_sha256')]:
            if hashlib.sha256((args.output/name).read_bytes()).hexdigest() != freeze[key]:
                parser.error('Frozen data fingerprint mismatch: '+name)
        cases = [json.loads(line) for line in (args.output/'inputs.jsonl').read_text().splitlines()]
        case = next((c for c in cases if c['id'] == args.grade_case), None)
        if case is None:
            parser.error('Case ID not found')
        gold = json.loads((args.output/'gold.json').read_text())
        print(json.dumps(grade(case, gold[case['id']], args.answer.read_text(), args.artifact),
                         ensure_ascii=False, indent=2))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    cases, gold = build(args.seed)
    public = args.output/'inputs.jsonl'
    public.write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in cases), encoding='utf-8')
    dump(args.output/'gold.json', gold)
    rows = []
    for policy in ('complete', 'stale', 'scope_blind', 'stateless', 'wrong_math'):
        for case in cases:
            inputs = recall(case, 'complete' if policy == 'wrong_math' else policy)
            result = solve(inputs, case['order'])
            if policy == 'wrong_math' and result['status'] == 'ok' and case['order'] == 6:
                from .math_core import rational
                result['c6'] = str(rational(result['c6'])+1)
            answer = {'inputs': inputs, 'result': result}
            destination = args.output/'reference-artifacts'/policy/case['id']/'deliverables'
            destination.mkdir(parents=True, exist_ok=True)
            artifact = destination/'research-certificate.json'
            dump(artifact, answer)
            rows.append({'policy': policy, 'case': case['id'], 'condition': case['condition'],
                         **grade(case, gold[case['id']], answer, artifact)})
    dump(args.output/'reference-results.json', rows)
    freeze = {'seed': args.seed, 'cases': len(cases), 'status': 'exploratory-not-native-agent-results',
              'input_sha256': hashlib.sha256(public.read_bytes()).hexdigest(),
              'gold_sha256': hashlib.sha256((args.output/'gold.json').read_bytes()).hexdigest(),
              'sources_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in Path(__file__).parent.glob('*.py')}}
    dump(args.output/'freeze.json', freeze)
    headers = ['策略', '实例', '输入正确', '数学正确', '自述条件下成立', '实际文件一致']
    table = ''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in
                    [r['policy'], r['case'], r['inputs'], r['math'],
                     r['consistent_with_reported_inputs'], r['artifact']])+'</tr>' for r in rows)
    detail = ''.join('<details><summary>'+html.escape(c['id'])+'</summary><pre>'+html.escape(
                    json.dumps(c, ensure_ascii=False, indent=2))+'</pre></details>' for c in cases)
    page = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>数学研究记忆原型</title>
<style>body{max-width:1100px;margin:32px auto;padding:16px;font:16px/1.6 sans-serif;color:#182634}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:7px;border:1px solid #ccd5df}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f6;padding:16px}summary{cursor:pointer}</style>
<h1>数学研究记忆 benchmark：可检查原型</h1>
<p>24个输入实例 × 5种人工参考策略。全部离线、未调用模型、费用为零。
这些结果检查题目和评分器能否定位预设故障，不证明真实智能体难度或排名。</p>
<p>流程：研究笔记 → 当前条件重建 → Schur展开 → 有理数证书 → 实际JSON文件。
memory依赖历史；oracle在最后一轮重给完整输入；no_history撤去目标资料，检查拒绝编造。</p>
<p><a href="inputs.jsonl">智能体输入</a> · <a href="gold.json">评分端答案（勿注入智能体）</a> ·
<a href="freeze.json">冻结指纹</a> · <a href="reference-results.json">逐项参考结果</a> ·
<a href="../README.md">设计说明</a></p><h2>参考策略结果</h2><table><thead><tr>'''
    page += ''.join('<th>'+h+'</th>' for h in headers)+'</tr></thead><tbody>'+table+'</tbody></table>'
    page += '<h2>展开查看逐轮材料</h2>'+detail+'</html>'
    (args.output/'index.html').write_text(page, encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'cases': len(cases), 'reference_checks': len(rows),
                      'complete_pass': all(r['inputs'] and r['math'] for r in rows if r['policy'] == 'complete'),
                      'model_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
