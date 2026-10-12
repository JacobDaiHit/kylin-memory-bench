# 0.2.1 修订与验证记录

0.2.1 尚未完成发布验收。以下工程验证不能代替难度试测。

2026-10-12进一步修订见[数学V3.1与评分修复记录](memory-revision-v31.md)。下方原校准和源码指纹记录保留，当前源码的复算结果另存于scoring-calibration-v31和scoring-version-comparison-v31；它们不覆盖此前验收。

## 评分契约校准

固定样例为回答 12 条、记忆 8 条、工具／文件 10 条，另有 4 组指定预期值的指标对照。结果为 30/30 样例、4/4 指标组符合预期，误通过 0。

[固定样例](evidence/scoring-calibration.jsonl) 保存预期状态与类别；[校准报告](evidence/scoring-calibration/report.html)、[JSON 结果](evidence/scoring-calibration/results.json) 和 CSV 保存实际标签、理由与说明。样例由 AI 辅助构造，没有独立人审；契约一致性不等于独立人审准确率，也不证明题目区分度。

当前源码复算：`python3 scripts/calibrate_scoring.py --check docs/evidence/scoring-calibration-v31`。原报告保留其当时源码指纹。

## 评分实现的版本化修订

0.2.0 的结构化文件检查沿用回答解析逻辑，带 Markdown 代码围栏的文本可能被当成合法 JSON 文件。0.2.1 对实际文件使用严格 JSON 解析；对话回答接受单个 JSON 代码块的既有契约继续保留。

[独立版本对照](evidence/scoring-version-comparison.json) 从冻结的 0.2.0 源码 ZIP 加载旧评分器，对相同保存证据分别计算：两套历史实验原分数均与旧评分器相符，且新旧评分没有逐判据变化。30 条校准样例中有 1 条变化：含代码围栏的 JSON 文件负例从误通过变为失败。

对照独立保存，不覆盖历史 scores.json，也不合并挑战集答案别名订正。当前源码复算：`python3 scripts/compare_scoring_versions.py --check docs/evidence/scoring-version-comparison-v31.json`；原对照仍保留。

## openKylin 底座验证

[实际记录](evidence/foundation-openkylin-0.2.1.json) 来自 openKylin 2.0 SP1 / WSL 2、Python 3.12.2。新进程通过 `env -i` 清空环境，运行在 `unshare --net` 创建的网络命名空间中，接口检查仅见 lo。

标准集 1008 个事件和挑战集 258 个事件均离线复核通过。修改副本第一条提示后，校验器拒绝副本；原件不变。

参考命令适配器在三个不同 PID 的进程中执行。同一工作区跨新会话计数为 1→2，另一工作区计数为 1。它验证参考流程的跨进程状态与工作区隔离，不覆盖真实智能体记忆算法、真实时间 TTL、全局删除、物理断电或裸机启动。

复做时使用新的输出文件：

```sh
sudo unshare --net -- su - kmb -c 'env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 python3 /mnt/d/github/openkylin/scripts/validate_foundation.py --output /mnt/d/github/openkylin/runs/foundation-new.json'
```

## 新增费用保护

预算代理新增 `--additional-budget-cny`，同时限制本进程新增保守费用估算和相对启动余额的下降，保留累计估算、请求数和初始余额；失败请求仍保留预留费用。本轮难度试测新增上限 5 元，视频补充的 1 元另行保留。

余额原值、凭据、代理临时配置和原生工作区不进入公开附件。费用上界是保护估算；余额变化也可能受其他调用和结算延迟影响，不能当成独立账单。

## 难度试测状态

两次尝试与实际门槛结论已保存于 [难度试测报告](difficulty-report.md)。原共享盘中断尝试和本地工作区完整尝试分别公开，均未覆盖历史结果。
