#!/usr/bin/env python3
"""Replay fixed scoring-contract fixtures without models or network access.

The expected labels and metric values below are explicitly specified before
evaluation. Agreement is a contract check, not independent human accuracy or
evidence that benchmark tasks can rank arbitrary agents.
"""
import argparse
import csv
import hashlib
import html
import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import BenchError, DIMENSIONS, strict_json
from kylin_memory_bench.scoring import aggregate, evaluate, metric

DEFAULT_DATASET = ROOT / 'docs/evidence/scoring-calibration.jsonl'
COUNTS = {'response': 12, 'memory': 8, 'tool_file': 10}
NOTICE = ('这些按明确契约预先写定、由 AI 辅助编写的固定样例用于验证评分规则；未进行独立人工标注复核，'
          '一致结果不等于独立人审准确率，不证明题目难度、真实智能体能力排名或全局删除。'
          '文件和工具样例是预先构造的证据记录，不是新增真实智能体实验。')
FILENAMES = ('results.json', 'results.csv', 'report.html')


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':'))


def load_fixtures(path):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = strict_json(line)
        if not isinstance(row, dict) or row.get('schema_version') != '1.0':
            raise ValueError('Invalid fixture schema at line ' + str(number))
        required = ('id', 'group', 'title', 'check', 'event', 'expected', 'rationale', 'provenance')
        if any(key not in row for key in required):
            raise ValueError('Incomplete fixture at line ' + str(number))
        if row['group'] not in COUNTS or not isinstance(row['check'], dict):
            raise ValueError('Invalid fixture group/check at line ' + str(number))
        if not all(isinstance(row[key], str) and row[key] for key in ('id', 'title', 'rationale')):
            raise ValueError('Fixture id/title/rationale must be nonempty text')
        expected = row['expected']
        if not isinstance(expected, dict) or set(expected) != {'status', 'category'}:
            raise ValueError('Expected label must explicitly supply status and category')
        if expected['status'] not in ('pass', 'fail', 'unknown', 'error'):
            raise ValueError('Invalid expected status')
        if not isinstance(expected['category'], str) or not expected['category']:
            raise ValueError('Invalid expected category')
        if row['provenance'] != 'synthetic_contract_fixture':
            raise ValueError('Fixture provenance must identify constructed contract evidence')
        source = row['check'].get('source')
        allowed = {'response': {'response'}, 'memory': {'memory'}, 'tool_file': {'actions', 'artifact'}}
        if source not in allowed[row['group']]:
            raise ValueError('Fixture group does not match evidence source')
        rows.append(row)
    if dict(Counter(row['group'] for row in rows)) != COUNTS:
        raise ValueError('Expected exactly 30 fixtures: response=12, memory=8, tool_file=10')
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Fixture ids must be unique')
    return rows


def aggregate_fixtures():
    """Prespecified arithmetic gold values; never derived from scorer output."""
    return [
        {'id': 'metrics-complete', 'title': '全部可观测的两通过一失败',
         'checks': [{'status': 'pass', 'weight': 1}, {'status': 'fail', 'weight': 1},
                    {'status': 'pass', 'weight': 1}],
         'expected': {'score': 0.666667, 'coverage': 1.0, 'lower_bound': 0.666667,
                      'upper_bound': 0.666667, 'check_count': 3, 'statuses': {'pass': 2, 'fail': 1}},
         'rationale': '通过权重2/总权重3；证据全部可观测，上下界与已观测分相同。'},
        {'id': 'metrics-unknown-error', 'title': '未知与执行错误保留在总分母',
         'checks': [{'status': 'pass', 'weight': 1}, {'status': 'fail', 'weight': 1},
                    {'status': 'unknown', 'weight': 1}, {'status': 'error', 'weight': 1}],
         'expected': {'score': 0.5, 'coverage': 0.5, 'lower_bound': 0.25,
                      'upper_bound': 0.75, 'check_count': 4,
                      'statuses': {'pass': 1, 'fail': 1, 'unknown': 1, 'error': 1}},
         'rationale': '可观测通过1/可观测2；覆盖2/4，下界1/4，上界(1+2)/4。'},
        {'id': 'metrics-weighted', 'title': '不同检查权重参与覆盖率和边界',
         'checks': [{'status': 'pass', 'weight': 1}, {'status': 'fail', 'weight': 3},
                    {'status': 'unknown', 'weight': 2}, {'status': 'error', 'weight': 4}],
         'expected': {'score': 0.25, 'coverage': 0.4, 'lower_bound': 0.1,
                      'upper_bound': 0.7, 'check_count': 4,
                      'statuses': {'pass': 1, 'fail': 1, 'unknown': 1, 'error': 1}},
         'rationale': '总权重10，可观测权重4；通过1，未知/错误权重6。'},
        {'id': 'metrics-case-dimension-macro', 'title': '先案例等权，再六维等权',
         'dimensions': [
             {'dimension': 'retention', 'cases': [
                 [{'status': 'pass', 'weight': 1}, {'status': 'fail', 'weight': 1}],
                 [{'status': 'pass', 'weight': 1}, {'status': 'pass', 'weight': 1},
                  {'status': 'pass', 'weight': 1}]]},
             *[{'dimension': dimension, 'cases': [[{'status': 'fail', 'weight': 1}]]}
               for dimension in ('retrieval', 'update', 'disambiguation', 'boundary', 'reuse')]],
         'expected': {'score': 0.125, 'coverage': 1.0, 'lower_bound': 0.125, 'upper_bound': 0.125},
         'rationale': '保持维度=(1/2+1)/2=3/4；其他五维为0；六维均值=1/8。不能用总检查项通过4/10替代。'}]


