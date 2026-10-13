# 视频专用 openKylin Luna 双 Agent 实测

本轮从真实 openKylin 2.0 SP1 / WSL 2 启动标准库评测框架和两款原生 Agent。Ubuntu 只提供 Luna 模型转发桥与无状态 BGE 嵌入服务，OAuth 不复制。共享的是固定原生运行时，不共享案例记忆。

预先选择标准集六维首例，两款各一轮，共 12 个案例、56 个计划事件。56/56 正常完成，执行错误 0；模型请求 151 次全部完成，返回模型均为 gpt-5.6-luna，评测器没有重跑案例。实际耗时 540.55 秒（约 9 分 1 秒）。

运行编号：`23d1cec0-e386-412c-a081-4f52b53097c4`。

| 系统 | 已观测分 | 覆盖率 | 下界 | 上界 |
|---|---:|---:|---:|---:|
| openclaw | 75.00% | 91.67% | 70.83% | 79.17% |
| hermes | 83.33% | 91.67% | 75.00% | 83.33% |

运行前实际 namespace 探针验证安装答案、项目、凭据和其他工作区均不可见；隔离失败会阻断模型调用。修订前原件及失败审计另存，不替换或混算。

正常结束不等于满分。单轮演示的案例与公开标准集重叠，不支持稳定排名；上游没有强制输出上限，不是历史 DeepSeek 同配置重测。新分数不与历史三轮或压力校题混算。

[双系统报告](../examples/openkylin-luna-video/report.html) · [雷达图](../examples/openkylin-luna-video/radar.svg) · [逐事件证据](../examples/openkylin-luna-video/evidence.html) · [冻结协议](../examples/openkylin-luna-video/video-protocol.json) · [Luna 请求元数据](evidence/openkylin-luna-video-requests.json) · [执行源码](../reproducibility/openkylin-luna-video-source-20261014.zip)

本轮是录制入口的真实验收，不是已经完成的连续桌面录像。正式录屏按 [全流程手册](recording-runbook.md) 在录像开始后创建新的运行；保留原片和实际等待，不能用结果回放冒充完整运行录屏。此前 Ubuntu 六维演示继续单独保留。

[安装资料隔离前后审计](evidence/installed-benchmark-isolation-audit.json) · [修订前原件与限制](openkylin-luna-video-initial.md)
