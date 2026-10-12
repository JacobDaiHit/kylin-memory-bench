#!/usr/bin/env python3
"""Replay a frozen 12-case, three-trial native-agent difficulty experiment.

This is a descriptive acceptance gate, not a significance test or a general
leaderboard. Original scores and raw evidence are never rewritten.
"""
import argparse
import csv
import html
import io
import os
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, pstdev
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import (BenchError, DIMENSIONS, canonical, digest,
                                      file_digest, read_json, write_json, write_text)
from kylin_memory_bench.runner import read_run, verify_run

DOMAINS = ('content', 'format', 'artifact', 'action', 'memory')
ABILITY_DOMAINS = frozenset(('content', 'artifact', 'action'))
LEVELS = ('low', 'high')
OBSERVATION_THRESHOLD = .9
DROP_THRESHOLD = .15
MIN_EFFECT_FAMILIES = 3


def effective(check):
    return (check['status'] in ('pass', 'fail') and
            check['category'] != 'invalid_response')


def observation(checks):
    """Unweighted, predeclared check counts; never silently drop nonobservations."""
    checks = list(checks)
    observed = [c for c in checks if effective(c)]
    correct = sum(c['status'] == 'pass' for c in observed)
    return {'check_count': len(checks), 'effective_count': len(observed),
            'correct_count': correct,
            'effective_observation_rate': len(observed) / len(checks) if checks else None,
            'effective_correct_rate': correct / len(observed) if observed else None,
            'status_counts': dict(sorted(Counter(c['status'] for c in checks).items())),
            'category_counts': dict(sorted(Counter(c['category'] for c in checks).items())),
            'format_invalid_count': sum(c['category'] == 'invalid_response' for c in checks),
            'execution_error_count': sum(c['status'] == 'error' for c in checks),
            'unknown_count': sum(c['status'] == 'unknown' for c in checks)}


def classify(checks):
    """Four exclusive groups: any missing observation makes a task indeterminate."""
    checks = list(checks)
    if not checks or any(not effective(c) for c in checks):
        return 'indeterminate'
    statuses = {c['status'] for c in checks}
    if statuses == {'pass'}:
        return 'all_pass'
    if statuses == {'fail'}:
        return 'all_fail'
    return 'disagreement'


def composition(groups):
    counts = Counter(classify(checks) for checks in groups)
    total = sum(counts.values())
    names = ('all_pass', 'all_fail', 'disagreement', 'indeterminate')
    return {'total': total, 'counts': {n: counts[n] for n in names},
            'proportions': {n: counts[n] / total if total else None for n in names}}


def validate_design(manifest, cases):
    if manifest.get('status') not in ('completed', 'completed_with_errors'):
        raise BenchError('Difficulty analysis requires a completed run, including recorded errors.')
    if manifest.get('repeats') != 3 or len(cases) != 12:
        raise BenchError('Expected exactly 12 cases and three trials.')
    agents = manifest.get('agents', [])
    if len(agents) != 2 or {a.get('kind') for a in agents} != {'openclaw', 'hermes'}:
        raise BenchError('Expected one native OpenClaw and one native Hermes agent; baselines are not accepted.')
    if len({a.get('id') for a in agents}) != 2:
        raise BenchError('Agent IDs must be distinct.')
    pairs = {}
    for case in cases:
        pair, level = case.get('difficulty_pair'), case.get('difficulty_level')
        if not isinstance(pair, str) or not pair or level not in LEVELS:
            raise BenchError('Every case needs difficulty_pair and difficulty_level=low/high.')
        if pair not in pairs:
            pairs[pair] = {}
        if level in pairs[pair]:
            raise BenchError('Each difficulty family must have exactly one low and one high case.')
        pairs[pair][level] = case
        checks = [c for s in case['steps'] for c in s.get('checks', [])]
        if not checks or not any(c.get('measurement_domain') in ABILITY_DOMAINS for c in checks):
            raise BenchError('Every case needs at least one predeclared ability-domain check.')
        if any(c.get('measurement_domain') not in DOMAINS for c in checks):
            raise BenchError('Every check needs a known measurement_domain.')
        source_domains = {'response': {'content', 'format'}, 'artifact': {'artifact'},
                          'actions': {'action'}, 'memory': {'memory'}}
        if any(c['measurement_domain'] not in source_domains.get(c['source'], set()) for c in checks):
            raise BenchError('measurement_domain must agree with the actual evidence source.')
    if len(pairs) != 6 or any(set(p) != set(LEVELS) for p in pairs.values()):
        raise BenchError('Expected six complete low/high difficulty families.')
    dimensions = []
    for pair in pairs.values():
        if pair['low']['dimension'] != pair['high']['dimension']:
            raise BenchError('Paired cases must measure the same dimension.')
        # Check weights remain in original scoring. This analysis counts ability
        # judgments equally, requiring matched numbers and domains to avoid a
        # changing denominator masquerading as a difficulty effect.
        signature = lambda c: Counter(x['measurement_domain'] for s in c['steps']
                                      for x in s.get('checks', [])
                                      if x['measurement_domain'] in ABILITY_DOMAINS)
        if signature(pair['low']) != signature(pair['high']):
            raise BenchError('Low/high ability-check domain counts must match.')
        dimensions.append(pair['low']['dimension'])
    if set(dimensions) != set(DIMENSIONS) or len(dimensions) != len(set(dimensions)):
        raise BenchError('Expected one low/high family in each of the six dimensions.')
    return pairs