def calculate(path=DEFAULT_DATASET):
    path = Path(path)
    rows = load_fixtures(path)
    results = []
    for row in rows:
        actual = evaluate(row['check'], row['event'])
        actual_label = {key: actual[key] for key in ('status', 'category')}
        results.append({'id': row['id'], 'group': row['group'], 'title': row['title'],
                        'check': row['check'], 'event': row['event'],
                        'expected': row['expected'], 'actual': actual_label,
                        'scorer_reason': actual['reason'], 'rationale': row['rationale'],
                        'matched': actual_label == row['expected'], 'provenance': row['provenance']})
    aggregate_results = []
    for fixture in aggregate_fixtures():
        if 'checks' in fixture:
            actual = metric(fixture['checks'])
        else:
            dimensions = fixture['dimensions']
            if {row['dimension'] for row in dimensions} != set(DIMENSIONS):
                raise ValueError('Macro fixture must include all six dimensions')
            actual = aggregate([aggregate([metric(checks) for checks in row['cases']])
                                for row in dimensions])
        aggregate_results.append({**fixture, 'actual': actual, 'matched': actual == fixture['expected']})
    summary = {'fixtures': len(results), 'matched': sum(row['matched'] for row in results),
               'aggregate_groups': len(aggregate_results),
               'aggregate_matched': sum(row['matched'] for row in aggregate_results),
               'false_passes': sum(row['actual']['status'] == 'pass' and
                                   row['expected']['status'] != 'pass' for row in results),
               'groups': dict(Counter(row['group'] for row in results)),
               'expected_statuses': dict(Counter(row['expected']['status'] for row in results)),
               'actual_statuses': dict(Counter(row['actual']['status'] for row in results))}
    return {'schema_version': '1.0', 'kind': 'fixed_scoring_contract_calibration',
            'dataset_sha256': hashlib.sha256(compact(rows).encode('utf-8')).hexdigest(),
            'dataset_hash_basis': 'canonical JSON rows; UTF-8; sorted object keys',
            'scorer_sha256': hashlib.sha256((ROOT / 'kylin_memory_bench/scoring.py').read_text(
                encoding='utf-8').encode('utf-8')).hexdigest(),
            'scorer_hash_basis': 'UTF-8 source text with normalized newlines',
            'label_policy': 'prespecified_contract_labels; authored_with_AI_assistance; no independent human review',
            'notice': NOTICE, 'summary': summary, 'fixtures': results,
            'aggregate_checks': aggregate_results,
            'passed': summary['matched'] == 30 and summary['aggregate_matched'] == 4}


def csv_text(report):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(['kind', 'id', 'group', 'title', 'expected', 'actual', 'matched', 'rationale'])
    for row in report['fixtures']:
        writer.writerow(['fixture', row['id'], row['group'], row['title'], compact(row['expected']),
                         compact(row['actual']), str(row['matched']).lower(), row['rationale']])
    for row in report['aggregate_checks']:
        writer.writerow(['aggregate', row['id'], 'metrics', row['title'], compact(row['expected']),
                         compact(row['actual']), str(row['matched']).lower(), row['rationale']])
    return output.getvalue()


