"""After full execution, independently replay and write a sanitized local report.

No model calls, no Git operations, no publication. Incomplete runs get a partial
status report, never a claim that the benchmark finished or video is approved.
"""
import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from kylin_memory_bench.common import read_json,write_json,write_text
from scripts.run_plan_full import report,ROOT


def export(root,destination):
    protocol=read_json(root/'protocol.json')
    for name,expected in protocol.get('source_sha256',{}).items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:
            raise ValueError('Frozen execution source changed; replay from archived source: '+name)
    progress=read_json(root/protocol.get('progress_file','progress.json'))
    analysis=report(root)  # independently replays every existing completed shard
    rows=[]
    for r in analysis['rows']:
        rows.append({k:r[k] for k in ('task_id','scenario_id','agent','condition','family','tier','split','phase')} | {
            'grade':{k:r['grade'][k] for k in ('status','observed','content_task_success','strict_task_success','format_status')},
            'action':{k:r['action'].get(k) for k in ('status','file_success','whole_task_success','tool_trace')},
            'planned_steps':r['planned_steps'],'observed_steps':r['observed_steps']})
    groups=[]
    for agent in ('openclaw','hermes'):
        for condition in ('memory','reader_only'):
            values=[r for r in rows if r['agent']==agent and r['condition']==condition]
            groups.append({'agent':agent,'condition':condition,'planned':len(values),
                'content_correct':sum(r['grade']['content_task_success'] for r in values),
                'strict_success':sum(r['grade']['strict_task_success'] for r in values),
                'whole_task_success':sum(r['action']['whole_task_success'] for r in values),
                'observed':sum(r['grade']['observed'] for r in values),
                'execution_errors':sum(r['phase']=='execution_error' for r in values),
                'incomplete':sum(r['phase']=='incomplete_evidence' for r in values)})
    attempted=successful=skipped=0
    for shard in (root/'shards').glob('*/evidence.jsonl'):
        for line in shard.read_text(encoding='utf-8').splitlines():
            event=json.loads(line)
            if str(event.get('error','')).startswith('Earlier step failed'):skipped+=1
            else:attempted+=1
            successful+=event.get('response') is not None
    complete=progress['status']=='complete' and len(analysis['verification'])==640
    exported={'model':protocol['model'],'histories':160,'repeats':1,'complete':complete,'groups':groups,
        'rows':rows,'attempted_event_slots':attempted,'response_observed_slots':successful,'skipped_event_slots':skipped,
        'protocol_sha256':hashlib.sha256((root/'protocol.json').read_bytes()).hexdigest(),
        'verified_shards':len(analysis['verification']),'analysis_sha256':hashlib.sha256((root/'analysis.json').read_bytes()).hexdigest(),
        'claim_limit':'One round; no stable ranking. Digest summary is not a public raw evidence bundle.'}
    write_json(destination/'evidence/luna-full-results.json',exported)
    lines=['# Luna 全量实验实际结果','',
        '**状态：'+('全计划已结束并逐案例复核。' if complete else '运行未完整结束，不得作为全量完成成绩。')+'**','',
        '160 条独立历史，两款 Agent 各一轮。memory 和原生单会话 reader_only 各 320 个案例，分开报告。',
        '阅读对照直接提供关键原始证据，保留文件工具；不是长期记忆成绩。','',
        '| Agent | 条件 | 内容正确／计划 | 完整任务成功／计划 | 有效观测／计划 | 执行错误 | 未完整执行 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for g in groups:
        n=g['planned'];lines.append(f"| {g['agent']} | {g['condition']} | {g['content_correct']}/{n} | {g['whole_task_success']}/{n} | {g['observed']}/{n} | {g['execution_errors']} | {g['incomplete']} |")
    lines+=['',f'实际记录到响应的步骤 {successful}；尝试槽位 {attempted}；故障后跳过槽位 {skipped}。这些不是独立历史数量。','',
        '[逐题脱敏结果](evidence/luna-full-results.json)保留全部计划分母。运行目录保存原始证据和单会话复核修订；没有重跑覆盖失败。',
        '', '原始证据保存在本机，公开摘要中的指纹不能代替完整可分发复核包。开发与公开预留分组见逐题结果，预留组不是盲测。',
        '', '## 视频与结论边界','',
        '本轮只支持单轮描述，不能称为稳定排名或统计显著差异，也不替代此前三轮难度验收门槛。',
        '录制时须标注 WSL2、Luna 和一轮实验；历史正式实验保持原数据来源。模型能读懂给齐证据的题，才有依据进一步讨论记忆链路。']
    if not complete:lines+=['','**尚不能据此定稿视频：当前仍有未完成或未复核的计划。**']
    elif any(g['observed']<.9*g['planned'] for g in groups):lines+=['','**有效观测不足 90%：应先分析执行／证据问题，暂停能力排名表述。**']
    else:lines+=['','本轮运行与复核材料可用于准备真实结果画面；最终成片仍需逐项核对阅读对照、失败归因、交付附件与原有验收要求。']
    write_text(destination/'luna-full-results.md','\n'.join(lines)+'\n')
    return exported


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--docs',type=Path,required=True)
    parser.add_argument('--once',action='store_true');args=parser.parse_args()
    while True:
        protocol=read_json(args.run/'protocol.json');path=args.run/protocol.get('progress_file','progress.json')
        if path.exists() and read_json(path)['status'] in ('complete','incomplete'):
            value=export(args.run,args.docs);print(json.dumps({'complete':value['complete'],'groups':value['groups']}),flush=True);return
        if args.once:return
        time.sleep(20)

if __name__=='__main__':main()