def summarize(manifest, cases, scores):
    """Pure descriptive statistics over already verified, independently replayed scores."""
    pairs = validate_design(manifest, cases)
    case_map = {c['id']: c for c in cases}
    check_map = {(c['id'], s['id'], x['id']): x
                 for c in cases for s in c['steps'] for x in s.get('checks', [])}
    records, executions = [], []
    expected_rows = {(a['id'], t, c['id']) for a in manifest['agents']
                     for t in range(3) for c in cases}
    seen = set()
    for agent in scores['agents']:
        for row in agent['cases']:
            key = (agent['id'], row['trial'], row['case_id'])
            if key not in expected_rows or key in seen:
                raise BenchError('Unexpected or duplicate case/trial in replayed scores.')
            seen.add(key)
            case = case_map[row['case_id']]
            added = []
            for result in row['checks']:
                rule = check_map[(case['id'], result['step_id'], result['check_id'])]
                if result['status'] not in ('pass', 'fail', 'unknown', 'error'):
                    raise BenchError('Unknown replayed check status.')
                item = {'agent_id': agent['id'], 'agent_kind': agent['kind'],
                        'trial': row['trial'], 'case_id': case['id'],
                        'difficulty_pair': case['difficulty_pair'],
                        'difficulty_level': case['difficulty_level'],
                        'dimension': case['dimension'],
                        'measurement_domain': rule['measurement_domain'],
                        'step_id': result['step_id'], 'check_id': result['check_id'],
                        'source': result['source'], 'status': result['status'],
                        'category': result['category'], 'reason': result['reason'],
                        'event_id': result['evidence_id']}
                item['ability_eligible'] = item['measurement_domain'] in ABILITY_DOMAINS
                item['effectively_observed'] = effective(item)
                item['failure_origin'] = ('format' if item['category'] == 'invalid_response' else
                                          'execution' if item['status'] == 'error' else
                                          'evidence' if item['status'] == 'unknown' else
                                          item['measurement_domain'])
                records.append(item)
                added.append(item)
            expected = {(s['id'], x['id']) for s in case['steps'] for x in s.get('checks', [])}
            if {(x['step_id'], x['check_id']) for x in added} != expected or len(added) != len(expected):
                raise BenchError('Incomplete or duplicate check results.')
            ability = [x for x in added if x['ability_eligible']]
            executions.append({'agent_id': agent['id'], 'trial': row['trial'],
                               'case_id': case['id'], 'classification': classify(ability),
                               **observation(ability)})
    if seen != expected_rows:
        raise BenchError('Missing case/trial results.')
    records.sort(key=lambda r: (r['difficulty_pair'], r['difficulty_level'],
                               r['trial'], r['agent_id'], r['step_id'], r['check_id']))
    executions.sort(key=lambda r: (r['case_id'], r['trial'], r['agent_id']))
    ability = [r for r in records if r['ability_eligible']]
    agent_ids = [a['id'] for a in manifest['agents']]
    families = []
    for pair_id, levels in sorted(pairs.items()):
        selected = [r for r in ability if r['difficulty_pair'] == pair_id]
        trials = []
        for trial in range(3):
            rates = {level: observation(r for r in selected if r['trial'] == trial and
                                      r['difficulty_level'] == level) for level in LEVELS}
            low, high = (rates[x]['effective_correct_rate'] for x in LEVELS)
            trials.append({'trial': trial, **rates,
                           'drop': low - high if low is not None and high is not None else None})
        drops = [r['drop'] for r in trials if r['drop'] is not None]
        mean_drop = mean(drops) if len(drops) == 3 else None
        direction_count = sum(x > 0 for x in drops)
        difficulty_effect = (mean_drop is not None and
                             mean_drop + 1e-12 >= DROP_THRESHOLD and direction_count >= 2)
        comparisons = []
        for trial in range(3):
            rates = {agent: observation(r for r in selected if r['trial'] == trial and
                                       r['agent_id'] == agent) for agent in agent_ids}
            first, second = (rates[x]['effective_correct_rate'] for x in agent_ids)
            comparisons.append({'trial': trial, 'agents': rates,
                                'difference': first - second if first is not None and second is not None else None})
        positive = sum(r['difference'] is not None and r['difference'] > 0 for r in comparisons)
        negative = sum(r['difference'] is not None and r['difference'] < 0 for r in comparisons)
        favored = agent_ids[0] if positive >= 2 else agent_ids[1] if negative >= 2 else None
        by_agent = {}
        for agent in agent_ids:
            agent_trials = []
            for trial in range(3):
                rates = {level: observation(r for r in selected if r['agent_id'] == agent and
                                          r['trial'] == trial and r['difficulty_level'] == level)
                         for level in LEVELS}
                low, high = (rates[level]['effective_correct_rate'] for level in LEVELS)
                agent_trials.append({'trial': trial, **rates,
                                     'drop': low - high if low is not None and high is not None else None})
            agent_drops = [r['drop'] for r in agent_trials if r['drop'] is not None]
            by_agent[agent] = {
                'levels': {level: observation(r for r in selected if r['agent_id'] == agent and
                                             r['difficulty_level'] == level) for level in LEVELS},
                'trials': agent_trials,
                'mean_drop': mean(agent_drops) if len(agent_drops) == 3 else None,
                'drop_stddev': pstdev(agent_drops) if len(agent_drops) == 3 else None}
        families.append({'difficulty_pair': pair_id, 'dimension': levels['low']['dimension'],
                         'cases': {l: levels[l]['id'] for l in LEVELS},
                         'trials': trials, 'mean_drop': mean_drop,
                         'drop_stddev': pstdev(drops) if len(drops) == 3 else None,
                         'strict_positive_drop_trials': direction_count,
                         'difficulty_effect': difficulty_effect,
                         'by_agent': by_agent,
                         'agent_comparisons': comparisons,
                         'stable_observed_difference': favored is not None,
                         'favored_agent': favored,
                         'difference_direction_trials': {'first_higher': positive, 'second_higher': negative}})
    global_observation = observation(ability)
    enough_observation = (global_observation['effective_observation_rate'] is not None and
                          global_observation['effective_observation_rate'] >= OBSERVATION_THRESHOLD)
    effect_count = sum(f['difficulty_effect'] for f in families)
    passed = enough_observation and effect_count >= MIN_EFFECT_FAMILIES
    warnings = []
    if not enough_observation:
        warnings.append('Ability effective observation is below 90%; format, execution and missing evidence must be investigated.')
    if effect_count < MIN_EFFECT_FAMILIES:
        warnings.append('Fewer than three families meet the descriptive difficulty-effect gate; difficulty sufficiency is unproven.')
    if any(f['stable_observed_difference'] for f in families):
        warnings.append('Observed family differences are conditional on this dataset/configuration and are not a general agent ranking.')
    else:
        warnings.append('No stable family-level system difference was observed; no ranking is inferred.')
    warnings.append('Effective-only correctness can be selection-biased; always inspect per-level coverage and nonobservation causes.')
    per_case = [[r for r in ability if r['case_id'] == c['id']] for c in cases]
    per_execution = [[r for r in ability if (r['agent_id'], r['trial'], r['case_id']) ==
                      (e['agent_id'], e['trial'], e['case_id'])] for e in executions]
    result = {'schema_version': '1.0', 'analysis_kind': 'predeclared_descriptive_difficulty_gate',
              'status': 'passed_gate' if passed else 'failed_gate',
              'summary': {'run_id': manifest['run_id'], 'case_count': len(cases), 'repeats': 3,
                          'agent_ids': agent_ids, 'ability_effective_observation_rate': global_observation['effective_observation_rate'],
                          'difficulty_effect_family_count': effect_count,
                          'required_difficulty_effect_families': MIN_EFFECT_FAMILIES,
                          'stable_difference_family_count': sum(f['stable_observed_difference'] for f in families)},
              'thresholds': {'effective_observation_rate_min': OBSERVATION_THRESHOLD,
                             'mean_low_minus_high_min': DROP_THRESHOLD,
                             'strict_positive_drop_trials_min': 2, 'effect_families_min': MIN_EFFECT_FAMILIES},
              'definitions': {
                  'ability_domains': sorted(ABILITY_DOMAINS),
                  'effective': 'pass/fail with category != invalid_response; memory/format domains excluded from ability gate',
                  'correctness': 'unweighted passed eligible checks / effectively observed eligible checks; null for no observations',
                  'pooled_family_trial': 'pool both agents equally at the predeclared check-count level per family/level/trial',
                  'mean_drop': 'mean of three pooled trial low-minus-high correctness differences; null if any trial is unobserved',
                  'stable_difference': 'same strict agent-correctness difference direction in at least two of three trials, pooling low/high; not significance',
                  'composition': 'exclusive: all_pass/all_fail require every eligible check observed and identical status; disagreement requires fully observed mixed pass/fail; any nonobservation makes indeterminate',
                  'case_composition_unit': 'one designed case across both agents and all three trials (12 total)',
                  'execution_composition_unit': 'one agent/case/trial execution (72 total)',
                  'interpretation': 'descriptive preregistered project thresholds, not a statistical significance test or proof of construct validity'},
              'source': {'run_id': manifest['run_id'], 'dataset_sha256': manifest['dataset_sha256'],
                         'evidence_chain_head': manifest['evidence_head'],
                         'implementation_sha256': manifest.get('implementation_sha256'),
                         'environment': manifest.get('environment', {})},
              'overall_ability': global_observation,
              'by_domain': {d: observation(r for r in records if r['measurement_domain'] == d) for d in DOMAINS},
              'failure_origins': dict(sorted(Counter(r['failure_origin'] for r in records if r['status'] != 'pass').items())),
              'case_composition': composition(per_case), 'execution_composition': composition(per_execution),
              'families': families, 'executions': executions, 'checks': records, 'warnings': warnings}
    return result