def html_text(report):
    def esc(value):
        return html.escape(str(value), quote=True)
    def evidence_row(row):
        return ('<tr class="' + ('match' if row['matched'] else 'mismatch') + '"><td>' +
                esc(row['id']) + '</td><td>' + esc(row['title']) + '</td><td><code>' +
                esc(compact(row['expected'])) + '</code></td><td><code>' + esc(compact(row['actual'])) +
                '</code></td><td>' + ('一致' if row['matched'] else '不一致') + '</td><td>' +
                esc(row['rationale']) + '</td></tr>')
    s = report['summary']
    tables = []
    titles = {'response': '响应契约（12 项）', 'memory': '记忆可见性（8 项）',
              'tool_file': '工具与文件（10 项）'}
    for group in COUNTS:
        tables.append('<h2>' + titles[group] + '</h2><table><thead><tr><th>编号</th><th>场景</th>'
                      '<th>预设标签</th><th>实际判定</th><th>对照</th><th>预设理由</th></tr></thead><tbody>' +
                      ''.join(evidence_row(row) for row in report['fixtures'] if row['group'] == group) +
                      '</tbody></table>')
    tables.append('<h2>聚合指标（4 组）</h2><table><thead><tr><th>编号</th><th>场景</th>'
                  '<th>预设指标</th><th>实际指标</th><th>对照</th><th>计算理由</th></tr></thead><tbody>' +
                  ''.join(evidence_row(row) for row in report['aggregate_checks']) + '</tbody></table>')
    details = ''.join('<details><summary>' + esc(row['id'] + '：' + row['title']) + '</summary><pre>' +
                      esc(json.dumps({'check': row['check'], 'event': row['event'],
                                      'scorer_reason': row['scorer_reason']}, ensure_ascii=False, indent=2)) +
                      '</pre></details>' for row in report['fixtures'])
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>评分契约校准</title><style>'
            'body{max-width:1500px;margin:32px auto;padding:0 24px;color:#182331;background:#f5f7fa;'
            'font:16px/1.65 system-ui,sans-serif}h1,h2{color:#153d64}table{width:100%;border-collapse:collapse;'
            'background:white;font-size:14px}th,td{padding:9px;border:1px solid #cbd6e1;text-align:left;'
            'vertical-align:top;overflow-wrap:anywhere}th{background:#e9eef5}.mismatch{background:#fff0eb}'
            'code,pre{font:13px/1.6 monospace;white-space:pre-wrap;overflow-wrap:anywhere}'
            '.notice{background:#fff2d2;padding:16px;border-left:5px solid #986d15}'
            '.summary{background:#e7f4ee;padding:16px}details{background:white;padding:12px;margin:8px 0}'
            '</style><body><h1>评分契约校准</h1><p class="notice">' + esc(NOTICE) +
            '</p><p class="summary">固定样例：' + str(s['matched']) + '/30 一致；聚合指标：' +
            str(s['aggregate_matched']) + '/4 一致；非通过被误判为通过：' + str(s['false_passes']) +
            '。验收：' + ('通过' if report['passed'] else '未通过') + '</p><p>标签先按明确契约写定，再调用现有评分器；'
            '没有模型调用。输入指纹：<code>' + esc(report['dataset_sha256']) + '</code></p>' +
            ''.join(tables) + '<h2>构造证据与判分原因</h2>' + details +
            '<p>复核：<code>python3 scripts/calibrate_scoring.py --check &lt;结果目录&gt;</code>。'
            '独立重算后同时检查 JSON、CSV 与 HTML；不会覆盖已有材料。</p></body></html>\n')


def artifacts(report):
    return {'results.json': json.dumps(report, ensure_ascii=False, indent=2,
                                       sort_keys=True, allow_nan=False) + '\n',
            'results.csv': csv_text(report), 'report.html': html_text(report)}


def write_results(output, report):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, text in artifacts(report).items():
        with (output / name).open('w', encoding='utf-8', newline='') as handle:
            handle.write(text)


def check_results(output, report):
    output = Path(output)
    for name, expected in artifacts(report).items():
        path = output / name
        if not path.is_file() or path.read_bytes() != expected.encode('utf-8'):
            raise ValueError('Calibration result differs from independent recomputation: ' + name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path, help='Create a new result directory; never overwrite evidence')
    action.add_argument('--check', type=Path, metavar='RESULT_DIRECTORY',
                        help='Read-only independent recomputation of all saved result formats')
    args = parser.parse_args(argv)
    try:
        report = calculate(args.dataset)
        if args.check is not None:
            check_results(args.check, report)
        else:
            write_results(args.output, report)
        summary = report['summary']
        print(('CALIBRATION PASS' if report['passed'] else 'CALIBRATION MISMATCH') +
              ': {}/30 fixtures, {}/4 metric groups, {} false passes; no model calls.'.format(
                  summary['matched'], summary['aggregate_matched'], summary['false_passes']))
        return 0 if report['passed'] else 1
    except (BenchError, ValueError, KeyError, TypeError, OSError) as exc:
        print('Calibration error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
