# 难度与区分度试测报告

**描述性验收未通过。** 有效能力判据观测率 96.76%，达到预定难度效应门槛的家族 1/6。

完整逐题、逐轮、判据分类、波动与证据链接见 [分析报告](evidence/difficulty-analysis/report.html)。

## 两次尝试的来源

- 初次共享盘尝试：`5adbf74e-5a59-4c46-a2e8-55e2ae2025b8`，状态 interrupted，101 个事件、81 个执行错误。OpenClaw 状态目录所有权拒绝，Hermes SQLite 权限错误与状态库重建，使持久化前提无效；停止后保留 [完整中断证据](../examples/openkylin-difficulty-interrupted/report.html)。它不是完整三轮能力结果。
- 基础设施修正尝试：`c49728c3-101a-4c94-9556-18b85d9c3406`，状态 completed_with_errors，270 个事件、1 个执行错误。工作区迁到 openKylin 本地用户目录；题目、答案、模型配置和评分代码不变，12 题全部执行三轮，没有选择性替换题目或覆盖第一次尝试。

修正前新增目录所有权、chmod 和跨进程 SQLite 检查；两次使用同一累计账本，共同受新增 5 元上限约束。保守新增费用上界 3.02572592 元，不能当作独立账单；视频补充的 1 元尚未使用。

## 家族难度效应

| 家族 | 三轮平均正确率下降 | 两轮同向且下降≥15个百分点 |
|---|---:|---|
| boundary | 16.67% | 是 |
| disambiguation | 0.00% | 否 |
| retention | 0.00% | 否 |
| retrieval | 11.11% | 否 |
| reuse | 0.00% | 否 |
| update | 0.00% | 否 |

## 可以支持的结论

未达到预定门槛，暂停“难度充分／能力排名”及最终成片定稿。应先依据格式、执行、证据不足与内容判据的实际分布处理测量问题；不临时改变答案、分母或制造某款系统的败题。
逐家族的条件性差异见分析报告与逐判据证据；不得把不同数据集分数混合排名。

记忆快照仅作可见性诊断；逻辑时间不等于真实跨天老化。格式、执行和未知项分别报告，原有加权评分完整保留。

复算：`python3 scripts/analyze_difficulty.py --run examples/openkylin-difficulty --output docs/evidence/difficulty-analysis --check`。退出码 3 表示难度验收未通过，不能与证据损坏混为一谈。
