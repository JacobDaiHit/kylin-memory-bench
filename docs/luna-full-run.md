# Luna 全量实验：冻结范围与验收口径

用户确认：第二阶段全部 **160 条历史 × 两款 Agent × 一轮**。主实验使用原先冻结的
`development-v2/native-memory-*.jsonl`，逐字保留输入、答案及评分契约，不重新生成记忆题面。
128 条开发历史和 32 条公开预留历史分开报告；预留部分不是盲测。

另有每条历史、每款 Agent 各一次 `reader_only`：只提交查询及充分的原始证据，
在新的隔离工作区中运行原生 Agent，保留文件工具，允许实际交付任务。
它不学习前面的 128 条历史，也不冒充原五条件中的完整 `oracle_evidence`。
主实验 320 案例、41,280 turn；阅读对照 320 案例、320 turn；共 640 案例、41,600 turn。
工具循环可能使模型请求数高于 turn 数。

## 公平性与资源条件

- 两款 Agent 同用 `gpt-5.6-luna`、`reasoning.effort=none`，同一批学习历史和查询。
- 各自保留原生记忆管理、自动注入及工具。不是“相同检索算法”的实验，也不能宣称输入 token 相同。
- OpenClaw 显式配置本地 `BAAI/bge-small-zh-v1.5` / FastEmbed 0.9.0 / CPU embeddings；
  SQLite 索引、混合检索和工作区仍由 OpenClaw 管理。Hermes 保留自己的原生记忆机制。
- 本地服务只计算文本向量，没有共享记忆库，不读取 gold、不返回答案。正式运行前检查向量索引、
  跨会话复用及空工作区拒答。此前无认证降级运行不混入本次成绩。
- 没有累计金额或模型请求数上限；继续记录 usage、响应模型、超时、故障和中断。
  两者 turn 超时均为 180 秒。套餐接口不提供服务端输出 token 硬上限，原生自动携带但不支持的参数明确记账。
- 四个并发槽，固定种子打乱历史顺序，交替安排两款 Agent；不同条件、案例、Agent 的可写状态独立。
- 真实运行环境是 WSL2/Linux，不冒充 openKylin 原生系统上的实测。

配置依据：[OpenClaw 检索配置](https://docs.openclaw.ai/reference/memory-config)、
[FastEmbed 模型列表](https://qdrant.github.io/fastembed/examples/Supported_Models/)。

## 故障、恢复与复核

`run_plan_full.py` 在调用前复制源码和原数据、冻结全部任务及文件指纹。每个案例使用核心 runner
生成独立哈希证据链、真实文件快照、配置和分数。请求流与 token usage 单独持续保存。

完成、失败、被中断的案例均保留，不自动重跑；恢复只执行从未开始的案例。普通内容答错不会
触发停机。连续三例执行错误则停止派发新案例，保留已开始的工作与未执行分母，先定位基础设施问题。
存在 `STOP` 文件时不继续派发；不能用恢复把失败改写成成功。

中途进度在 `progress.json`；完成后自动生成 `analysis.json`、逐题复核状态和 `report.html`。
报告分别列记忆内容、格式、文件交付、工具证据可见性、执行错误和未执行项。
原始材料可能含私人路径和原生系统提示，不能直接公开整个运行目录；公开交付前必须做脱敏、打包和复核。

## 报告与视频

本轮按全计划分母报告，内容失败不筛掉，不看完结果后调整 gold、难度档位或题型。
阅读对照也错的题，应优先分析理解和规则应用，不能一概称为遗忘。文件错误与内容错误分开。

只有结果实际产生并通过逐案例复核后，才将数值写入提交报告。单轮可以展示执行能力、具体失败
和探索性难度现象，不能声称稳定排名或统计显著差异；也不替代此前规定的三轮难度验收门槛。
视频保留历史三轮实验的来源，新 Luna 全量实验明确标注“一轮”。完整执行、证据完整性和结果
解释尚未检查完时，只能准备录制清单，不能宣布最终成片可以定稿。

## 本机操作

```bash
# 独立运行环境：pip install fastembed==0.9.0
/tmp/kmb-embedding-venv/bin/python scripts/local_embeddings.py \
  --cache /tmp/kmb-embedding-model --ready tmp/local-embedding-ready.json
# 不调用 Luna 的原生向量检索检查：
python -m scripts.check_plan_memory
# 双 Agent 真实健康检查（输出目录必须是新目录）：
tmp/chatgpt-plan-venv/bin/python -m scripts.run_plan_health \
  --output tmp/plan-vector-health-01 --live --embedding-url http://127.0.0.1:18789/v1
# prepare 会检查这两份记录。
python -m scripts.run_plan_full prepare --output /home/maedaily/.local/share/kmb-live/runs/kmb-plan-full-20261013
python -m scripts.run_plan_full run --output /home/maedaily/.local/share/kmb-live/runs/kmb-plan-full-20261013
python -m scripts.run_plan_full status --output /home/maedaily/.local/share/kmb-live/runs/kmb-plan-full-20261013
```

这些路径是本机运行约定，不是跨机器安装接口；实际调用需要在已有 ChatGPT 授权的虚拟环境中运行。

## 单会话复核修订（首次运行已保留）

首次派发后，两条阅读对照已成功生成输出，但事后使用核心记忆复核器时报
`memory evaluation requires at least two sessions`。这是运行器接口使用错误，不是模型失败。
新增 `plan_reader_replay.py` 专门复核预先冻结的单会话对照：逐项检查原输入、配置、会话身份、
文件快照、证据链及重新计算的分数。两份真实记录离线通过；没有重新调用模型。

运行目录 `amendments/reader-replay-1` 保存旧协议、原控制器错误状态和修订原因。
题目、gold、两款 Agent 配置及评分逻辑保持不变；旧源码仍在 `frozen/source`，修订源码另存。
旧控制器只完成已开始的案例；新控制器按任务租约补充空余槽位，总并发仍为 4。
当前状态由协议指向 `progress-reader-replay-1.json`，`status` 命令自动读取正确文件。
其中 `observed_agent_turns` 是**落盘事件槽位数，包含故障后的跳过项**，不能当成成功执行次数。

完成后，`watch_plan_report.py` 再次复核各案例，并将不含原生提示、凭据和私人路径的逐题摘要
写入 `docs/evidence/luna-full-results.json` 和 `docs/luna-full-results.md`。它不自动提交或发布。
未完整结束时只生成明确标注的部分报告，不能借此宣布可定稿视频。

[公开冻结清单](evidence/luna-full-protocol.json)与[本地向量／隔离检查摘要](evidence/luna-local-memory-preflight.json)
可以核对试题范围和运行条件。代码回归：完整 231 项通过；另新增的脱敏报告回归 1 项通过。
这些是软件检查，不是 232 道模型记忆成绩。