def calculate(run):
    verify_run(run)
    manifest, cases, events, scores = read_run(run)
    result = summarize(manifest, cases, scores)
    result['source']['file_sha256'] = {n: file_digest(Path(run) / n) for n in
                                      ('manifest.json', 'dataset.jsonl', 'config.json', 'evidence.jsonl', 'scores.json')}
    result['source']['event_count'] = len(events)
    return result


def render_html(result, evidence_href):
    def esc(x):
        return html.escape(str(x), quote=True)
    def pct(x):
        return '不可观测' if x is None else f'{x * 100:.2f}%'
    headings = '<tr><th>任务家族</th><th>低−高均值</th><th>同向轮数</th><th>难度效应</th><th>系统差异</th></tr>'
    rows = []
    system_rows = []
    for f in result['families']:
        rows.append('<tr><td>' + esc(DIMENSIONS[f['dimension']]) + '</td><td>' + pct(f['mean_drop']) +
                    '</td><td>' + str(f['strict_positive_drop_trials']) + '/3</td><td>' +
                    ('达到门槛' if f['difficulty_effect'] else '未达到') + '</td><td>' +
                    esc(f['favored_agent'] or '未观察到稳定差异') + '</td></tr>')
        for agent, data in f['by_agent'].items():
            low, high = (data['levels'][level] for level in LEVELS)
            system_rows.append('<tr><td>' + esc(DIMENSIONS[f['dimension']]) + '</td><td>' + esc(agent) +
                               '</td><td>' + pct(low['effective_correct_rate']) + '</td><td>' +
                               pct(high['effective_correct_rate']) + '</td><td>' +
                               pct(low['effective_observation_rate']) + ' / ' + pct(high['effective_observation_rate']) +
                               '</td><td>' + pct(data['mean_drop']) + '</td><td>' + pct(data['drop_stddev']) + '</td></tr>')
    domain_rows = []
    for domain, data in result['by_domain'].items():
        domain_rows.append('<tr><td>' + esc(domain) + '</td>' +
                           ''.join('<td>' + str(data[k]) + '</td>' for k in
                                   ('check_count', 'effective_count', 'correct_count', 'format_invalid_count',
                                    'execution_error_count', 'unknown_count')) + '</tr>')
    execution_rows = []
    for data in result['executions']:
        execution_rows.append('<tr>' + ''.join('<td>' + esc(data[k]) + '</td>' for k in
                              ('agent_id', 'trial', 'case_id', 'classification')) +
                              '<td>' + str(data['correct_count']) + '/' + str(data['effective_count']) +
                              '</td><td>' + pct(data['effective_observation_rate']) + '</td></tr>')
    detail = []
    for r in result['checks']:
        event = ('<a href="' + esc(evidence_href + '#event-' + quote(str(r['event_id']), safe='')) + '">#' +
                 esc(r['event_id']) + '</a>') if r['event_id'] else '无事件'
        detail.append('<tr>' + ''.join('<td>' + esc(r[k]) + '</td>' for k in
                      ('agent_id', 'trial', 'case_id', 'difficulty_level', 'measurement_domain', 'status', 'category')) +
                      '<td>' + event + '</td><td>' + esc(r['reason']) + '</td></tr>')
    warnings = ''.join('<li>' + esc(w) + '</li>' for w in result['warnings'])
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>难度与区分度前置试测</title><style>body{font:16px/1.7 system-ui,sans-serif;margin:32px;color:#17324b;max-width:1400px}'
            'table{border-collapse:collapse;width:100%;margin:20px 0}th,td{border:1px solid #ccd8df;padding:8px;text-align:left}'
            'th{background:#edf4f8}aside{background:#fff0cd;padding:20px}code{overflow-wrap:anywhere}.scroll{overflow:auto}'
            '</style><h1>难度与区分度前置试测</h1><aside><strong>' +
            ('描述性验收通过' if result['status'] == 'passed_gate' else '描述性验收未通过：暂停难度充分／能力排名主张') +
            '</strong><p>能力有效观测率 ' + pct(result['overall_ability']['effective_observation_rate']) +
            '；难度效应家族 ' + str(result['summary']['difficulty_effect_family_count']) +
            '/6。阈值为项目预先固定的描述性门槛，不代表统计显著性。</p></aside>'
            '<p>来源运行：<code>' + esc(result['source']['run_id']) + '</code>。两款原生智能体，各三轮，12 个实例。'
            '只读重放，未修改原始运行。</p><p>能力统计使用 content / artifact / action；格式无法解析、执行错误及证据不足'
            '都留在观测率分母中，memory 仅作诊断。正确率只在有效观测判据中计算，无观测用 null。</p>'
            '<h2>配对难度与条件性系统差异</h2><table>' + headings + ''.join(rows) + '</table>'
            '<h2>两款系统的低／高负载对照</h2><p>正确率仅使用有效观测；每轮差值与其总体标准差'
            '列于下表，不以未观测项冒充失败或正确。样本仅三轮。</p><table><tr><th>家族</th><th>系统</th>'
            '<th>低正确率</th><th>高正确率</th><th>低／高观测率</th><th>三轮平均下降</th><th>下降标准差</th></tr>' +
            ''.join(system_rows) + '</table><h2>判据来源与失分性质</h2><table><tr><th>域</th><th>总判据</th>'
            '<th>有效</th><th>通过</th><th>格式不可解析</th><th>执行错误</th><th>证据未知</th></tr>' +
            ''.join(domain_rows) + '</table>'
            '<h2>判题组成</h2><p>每个设计题聚合两款系统及三轮：<code>' + esc(canonical(result['case_composition'])) +
            '</code></p><p>每次 agent/case/trial 执行：<code>' + esc(canonical(result['execution_composition'])) +
            '</code></p><p>全通过／全失败要求所有能力判据有效且状态一致；全部有效但 pass/fail 混合为有分歧；'
            '任何非观测均为不可判。类别互斥，混合 unknown 不算全通过。</p>'
            '<h2>限制与解释</h2><ul>' + warnings + '</ul><p><a href="difficulty-summary.json">完整 JSON</a> · '
            '<a href="difficulty-checks.csv">逐判据 CSV</a> · <a href="difficulty-families.csv">逐家族每轮 CSV</a></p>'
            '<h2>逐题、逐系统、逐轮表现</h2><table><tr><th>系统</th><th>轮次（从0起）</th><th>案例</th>'
            '<th>互斥分类</th><th>通过／有效判据</th><th>有效观测率</th></tr>' + ''.join(execution_rows) + '</table>'
            '<h2>逐项证据</h2><div class="scroll"><table><tr><th>智能体</th><th>轮次（从0起）</th><th>案例</th>'
            '<th>难度</th><th>域</th><th>状态</th><th>类别</th><th>事件</th><th>原因</th></tr>' + ''.join(detail) +
            '</table></div></html>')


