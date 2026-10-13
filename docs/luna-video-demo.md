# Luna 六维操作演示：2026-10-14

六维各选标准集首例，固定在运行前，两款原生 Agent 各一轮。共 12 个案例、56 个事件，全部正常结束，执行错误 0。实际耗时 831.57 秒（约 13 分 52 秒）。

模型请求共 146 次，完成 145 次、失败 1 次；失败与原生恢复记录保留，不由评测器重跑覆盖。所有已完成请求返回 gpt-5.6-luna。上游没有强制输出额度或采样参数，因此不是历史 DeepSeek 的同配置重复。

| 系统 | 已观测分 | 覆盖率 | 下界 | 上界 |
|---|---:|---:|---:|---:|
| openclaw | 63.89% | 87.50% | 52.78% | 65.28% |
| hermes | 91.67% | 87.50% | 79.17% | 91.67% |

本轮为操作演示，题库与历史标准集重叠，仅单轮；不支持稳定产品排名，不证明总体难度。未知项不是通过，正常结束不代表满分。模型运行发生在 Ubuntu WSL，openKylin UKUI 用于展示保存报告。

[OpenClaw 报告](../examples/luna-video-demo-openclaw/report.html) · [Hermes 报告](../examples/luna-video-demo-hermes/report.html) · [同数据对照](evidence/luna-video-comparison/report.html)

[冻结协议](evidence/luna-video-protocol.json) · [元数据与失败记录](evidence/luna-video-requests-public.json) · [原始执行源码](../reproducibility/luna-video-source-20261014.zip)

完整原生工作区与 API 请求原件保留在本地，不进入交付。公开运行导出保留原始事件和散列链，配置中的临时认证值由核心脱敏；可用 verify 离线重算。录屏时可展示结果回放，但不能称为已经录到现场连续执行。
