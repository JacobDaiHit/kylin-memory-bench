# openKylin 首轮演示原件：隔离修订前

**本轮运行完成，但后续审计发现已安装评测资料仍可从 /usr/share 访问。它不作为最终记忆隔离验收，原始事件与分数保持不变。不假设实际泄漏，也不证明没有读取。最终录制入口另存修订协议。**

本轮从真实 openKylin 2.0 SP1 / WSL 2 启动标准库评测框架和两款原生 Agent。Ubuntu 只提供 Luna 模型转发桥与无状态 BGE 嵌入服务，OAuth 不复制。共享的是固定原生运行时，不共享案例记忆。

预先选择标准集六维首例，两款各一轮，共 12 个案例、56 个计划事件。56/56 正常完成，执行错误 0；模型请求 150 次全部完成，返回模型均为 gpt-5.6-luna，评测器没有重跑案例。实际耗时 544.72 秒（约 9 分 5 秒）。

运行编号：`df825bc0-e233-45c4-9a56-afacc6148782`。

| 系统 | 已观测分 | 覆盖率 | 下界 | 上界 |
|---|---:|---:|---:|---:|
| openclaw | 61.11% | 87.50% | 52.78% | 65.28% |
| hermes | 91.67% | 87.50% | 79.17% | 91.67% |

正常结束不等于满分。单轮演示的案例与公开标准集重叠，不支持稳定排名；上游没有强制输出上限，不是历史 DeepSeek 同配置重测。新分数不与历史三轮或压力校题混算。

[双系统报告](../examples/openkylin-luna-video-initial/report.html) · [雷达图](../examples/openkylin-luna-video-initial/radar.svg) · [逐事件证据](../examples/openkylin-luna-video-initial/evidence.html) · [冻结协议](../examples/openkylin-luna-video-initial/video-protocol.json) · [Luna 请求元数据](evidence/openkylin-luna-video-initial-requests.json) · [执行源码](../reproducibility/openkylin-luna-video-initial-source-20261014.zip)

本轮是录制入口的真实验收，不是已经完成的连续桌面录像。正式录屏按 [全流程手册](recording-runbook.md) 在录像开始后创建新的运行；保留原片和实际等待，不能用结果回放冒充完整运行录屏。此前 Ubuntu 六维演示继续单独保留。
