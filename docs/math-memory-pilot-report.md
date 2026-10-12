# 数学研究记忆：真实可行性试测报告

本轮实际调用付费模型，使用原生OpenClaw与Hermes，在openKylin独立工作区各运行一轮。它是可行性检查，不是三轮难度验收或系统排名。

**当前判定：没有达到继续纳入正式记忆测量或成片结论的条件。** 修订版12个最终槽位中，9个执行错误、1个JSON外层格式失败；2个可评分数学响应均未通过。不能把未知项算成能力错误，不能据此排名。

## 版本与冻结

V1的首个可读取响应暴露题面歧义：两份accepted快照没有明确写出覆盖顺序。为避免继续浪费预算，主动停止。保留全部已发生证据、格式失败、执行错误及未完成项，另开V2，未覆盖旧答案或重跑同一失败题。V1终止时WSL子进程退出早于引擎写入结束状态，故保留原running清单并单独记录中断状态恢复操作；原证据链未改动。

V2明确按时间顺序覆盖同项目批准快照，固定来源顺序；采用二维小型矩阵，统一提供展开公式。完整资料组在新会话直接给当前条件，历史与记忆组不匹配，只作为数学任务可完成性的对照，不支持严格因果解释。

六个实例预先冻结：四阶历史、四阶完整资料、六阶历史、六阶完整资料、资料缺失、D奇异。两款系统各一轮，共12个最终槽位。未按结果筛题或替换失败。两者仍沿用历史原生文件/记忆工具配置；没有执行计算器工具，模型输出上限2048，temperature=0，thinking关闭，Hermes内部max_turns=6。

## 逐项真实结果

| 系统 | 实例 | 事件 | JSON外层 | 完整当前输入 | 数学结果 | 实际文件 |
|---|---|---:|---|---|---|---|
| hermes | math-v2-reasoning-low--memory | 10 | 未知 | 未知 | 未知 | 未知 |
| openclaw | math-v2-reasoning-low--oracle | 15 | 通过 | 未通过 | 未通过 | 通过 |
| openclaw | math-v2-reasoning-low--memory | 17 | 未通过 | 未知 | 未知 | 未通过 |
| hermes | math-v2-reasoning-low--oracle | 18 | 未知 | 未知 | 未知 | 未知 |
| hermes | math-v2-reasoning-high--memory | 29 | 未知 | 未知 | 未知 | 未知 |
| openclaw | math-v2-reasoning-high--memory | 33 | 通过 | 未通过 | 未通过 | 通过 |
| openclaw | math-v2-reasoning-high--oracle | 34 | 未知 | 未知 | 未知 | 未知 |
| hermes | math-v2-reasoning-high--oracle | 37 | 未知 | 未知 | 未知 | 未知 |
| hermes | math-v2-reasoning-high--no_history | 39 | 未知 | 未知 | 未知 | 未知 |
| openclaw | math-v2-reasoning-high--no_history | 40 | 未知 | 未知 | 未知 | 未知 |
| hermes | math-v2-applicability-singular--oracle | 43 | 未知 | 未知 | 未知 | 未知 |
| openclaw | math-v2-applicability-singular--oracle | 44 | 未知 | 未知 | 未知 | 未知 |

执行错误数：9；缺失最终事件数：0。格式或执行失败时，数学与记忆结果保持未知，不能称为已观测的错误。实际文件“通过”仅表示文件存在；内容正确性与回答一致性另见逐项JSON。

## 判断与下一步

判定是否有推进价值，首先看四阶/六阶完整资料组是否能可靠完成数学任务。若该组未通过，本轮无法将历史组的主要失败归因于记忆，也不足以声称数学题已验证出区分度。研究工作流题族仍可探索，但完整数学证书交付应作为独立的端到端任务指标。

具体可读取证据：OpenClaw四阶完整资料组拿到了CURRENT_INPUTS，却返回insufficient，并将这个错误回答写入文件。六阶历史组的A/B/D、分支和v4全部恢复正确，但sources使用字符串而非数组，并把本来适用的方法判为method_invalid。四阶历史组正文出现正确条件与c4，但不是约定JSON、没有实际证书，故正式评分保持未知；正文之后也出现了错误的行列式展开，不能称为数学任务完成。

9次最终执行错误既包括原生CLI退出，也受到上游读取超时和后段预算保护阻断影响。仅有stderr散列时不猜测根因；预算阻断不能当作智能体无能力。JSON外层检查不等同于所有字段类型都正确，来源类型与数学条件分别诊断。

建议下一版拆成三个阶段：先只要求恢复当前输入与方法适用条件；再用确定性代数程序核验恢复输入的下游后果；最后单独测模型推导及工具交付。这样可在保持研究条件复杂度的同时，减少长计算和格式失败对记忆观测的遮蔽。任何后续付费试测仍须新冻结协议和预算，不能用人工参考策略的通过率替代真实运行。

## 费用与复核

V1+V2的已记录token保守增量费用估算为1.81762208元，账户区间余额减少0.73元；原难度验证阶段累计保守增量估算为4.84334800元，受原5元上限保护。视频预留1元未使用。中断时在途请求可能缺少usage，余额差也不是逐笔核对后的账单。预算保护同时核对余额与估算，不清零累计账本。

- [V2离线结果页](evidence/math-pilot-v2/index.html)、[逐项结果](evidence/math-pilot-v2/results.json)。
- [V1完整槽位说明](evidence/math-pilot-v1-complete-accounting/results.json)、[停止状态恢复记录](evidence/math-pilot-v1-stop-recovery.json)。
- [V2冻结输入与规则](../experiments/math_memory/pilot-v2/protocol.json)、[运行冻结指纹](evidence/math-pilot-v2-freeze.json)。
- [V2原始证据](../examples/openkylin-math-pilot-v2/evidence.html)、[V1原始证据](../examples/openkylin-math-pilot-v1/evidence.html)。
- [数学原型与推导说明](../experiments/math_memory/README.md)、[脱敏费用汇总](evidence/math-pilot-budget-summary.json)。

- [网络与额度阻断分类](evidence/math-pilot-network-summary.json)：仅披露归类和时间，不公开私人余额与原始错误正文。

分析阶段修复了read_run返回值解包，并补充逐字段诊断、未发生槽位和HTML展示；未改变已冻结的题目、答案或主判据。输入/答案指纹在分析前重新核对；分析器指纹保存在结果JSON。历史0.2.0和原难度试测结果保持不变。
