#!/usr/bin/env python3
"""Generate the factual results note from independently verified exported runs."""
import collections,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench.common import DIMENSIONS,read_json
from kylin_memory_bench.runner import read_run,verify_run
def pct(value):return '未观测' if value is None else f'{value*100:.2f}%'
def safe(text):return str(text).replace('|',' / ').replace('\n',' ')
def main():
    lines=['# openKylin 真实实验结果','',
           '本文件由 scripts/summarize_experiments.py 从已校验的实测证据生成。原始失败、未知项和执行错误均保留；不拼接选择性重跑结果。','',
           '系统：openKylin 2.0 SP1 / WSL 2，Python 3.12.2。固定原生版本与系统包见 evidence/openkylin-environment.json。两个智能体共同调用 deepseek-flash，temperature=0，非思考模式，每请求最多 2048 输出 tokens。','']
    for folder,title in [('openkylin-core','标准集'),('openkylin-challenge','独立挑战集')]:
        root=ROOT/'examples'/folder;verify_run(root)
        m,cases,events,scores=read_run(root);config=read_json(root/'config.json')
        metadata=read_json(root/'experiment.json')
        review=read_json(root/'reviewed-scores.json') if folder=='openkylin-challenge' else None
        if review:
            lines += ['## 挑战集答案标注订正（实测后公开修订）','', '两系统三轮均返回正确的“松柏项目”，原标注仅接受“松柏”，造成六次等价答案误判。订正版统一接受这两个显式别名；其余 156 个检查、原始提示、回答和全部执行错误均保持原样。原始报告仍保留，不能将原始 confusion 六项解释为记忆失败。','', '| 系统 | 原始下界 | 订正下界 | 订正上界 | 覆盖率 |','|---|---:|---:|---:|---:|']
            for a,b in zip(scores['agents'],review['agents']):
                lines += ['| '+a['id']+' | '+pct(a['overall']['lower_bound'])+' | '+pct(b['overall']['lower_bound'])+' | '+pct(b['overall']['upper_bound'])+' | '+pct(b['overall']['coverage'])+' |']
            lines += ['', '[订正后完整报告](../examples/openkylin-challenge/reviewed-report.html) · [逐项订正记录](../examples/openkylin-challenge/score-review.json)。运行 `python3 scripts/review_challenge.py --check` 可独立复算，且不调用模型。下方标准表仍展示冻结的原始分数。','']
        lines += ['## '+title,'',
                  f'运行 ID：{m["run_id"]}。{len(cases)} 个案例，两款智能体各 {m["repeats"]} 轮，共 {len(events)} 个步骤事件。状态：{m["status"]}。',
                  f'UTC 起止：{m["started_at"]} 至 {m["finished_at"]}。jobs={m.get("jobs",1)}；超时配置：'+', '.join(a['id']+'='+str(a.get('timeout'))+' 秒' for a in config['agents'])+'。','',
                  '| 系统 | 通过 | 失败 | 未知 | 错误项 | 已观测分 | 下界 | 上界 | 覆盖率 | 三轮标准差 |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for a in scores['agents']:
            counts=collections.Counter()
            for c in a['cases']:counts.update(c['statuses'])
            values=[a['id']]+[str(counts[s]) for s in ('pass','fail','unknown','error')]+[pct(a['overall'][k]) for k in ('score','lower_bound','upper_bound','coverage')]+[pct(a['stability']['stddev'])]
            lines += ['| '+' | '.join(values)+' |']
        lines += ['','上表通过/失败等为未加权检查项数；得分与覆盖率为案例及维度宏平均，不能直接用项数相除替代。','',
                  '| 维度 | '+ ' | '.join(a['id']+' 下界 / 覆盖率' for a in scores['agents'])+' |',
                  '|---|'+ '|'.join('---:' for _ in scores['agents'])+'|']
        for d,label in DIMENSIONS.items():
            lines+=['| '+label+' | '+' | '.join(pct(a['dimensions'][d]['lower_bound'])+' / '+pct(a['dimensions'][d]['coverage']) for a in scores['agents'])+' |']
        lines+=['','### 重复与运行故障','']
        for a in scores['agents']:
            lines += ['- '+a['id']+' 各轮下界：'+', '.join(pct(x) for x in a['stability']['trial_lower_bounds'])+'。记录步骤 P50 / P95：'+f'{a["runtime"]["latency_p50_ms"]/1000:.2f} / {a["runtime"]["latency_p95_ms"]/1000:.2f} 秒。']
        errors=[e for e in events if e.get('error')]
        roots=[e for e in errors if not e['error'].startswith('Earlier step failed')]
        lines += ['',f'执行错误事件 {len(errors)} 个，其中实际执行失败 {len(roots)} 个，前序失败后跳过 {len(errors)-len(roots)} 个。评分表中的“错误项”数量可能不同，因为各步骤的验证项数不同。','']
        for e in roots:
            link=f'../examples/{folder}/evidence.html#event-{e["event_id"]}'
            lines += [f'- [{e["agent_id"]} / 第 {e["trial"]+1} 轮 / {e["case_id"]} / {e["step_id"]}]({link})：'+safe(e['error'])]
        lines+=['','时延含 CLI 启动、工具、预算代理队列、网络和模型，并包括跳过步骤的近零时长。它是本次全部记录步骤的描述指标，不能作为模型纯推理速度或跨数据集性能排名。','',
                '### 能力失败与证据不足','']
        for a in scores['agents']:
            failed=[(c,ch) for c in a['cases'] for ch in c['checks'] if ch['status']=='fail']
            category=collections.Counter(ch['category'] for _,ch in failed)
            lines += ['- '+a['id']+' 能力失败类别：'+(safe(dict(category)) if category else '未观察到可判定的能力失败')+'。']
            # Deterministic first four examples, with all other cases available in the report.
            for c,ch in failed[:4]:
                link=f'../examples/{folder}/evidence.html#event-{ch["evidence_id"]}'
                lines += [f'  - [{safe(c["title"])} / {ch["check_id"]}]({link})：{ch["category"]}。']
        lines += ['','记忆快照默认仅部分可见。局部文件未出现某值，不足以证明全局删除或从未持久化；此类项保留 unknown，体现在上下界中。','',
                  '### API 审计','',
                  '事件计数：'+safe(metadata.get('audit_counts',{}))+'。',
                  '已记录 completion 的 token 用量（可能不是全部上游请求）：'+safe(metadata.get('usage',{}))+'。',
                  'API 审计保存请求指纹、用量和保护动作；不包含真实模型 key。余额是账户快照，存在结算延迟和其他调用影响，不能当成该运行独立账单。','',
                  f'数据指纹：{m["dataset_sha256"]}。',
                  f'实现指纹：{m["implementation_sha256"]}。','',
                  f'[完整报告](../examples/{folder}/report.html) · [逐事件证据](../examples/{folder}/evidence.html) · [API 审计](../examples/{folder}/api-audit.jsonl)','']
    lines += ['## 审计完整性与交付修复','', '标准集冻结代理中，后置余额查询失败可能导致已返回的模型结果丢失，并遗漏 completion 审计事件。独立对账见 evidence/core-api-accounting.json。交付源码已先落盘用量和审计，再尝试更新余额；不修改既有实验，也不将部分 usage 当作精确完整账单。','', '## 资源控制失败','', '挑战集第 1 轮 OpenClaw 的 revised-artifact/correction 出现重复工具读取，保守费用预留触发一次 budget_stop，随后文件生成步骤跳过。其余案例继续完成。这是给定工具配置与预算下的系统执行失败，不等于账户余额耗尽；没有选择性重跑替换。诊断见 evidence/challenge-resource-guard.json。Hermes 使用 file/memory 工具集，max_turns=6；OpenClaw 允许 read/write/edit/memory_search/memory_get 工具，本次未开启额外 loopDetection。结果是各自明确配置的系统组合评测，工具策略并非完全同构。','', '## 结论范围','',
              '标准集与挑战集分别报告。两套实验使用不同案例、证据需求与并发/超时配置，不比较跨集总分或延迟。三轮重复、小规模合成数据和单一模型服务不足以支持通用产品排名。',
              '原始计划中的天数是明确标注的模拟逻辑时间。本项目没有实际等待相应天数，也没有验证真实时间 TTL、物理断电恢复或任意自然语言任务。',
              '规则基线与历史 Ubuntu pilot 均独立保存；最终报告不将它们混入两套 openKylin 原生实验。','']
    path=ROOT/'docs/results.md';path.write_text('\n'.join(lines),encoding='utf-8');print(path)
if __name__=='__main__':main()
