#!/usr/bin/env python3
"""Publish local, redacted evidence and the actual V3 memory-pilot report."""
import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.math_memory.record_pilot import analyze
from kylin_memory_bench.runner import read_run, verify_run
from experiments.math_memory.memory_only import grade


def content_diagnostic(case,expected,row):
    """Post-run envelope diagnostic only; never changes frozen primary scoring."""
    result={'agent':row['agent'],'case':row['case'],'condition':row['condition'],
            'event_id':row['event_id'],'primary_unchanged':True,'post_run_diagnostic':True,
            'eligible_for_predeclared_gate':False,'extraction':None,'grade':None}
    if row['execution_error'] or not isinstance(row['response_text'],str):return result
    if not row['format_error']:
        result.update(extraction='already_conforming_response',grade=grade(case,expected,row['response_text']))
        return result
    # One explicitly delimited JSON answer is inspectable; multiple alternatives stay ambiguous.
    blocks=re.findall(r'```(?:json)?\s*\n(.*?)\n```',row['response_text'],re.DOTALL)
    if len(blocks)==1:
        checked=grade(case,expected,blocks[0])
        if checked['format']=='json':result.update(extraction='single_json_block_with_extra_prose',grade=checked)
    return result


def retrieval_diagnostic(case,events,workspace=None):
    """Audit explicit record reads and stored files without inferring a score."""
    selected=[e for e in events if e['agent_id']=='openclaw' and e['case_id']==case['id']]
    final=next(e for e in selected if e['step_id']=='final')
    history={}
    for session in case['sessions'][:-1]:
        for line in session['prompt'].splitlines():
            if line.startswith('RECORD='):
                record=json.loads(line[7:])
                history[record['id']]=record
    seen=set();reads=[]
    for action in (final.get('response') or {}).get('actions',[]):
        if action['name']!='read_file':continue
        ids=set()
        for block in action.get('result',[]):
            if not isinstance(block,dict):continue
            for line in block.get('text','').splitlines():
                if line.startswith('RECORD='):
                    try:ids.add(json.loads(line[7:])['id'])
                    except (json.JSONDecodeError,KeyError,TypeError):pass
        seen.update(ids)
        reads.append({'path':action.get('arguments',{}).get('path'),
                      'literal_record_count':len(ids),'record_ids':sorted(ids)})
    missing=[]
    for record_id in sorted(history.keys()-seen):
        row={'record_id':record_id,'project':history[record_id]['project'],
             'kind':history[record_id]['kind'],'writes':[]}
        for event in selected:
            if event['step_id']=='final':continue
            for action in (event.get('response') or {}).get('actions',[]):
                args=action.get('arguments',{});content=args.get('content')
                if action['name']!='write_file' or not isinstance(content,str) or record_id not in content:continue
                path=Path(args.get('path',''))
                write={'event_id':event['event_id'],'path':str(path),
                       'written_content_sha256':hashlib.sha256(content.encode()).hexdigest(),
                       'current_file_exists':None,'current_file_matches_write':None}
                if workspace is not None and not path.is_absolute() and '..' not in path.parts:
                    current=workspace/path
                    write['current_file_exists']=current.is_file()
                    if current.is_file():
                        write['current_file_sha256']=hashlib.sha256(current.read_bytes()).hexdigest()
                        write['current_file_matches_write']=write['current_file_sha256']==write['written_content_sha256']
                row['writes'].append(write)
        missing.append(row)
    text=(final.get('response') or {}).get('text','')
    return {'status':'post_run_retrieval_diagnostic_not_primary_score','agent':'openclaw',
            'case':case['id'],'final_event_id':final['event_id'],
            'primary_unchanged':True,'eligible_for_predeclared_gate':False,
            'historical_record_count':len(history),'explicitly_read_record_count':len(history.keys()&seen),
            'final_reads':reads,'not_in_explicit_final_reads':missing,
            'stored_files_inspected':workspace is not None,
            'native_output_limit_marker':'Reply truncated at the model\'s output token limit' in text,
            'claim_limit':'Explicit tool reads and persisted files only. Does not prove absence from automatic context, deletion, internal forgetting or a field-level memory score.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--transport-revision',action='store_true')
    p.add_argument('--refresh-report',action='store_true',help='Refresh presentation and post-run diagnostics; preserve primary scores and exports.')
    p.add_argument('--memory-workspace',type=Path,help='Read-only inspection of the OpenClaw memory-case workspace; never export the workspace.')
    args=p.parse_args()
    evidence=ROOT/'docs/evidence/research-memory-v3'
    frozen_dir=ROOT/('experiments/math_memory/pilot-v3-transport' if args.transport_revision else
                    'experiments/math_memory/pilot-v3')
    if args.refresh_report:
        verify_run(args.run)
    else:
        analyze(frozen_dir,args.run,evidence)
    export=ROOT/'examples/openkylin-research-memory-v3'
    stem='research-v3-transport' if args.transport_revision else 'research-v3-native'
    audit=ROOT/('runs/'+stem+'/api-audit.jsonl')
    if not args.refresh_report:
        subprocess.run([sys.executable,str(ROOT/'scripts/export_run.py'),str(args.run),str(export),
                        '--audit',str(audit)],cwd=ROOT,check=True,capture_output=True)
    manifest,dataset,events,raw_scores=read_run(args.run)
    result=json.loads((evidence/'results.json').read_text())
    if result['run_id']!=manifest['run_id']:
        raise ValueError('Existing primary result belongs to a different run')
    freeze_name='research-v3-transport-execution-freeze.json' if args.transport_revision else 'research-v3-execution-freeze.json'
    frozen=json.loads((ROOT/'docs/evidence'/freeze_name).read_text())
    original_frozen=json.loads((ROOT/'docs/evidence/research-v3-execution-freeze.json').read_text())
    ledger=json.loads((ROOT/'runs/deepseek-budget.local.json').read_text())
    logs=[json.loads(line) for line in audit.read_text().splitlines() if line]
    if args.transport_revision:
        logs=[json.loads(line) for line in (ROOT/'runs/research-v3-native/api-audit.jsonl').read_text().splitlines() if line]+logs
    starts=[r for r in logs if r['event']=='start']
    finishes=[r for r in logs if r['event']=='finished']
    estimate=Decimal(ledger['estimated_upper_cny'])-Decimal(original_frozen['cumulative_estimate_start_cny'])
    fresh=bool(finishes and finishes[-1].get('balance_fresh'))
    decrease=(Decimal(starts[0]['balance_cny'])-Decimal(finishes[-1]['balance_cny'])) if starts and fresh else None
    budget={'additional_authorized_limit_cny':original_frozen['incremental_authorized_limit_cny'],
            'incremental_conservative_ledger_estimate_cny':str(estimate),
            'observed_account_balance_decrease_cny':str(decrease) if decrease is not None else None,
            'final_balance_fresh':fresh,'video_reserved_limit_cny':'1',
            'cumulative_ledger_preserved':True,'completed_requests':sum(r['event']=='completion' for r in logs),
            'budget_stop_count':sum(r['event']=='budget_stop' for r in logs),
            'includes_interrupted_first_attempt':args.transport_revision,
            'note':'Peak-rate token estimate and account-interval decrease are separate; neither is an individually reconciled invoice. In-flight failures may retain conservative reserves. Original balances omitted.'}
    (ROOT/'docs/evidence/research-v3-budget-summary.json').write_text(json.dumps(budget,ensure_ascii=False,indent=2)+'\n')
    network=[]
    for row in logs:
        if row['event']!='rejected':continue
        reason=row.get('reason','').lower()
        category=('budget_guard' if 'budget' in reason else 'upstream_timeout' if 'timed out' in reason or 'timeout' in reason
                  else 'request_limit' if 'request limit' in reason else 'other_proxy_or_provider_error')
        network.append({'at':row['at'],'category':category})
    (ROOT/'docs/evidence/research-v3-network-summary.json').write_text(json.dumps(
        {'counts':dict(collections.Counter(r['category'] for r in network)),'events':network,
         'note':'Safe categories only; arbitrary error text and account fields are excluded.'},ensure_ascii=False,indent=2)+'\n')
    tools=[]
    for row in result['rows']:
        matching=[e for e in events if e['agent_id']==row['agent'] and e['case_id']==row['case']]
        tools.append({'agent':row['agent'],'condition':row['condition'],
            'historical_tools':dict(collections.Counter(a['name'] for e in matching if e['step_id']!='final'
                                   for a in (e.get('response') or {}).get('actions') or [])),
            'final_tools':dict(collections.Counter(a['name'] for e in matching if e['step_id']=='final'
                              for a in (e.get('response') or {}).get('actions') or []))})
    (evidence/'tool-summary.json').write_text(json.dumps(tools,ensure_ascii=False,indent=2)+'\n')
    rows=result['rows'];memory=[r for r in rows if r['condition']=='memory']
    cases={c['id']:c for c in json.loads((frozen_dir/'learner-cases.json').read_text())}
    gold=json.loads((frozen_dir/'gold.json').read_text())
    envelope=[content_diagnostic(cases[r['case']],gold[r['case']],r) for r in rows]
    (evidence/'content-envelope-diagnostics.json').write_text(json.dumps(
        {'status':'post_run_diagnostic_not_primary_score','policy':'Uniform inspection of one explicit JSON block; multiple blocks are not selected. Original raw response and frozen score are unchanged.',
         'claim_limit':'Explains content versus surrounding-format loss only; not eligible for predeclared gates or system ranking.',
         'diagnostic_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         'rows':envelope},ensure_ascii=False,indent=2)+'\n')
    retrieval=retrieval_diagnostic(cases['research-v3-combined-high-memory'],events,args.memory_workspace)
    retrieval.update(run_id=manifest['run_id'],
                     diagnostic_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     evidence_file_sha256=hashlib.sha256((args.run/'evidence.jsonl').read_bytes()).hexdigest())
    (evidence/'retrieval-diagnostics.json').write_text(json.dumps(retrieval,ensure_ascii=False,indent=2)+'\n')
    books=[r for r in rows if r['condition']=='open_book']
    books_pass=all(r['correct_over_all']>=0.95 for r in books)
    content_books_pass=all(r['grade'] and r['grade']['correct_count']==18
                           for r in envelope if r['condition']=='open_book')
    coverage=sum(r['observed_count'] for r in memory)/36
    if not books_pass and content_books_pass:
        verdict='两款系统在补充内容核查中均能恢复完整记录的18项答案，但冻结主契约因外围格式未通过；历史记忆组又受输出截断和执行故障阻断，尚不能证明充分难度或稳定记忆差异。'
    elif not books_pass:
        verdict='完整记录对照未通过冻结契约，历史组主要失分尚不能归因于记忆；需要分别核查记录理解、输出和执行问题。'
    elif coverage<0.9:
        verdict='完整记录对照可完成，但历史组有效观测不足90%，尚不能把主要差异解释为记忆差异。'
    elif all(r['correct_count']==18 for r in memory):
        verdict='完整记录和历史记忆组均通过；本轮未观察到该实例能区分两款系统，尚不能宣称难度足够。'
    else:
        verdict='完整记录对照可完成，历史记忆组出现可定位的记录恢复错误。它支持继续复测，但单轮不能证明难度充分、稳定差异或系统排名。'
    labels={'memory':'历史记忆','open_book':'最终重给完整记录','no_history':'目标资料从未提供'}
    table='\n'.join('| '+r['agent']+' | '+labels[r['condition']]+' | '+str(r['correct_count'])+'/18 | '+str(r['observed_count'])+'/18 | '+
                    ('执行错误' if r['execution_error'] else r['format'] or '无法解析')+' | [#'+str(r['event_id'])+
                    '](../examples/openkylin-research-memory-v3/evidence.html#event-'+str(r['event_id'])+') |' for r in rows)
    diagnostics=[]
    for r in rows:
        if r['execution_error']:
            diagnostics.append('- '+r['agent']+'／'+labels[r['condition']]+'：执行错误，18项保留为错误／未知，不计为已观测的记忆失败。')
        elif r['format_error']:
            diagnostics.append('- '+r['agent']+'／'+labels[r['condition']]+'：响应无法按冻结格式解析；不能把格式问题全部算作遗忘。')
        elif r['correct_count']<18:
            failed=[c for c in r['checks'] if c['status']!='pass']
            content='；'.join(c['qid']+'：登记值 '+json.dumps(c['expected'],ensure_ascii=False)+'，回答 '+json.dumps(c['actual'],ensure_ascii=False)+'（'+c['status']+'）' for c in failed)
            diagnostics.append('- '+r['agent']+'／'+labels[r['condition']]+'：'+content+'。')
    if not diagnostics:diagnostics=['- 六个最终响应均正确。通过只证明这次实例可完成，不能替代三轮低、高负载验证。']
    raw_fails=manifest['execution_errors']
    final_fails=sum(bool(r['execution_error']) for r in rows)
    missing=sum(r['event_id'] is None for r in rows)
    envelope_table='\n'.join('| '+r['agent']+' | '+labels[r['condition']]+' | '+
        (str(r['grade']['correct_count'])+'/18' if r['grade'] else '不可判')+' | '+
        (str(r['grade']['observed_count'])+'/18' if r['grade'] else '0/18')+' | '+str(r['extraction'] or '执行／格式未知')+' |' for r in envelope)
    storage_checked=bool(retrieval['not_in_explicit_final_reads']) and all(
        any(w['current_file_matches_write'] is True for w in r['writes'])
        for r in retrieval['not_in_explicit_final_reads'])
    storage_note=('试测结束后只读核对确认这五个文件仍存在，内容散列与当时写入一致。'
                  if storage_checked else '本次报告生成未核对这些独立文件的结束状态，不能从未读记录推断文件丢失。')
    revision_note=''
    if args.transport_revision:
        first=json.loads((ROOT/'docs/evidence/research-v3-interrupted-accounting.json').read_text())
        revision_note=f'''## 首次尝试与统一底座修订

首次尝试记录{first['events']}条事件后停止，原生首次执行错误{first['original_execution_errors']}次；六个最终槽位的108项均未得到有效能力观测。三个Hermes最终槽位为执行错误，三个OpenClaw最终槽位未执行，全部保持错误／未知。源数据、原始评分、冻结指纹和原转发程序完整保存，没有用修订版覆盖失败。

转发程序原先将包括上游超时在内的异常统一返回HTTP 400，并串行处理全部调用。该错误状态可能让智能体把传输故障当作不可重试的参数问题；排队也会影响客户端连接。本版统一保留上游HTTP状态，超时返回504，并支持并行调用；费用预留、结算与账本写入均同步，避免并行调用重复使用额度。失败且缺usage的请求仍保留保守预留。原生内部传输恢复继续按各自原生实现运行；每次请求和故障均审计、计费，评测器不自动重跑失败案例。

两个版本的题目、答案、会话顺序和主评分字节相同，只更换独立工作区与统一转发实现。修订前后不是两轮稳定性实验，不能当作能力进步或一次完整三轮验收。两次尝试共用新增10元上限。

- [首次尝试完整证据](../examples/openkylin-research-memory-v3-interrupted/evidence.html)、[六槽位说明](evidence/research-v3-interrupted-accounting.json)。
- [转发修订验收](evidence/research-v3-transport-validation.json)、[修订执行冻结](evidence/research-v3-transport-execution-freeze.json)。

'''
    md=f'''# 数学研究档案记忆 V3：真实付费小试测

本轮只测试重新设计的数学研究档案实例。原生OpenClaw与Hermes在openKylin上使用同一DeepSeek Flash，各一轮、各三个资料条件，均使用独立工作区。最终只恢复登记事实，不计算展开系数、判断数学真伪或交付证书。

**当前结论：{verdict}** 原有难度验收未通过的结论仍保留，本轮不是正式三轮验收或提交就绪证明。

{revision_note}
## 冻结的任务与控制

综合高负载包含78次历史会话，交错15个研究项目，最后查询其中三个项目的18项短值。查询当前D1与分支、指定引理版本与登记bound、C0时的D1、行政修订标签，以及禁止复用和未提供资料的边界。每个非空答案都有原文记录出处。

历史组与完整记录组在此前会话中接收完全相同的记录，工作区独立；完整记录组最后重给原始历史，不提供整理好的答案。资料缺失组删除三个被查询项目的所有记录，保留46次干扰会话，18项均应返回null。这组单独评价拒绝编造。

预先选定三个条件，没有按结果筛题、自动重试或替换失败。六个案例任务并发，但各案例内部会话顺序固定。temperature=0、thinking关闭、输出上限2048，Hermes内部max_turns=6；两者保留各自原生文件和记忆工具，原生配置差异在导出的config.json中披露。

## 实际结果

| 系统 | 资料条件 | 正确项 | 有效观测 | 格式／状态 | 最终证据 |
|---|---|---:|---:|---|---|
{table}

历史记忆组有效观测率为{coverage:.2%}。全部最终槽位的分母保持108项；执行、格式和缺字段不缩小分母。当前直接事实、关联引用、旧检查点和边界逐项状态见结果JSON。完整记录门槛95%在18项实例中实际上要求18/18；它只检查任务可读与可答，不证明内部记忆机制。

全部历史与最终事件共{len(events)}条，记录的执行错误共{raw_fails}条，其中最终执行错误{final_fails}个，缺失最终事件{missing}个。某个历史步骤失败后，现有运行器会把该案例后续步骤记为跳过；这些连带项不能称为多次独立能力失败。

## 错误解释

{chr(10).join(diagnostics)}

JSON严格相等的原始评分完整保留。本版主评分另行接受预先冻结的行式答案、合法别名和精确等价分数；原始评分不能覆盖主评分，也不把两套结果混成一个分数。未提供/被禁止复用的null、错误null、格式未知和执行错误分别呈现。

### 内容与外围格式的补充核查

以下是运行后新增的诊断，不改冻结主分数、不改变108项分母、不纳入预先声明的门槛或排名。对所有最终响应采用同一规则：原本合规的答案直接核查；若仅有一个明确JSON代码块但前后附带解释，则单独核查该块的18项值；多块候选不挑选，执行错误保持不可判。它解释原文可读取的内容，不把被主契约拒绝的答案事后改判为通过。

| 系统 | 资料条件 | 可读内容正确项 | 可读内容观测项 | 取值位置 |
|---|---|---:|---:|---|
{envelope_table}

[补充诊断与逐项状态](evidence/research-memory-v3/content-envelope-diagnostics.json)保留抽取方式及主分数不变的标记。主契约的格式未知不等于这些原文值在内容上错误；这项补充亦不能替代事前评分契约校准或真实三轮验证。

### 历史记录实际保存与检索

OpenClaw历史组的最终事件[#410](../examples/openkylin-research-memory-v3/evidence.html#event-410)显式读取了`MEMORY.md`，其中有{retrieval['explicitly_read_record_count']}/{retrieval['historical_record_count']}份原文记录。缺在这次读取中的五份是三个项目的C0初始记录，以及前两个项目最初采用的引理记录。它们此前分别写入四个`.openclaw/tmp/*.json`文件和一个`memory/*.md`文件。{storage_note}

因此，证据支持“资料分散保存，最终显式检索不完整”，不能称为资料被删除或全部忘掉。最终文本误把归档项目的引用当作原项目的候选来源，同时报告缺少原项目引用；回答在整理途中被原生CLI标注输出上限截断，没有18项完整答案。不能给这段未完成的推敲补算正式记忆分数。[检索诊断](evidence/research-memory-v3/retrieval-diagnostics.json)保留写入事件、相对路径和散列，不公开工作区；显式工具轨迹也不能排除系统自动注入其他资料。

原文还暴露一个题面歧义：最后的`hint_permission`补丁没有`revision`，模型质疑此时是否应返回`null`。冻结答案仍为最后明确登记的`v6`，本轮不修改答案或分母；下版需要明确“未提供revision的补丁保留已有标签”。这属于记录契约需要澄清的问题，不能把该项争议直接解释成遗忘。

继续付费前，应先把唯一明确答案块的内容评分、外围格式评分、最终输出额度和上述标签规则一起冻结并离线校准，并完成执行可靠性验收。本轮没有追加第三次付费尝试，也不依据这次失败临时制造数学难题。

## 验收与证据范围

首次付费前全项目114项测试、openKylin专项14项测试通过；转发修订后全项目118项、openKylin专项28项测试通过。两款原生CLI各通过两次独立会话的本地模拟API启动检查。目录/PID隔离核查确认仓库、评分端、其他案例和旧临时目录不可读，当前工作区可读写；未暴露全局Hermes配置。原生进程只见自己的工作区与安装运行时，且关闭提权、丢弃能力。离线启动检查不证明真实记忆表现。

运行后新增的内容与检索诊断另有专项测试，确认补充诊断不改主评分、多候选不挑答案，以及未读但仍保存的资料不能称为丢失。专项测试记录见[诊断验收](evidence/research-v3-diagnostic-validation.json)。

原生工具轨迹、逐步记忆快照与最终读写另外保留。快照complete=false表示只采集配置范围内的部分状态；没有文件/工具轨迹不能凭空认定某个内部过程。隔离实现会改变可见文件系统，故结果只适用于披露的运行条件。数学登记是合成研究材料，登记常数与审阅结论不声称构成真实定理。

本轮仅一个高负载实例、一个种子、一轮；没有低负载对照、重复波动或跨题族难度测量。不能据此宣布至少三个家族的难度效应，也不能直接形成能力排名或视频最终结论。

## 费用与复核

本次新增保护上限{budget['additional_authorized_limit_cny']}元，保留累计账本。增量保守记账估算为{budget['incremental_conservative_ledger_estimate_cny']}元；账户区间余额减少{budget['observed_account_balance_decrease_cny'] or '未知'}元。这两者均不等于逐笔核对的独立账单，原始余额与凭据未公开。视频预留1元未用于本次试测。

保护器沿用每百万tokens输入未命中2元、命中0.04元、输出8元的高峰上界；本次已核对[DeepSeek官方价格页](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)，即使处于空闲时段也保留该保守上界。上游失败的在途预留可能缺少usage，不通过清零或重跑消除它。

- [离线设计与具体示例](../experiments/math_memory/memory-v3-design.md)、[交互展示页](../experiments/math_memory/memory-v3/index.html)。
- [本轮结果页](evidence/research-memory-v3/index.html)、[逐项主评分与答案](evidence/research-memory-v3/results.json)、[工具摘要](evidence/research-memory-v3/tool-summary.json)。
- [原始证据检查器](../examples/openkylin-research-memory-v3/evidence.html)、[保留的原始严格评分](../examples/openkylin-research-memory-v3/scores.json)。
- [任务与判据冻结](../experiments/math_memory/pilot-v3-transport/protocol.json)、[原始执行与费用冻结](evidence/research-v3-execution-freeze.json)、[离线验收](evidence/research-v3-validation.json)。
- [脱敏费用记录](evidence/research-v3-budget-summary.json)、[代理/上游故障分类](evidence/research-v3-network-summary.json)。

旧V1/V2数学测试、原0.2.0正式实验及既有订正保持原样。V3以独立版本和报告呈现，不能改写旧结果。
'''
    (ROOT/'docs/research-memory-v3-report.md').write_text(md,encoding='utf-8')
    page=(evidence/'index.html').read_text()
    note='<p id="diagnostic-note">主评分0项有效观测表示格式／执行阻断，不等于记忆能力为零。<a href="content-envelope-diagnostics.json">补充内容核查</a>中两款完整记录对照均18/18；<a href="retrieval-diagnostics.json">检索诊断</a>与<a href="../../research-memory-v3-report.md">完整报告</a>另列。</p>'
    page=re.sub(r'<p id="diagnostic-note">.*?</p>','',page,flags=re.DOTALL)
    (evidence/'index.html').write_text(page.replace('<table>',note+'<table>',1),encoding='utf-8')
    print(json.dumps({'report':'docs/research-memory-v3-report.md','verdict':verdict,
                      'final_slots':len(rows),'events':len(events),'budget':budget},ensure_ascii=False))


if __name__=='__main__':main()
