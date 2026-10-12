#!/usr/bin/env python3
"""Generate descriptive dataset counts from frozen case definitions, no models."""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import DIMENSIONS, digest, write_json, write_text
from kylin_memory_bench.dataset import load_dataset


def summarize(path):
    cases = load_dataset(path)
    matrix = {d: Counter() for d in DIMENSIONS}
    rows = []
    for case in cases:
        steps = case['steps']
        for step in steps:
            matrix[case['dimension']].update(c['source'] for c in step.get('checks', []))
        rows.append({'id': case['id'], 'dimension': case['dimension'],
                     'step_count': len(steps), 'session_count': len({s['session'] for s in steps}),
                     'simulated_day_span': steps[-1]['day'] - steps[0]['day'],
                     'interference_step_count': sum(s['id'].startswith('noise') for s in steps),
                     'difficulty_pair': case.get('difficulty_pair'),
                     'difficulty_level': case.get('difficulty_level'),
                     'load_axis': case.get('difficulty_axis'), 'load_value': case.get('load_value')})
    return {'source': path.relative_to(ROOT).as_posix(), 'dataset_sha256': digest(cases),
            'case_count': len(cases), 'step_count': sum(r['step_count'] for r in rows),
            'check_count': sum(sum(c.values()) for c in matrix.values()),
            'dimension_source_counts': {d: dict(c) for d, c in matrix.items()}, 'cases': rows}


def main():
    suites = {name: summarize(ROOT / path) for name, path in (
        ('standard', 'examples/openkylin-core/dataset.jsonl'),
        ('challenge_original', 'examples/openkylin-challenge/dataset.jsonl'),
        ('difficulty', 'kylin_memory_bench/data/difficulty.jsonl'))}
    write_json(ROOT / 'docs/evidence/dataset-card.json', {'schema_version': '1.0', 'suites': suites})
    text = ['# 数据说明卡', '',
            '本卡由冻结题目定义生成，不调用模型。数量是单套题库的未加权判据数，不是三轮实验总数或评分宏平均。', '',
            '## 来源与任务性质', '',
            '- 标准集：六种任务模板，每维六个事实变体。36 个案例不等于 36 个独立任务家族。',
            '- 挑战集：12 个独立挑战案例。这里统计冻结原题；“松柏／松柏项目”别名订正另见 score-review.json，原始证据保留。',
            '- 难度集：六个家族的低／高负载配对，共 12 个实例。题目冻结不代表难度已验证；实际结论以独立试测分析为准。', '',
            '| 题库 | 案例 | 步骤 | 判据 |', '|---|---:|---:|---:|']
    labels = {'standard': '标准集', 'challenge_original': '挑战集原题', 'difficulty': '难度集'}
    for name, suite in suites.items():
        text.append('| {} | {} | {} | {} |'.format(labels[name], suite['case_count'], suite['step_count'], suite['check_count']))
    for name, suite in suites.items():
        text.extend(['', '## ' + labels[name] + '：能力 × 判据来源', '',
                     '| 能力 | 回答 | 记忆 | 工具行动 | 文件 |', '|---|---:|---:|---:|---:|'])
        for dimension, label in DIMENSIONS.items():
            counts = suite['dimension_source_counts'][dimension]
            text.append('| {} | {} | {} | {} | {} |'.format(label, *(counts.get(s, 0) for s in ('response', 'memory', 'actions', 'artifact'))))
        rows = suite['cases']
        text.extend(['', '每例步骤范围 {}–{}，不同会话数范围 {}–{}。逐例深度、干扰步骤和逻辑天数见 [机器可读数据卡](evidence/dataset-card.json)。'.format(
            min(r['step_count'] for r in rows), max(r['step_count'] for r in rows),
            min(r['session_count'] for r in rows), max(r['session_count'] for r in rows))])
    text.extend(['', '## 难度负载与测量边界', '',
                 '| 家族 | 级别 | 负载因素 | 负载 | 步骤 |', '|---|---|---|---:|---:|'])
    for row in suites['difficulty']['cases']:
        text.append('| {} | {} | {} | {} | {} |'.format(DIMENSIONS[row['dimension']], row['difficulty_level'], row['load_axis'], row['load_value'], row['step_count']))
    text.extend(['',
                 '所有题库均为合成资料。day 是明确写入提示的逻辑时间，不代表真实跨天老化或 TTL 测试。相近实体和候选事实也是干扰，不能仅凭 noise 步骤数比较所有家族难度。', '',
                 '难度分析使用 content、artifact、action 的预声明判据；格式不可解析、执行故障和证据不足保留在有效观测率分母中。记忆快照用于诊断，部分可见性不足以证明全局删除。', '',
                 '验收门槛为能力有效观测率至少 90%，至少三个家族平均下降 15 个百分点且三轮中两轮方向一致。这是描述性门槛，不是统计显著性。每族只有一对实例，三轮也不是新增独立题目；不能据此建立广泛排名。', '',
                 '评分契约校准样例由 AI 辅助构造，没有独立人审；校准通过不证明题目有足够区分度。', '',
                 '复算：`python3 scripts/build_dataset_card.py`。'])
    write_text(ROOT / 'docs/dataset-card.md', '\n'.join(text) + '\n')
    print('DATASET CARD: standard {}, challenge {}, difficulty {} cases.'.format(*(s['case_count'] for s in suites.values())))


if __name__ == '__main__':
    main()