def csv_text(rows, fields):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def publish(result, run, output):
    output, run = Path(output), Path(run)
    if output.exists():
        raise BenchError('Output already exists; choose a new directory (or use --check).')
    try:
        output.resolve().relative_to(run.resolve())
    except ValueError:
        pass
    else:
        raise BenchError('Analysis output must be outside the original run directory.')
    try:
        evidence_href = Path(os.path.relpath(run / 'evidence.html', output)).as_posix()
    except ValueError as exc:
        raise BenchError('Source and analysis must share a filesystem volume for portable relative evidence links.') from exc
    evidence_href = quote(evidence_href, safe='/')
    output.mkdir(parents=True)
    write_json(output / 'difficulty-summary.json', result)
    fields = ('agent_id', 'agent_kind', 'trial', 'case_id', 'difficulty_pair', 'difficulty_level',
              'dimension', 'measurement_domain', 'step_id', 'check_id', 'source', 'status', 'category',
              'ability_eligible', 'effectively_observed', 'failure_origin', 'event_id', 'reason')
    write_text(output / 'difficulty-checks.csv', csv_text(result['checks'], fields))
    rows = []
    for f in result['families']:
        for t in f['trials']:
            rows.append({'family': f['difficulty_pair'], 'dimension': f['dimension'], 'trial': t['trial'],
                         'low_correct_rate': t['low']['effective_correct_rate'],
                         'high_correct_rate': t['high']['effective_correct_rate'],
                         'low_observation_rate': t['low']['effective_observation_rate'],
                         'high_observation_rate': t['high']['effective_observation_rate'],
                         'drop': t['drop'], 'family_mean_drop': f['mean_drop'],
                         'difficulty_effect': f['difficulty_effect'], 'favored_agent': f['favored_agent']})
    write_text(output / 'difficulty-families.csv', csv_text(rows, tuple(rows[0])))
    write_text(output / 'report.html', render_html(result, evidence_href))
    hashes = '\n'.join('- ' + n + ': `' + value + '`' for n, value in result['source']['file_sha256'].items())
    write_text(output / 'README.md', '# 难度与区分度前置试测\n\n'
               '来源运行：`' + result['source']['run_id'] + '`。状态：`' + result['status'] + '`。\n\n'
               '此报告由 verify_run/read_run 独立重放，不改变原运行。能力域为 content/artifact/action；'
               'memory 仅作可见性诊断。格式、执行和 unknown 不冒充内容错误。\n\n'
               '有效判据使用等权计数；原正式加权评分完整保留在源运行。门槛为描述性验收，不是统计显著性或广泛排名。\n\n'
               '重算：`python scripts/analyze_difficulty.py --run <源运行目录> --output <本报告目录> --check`。'
               '退出 0 为通过，3 为门槛未通过但报告有效，2 为输入或复核错误。\n\n源文件 SHA256：\n\n' + hashes + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Independently recompute and compare saved summary without writing.')
    args = parser.parse_args(argv)
    try:
        if not args.check and args.output.exists():
            raise BenchError('Output already exists; choose a new directory (or use --check).')
        result = calculate(args.run)
        if args.check:
            if canonical(read_json(args.output / 'difficulty-summary.json')) != canonical(result):
                raise BenchError('Difficulty summary differs from independent replay.')
        else:
            publish(result, args.run, args.output)
        print(canonical({'status': result['status'], 'summary': result['summary'], 'checked': args.check}))
        return 0 if result['status'] == 'passed_gate' else 3
    except (BenchError, KeyError, TypeError, OSError, ValueError) as exc:
        print('Difficulty analysis error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
