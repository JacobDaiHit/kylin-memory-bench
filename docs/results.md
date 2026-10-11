# openKylin 真实实验结果

本文件由 scripts/summarize_experiments.py 从已校验的实测证据生成。原始失败、未知项和执行错误均保留；不拼接选择性重跑结果。

系统：openKylin 2.0 SP1 / WSL 2，Python 3.12.2。固定原生版本与系统包见 evidence/openkylin-environment.json。两个智能体共同调用 deepseek-flash，temperature=0，非思考模式，每请求最多 2048 输出 tokens。

## 标准集

运行 ID：dc318856-004f-4b1c-9910-2ab94d6b2633。36 个案例，两款智能体各 3 轮，共 1008 个步骤事件。状态：completed_with_errors。
UTC 起止：2026-10-03T05:23:00.173331+00:00 至 2026-10-03T06:56:44.593553+00:00。jobs=4；超时配置：openclaw=180 秒, hermes=180 秒。

| 系统 | 通过 | 失败 | 未知 | 错误项 | 已观测分 | 下界 | 上界 | 覆盖率 | 三轮标准差 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openclaw | 250 | 16 | 54 | 4 | 93.06% | 79.86% | 93.52% | 86.34% | 1.13% |
| hermes | 241 | 20 | 50 | 13 | 91.18% | 76.23% | 91.20% | 85.03% | 2.46% |

上表通过/失败等为未加权检查项数；得分与覆盖率为案例及维度宏平均，不能直接用项数相除替代。

| 维度 | openclaw 下界 / 覆盖率 | hermes 下界 / 覆盖率 |
|---|---:|---:|
| 长期保持 | 94.44% / 94.44% | 96.30% / 96.30% |
| 记忆调用 | 100.00% / 100.00% | 100.00% / 100.00% |
| 动态更新 | 70.83% / 75.00% | 69.44% / 72.22% |
| 相近区分 | 66.67% / 100.00% | 50.00% / 100.00% |
| 边界识别 | 47.22% / 48.61% | 47.22% / 47.22% |
| 任务复用 | 100.00% / 100.00% | 94.44% / 94.44% |

### 重复与运行故障

- openclaw 各轮下界：81.25%, 78.47%, 79.86%。记录步骤 P50 / P95：26.66 / 47.84 秒。
- hermes 各轮下界：79.17%, 73.15%, 76.39%。记录步骤 P50 / P95：13.85 / 27.90 秒。

执行错误事件 19 个，其中实际执行失败 6 个，前序失败后跳过 13 个。评分表中的“错误项”数量可能不同，因为各步骤的验证项数不同。

- [hermes / 第 2 轮 / boundary-001-224906 / learn](../examples/openkylin-core/evidence.html#event-371)：Adapter exited 1; stderr SHA256 is 65ffcf9da6c4e3c7db2d753e0c726455b3bcfae8f39d22af20c7d02da55e5ff2
- [hermes / 第 2 轮 / reuse-002-207622 / produce](../examples/openkylin-core/evidence.html#event-448)：Adapter exited 1; stderr SHA256 is d44a3182b8ff4c3f24e65acd8c68894fe9d3f058c77aecd5569edc6e30d05b16
- [hermes / 第 2 轮 / retention-003-541046 / noise-0](../examples/openkylin-core/evidence.html#event-449)：Adapter exited 1; stderr SHA256 is 0d005136d1d7c06ef655fc24b249aeb4c6faa8d364cb360adf55e4e3cd4bfbf0
- [openclaw / 第 2 轮 / boundary-005-401193 / positive-control](../examples/openkylin-core/evidence.html#event-607)：Adapter timeout after 180s
- [openclaw / 第 2 轮 / retention-006-614102 / learn](../examples/openkylin-core/evidence.html#event-608)：Adapter timeout after 180s
- [hermes / 第 3 轮 / update-002-207622 / correct](../examples/openkylin-core/evidence.html#event-748)：Adapter exited 1; stderr SHA256 is ea1b5619462b51e27e5d22cbf37e070df0c9b882a86c58b80e6c6114c5ac5288

时延含 CLI 启动、工具、预算代理队列、网络和模型，并包括跳过步骤的近零时长。它是本次全部记录步骤的描述指标，不能作为模型纯推理速度或跨数据集性能排名。

### 能力失败与证据不足

- openclaw 能力失败类别：{'confusion': 12, 'invalid_response': 4}。
  - [相似项目名、相同字段的隔离 / scope-a](../examples/openkylin-core/evidence.html#event-146)：confusion。
  - [相似项目名、相同字段的隔离 / scope-b](../examples/openkylin-core/evidence.html#event-210)：confusion。
  - [更正信息、覆盖旧值并处理撤销 / not-reused](../examples/openkylin-core/evidence.html#event-257)：invalid_response。
  - [相似项目名、相同字段的隔离 / scope-a](../examples/openkylin-core/evidence.html#event-262)：confusion。
- hermes 能力失败类别：{'confusion': 18, 'wrong_persistence': 1, 'stale_memory': 1}。
  - [相似项目名、相同字段的隔离 / scope-a](../examples/openkylin-core/evidence.html#event-34)：confusion。
  - [相似项目名、相同字段的隔离 / scope-a](../examples/openkylin-core/evidence.html#event-91)：confusion。
  - [相似项目名、相同字段的隔离 / scope-b](../examples/openkylin-core/evidence.html#event-145)：confusion。
  - [相似项目名、相同字段的隔离 / scope-b](../examples/openkylin-core/evidence.html#event-201)：confusion。

记忆快照默认仅部分可见。局部文件未出现某值，不足以证明全局删除或从未持久化；此类项保留 unknown，体现在上下界中。

### API 审计

事件计数：{'completion': 2237, 'finished': 1, 'rejected': 11, 'start': 1}。
已记录 completion 的 token 用量（可能不是全部上游请求）：{'completion_tokens': 141685, 'prompt_cache_hit_tokens': 10261120, 'prompt_cache_miss_tokens': 2768779, 'prompt_tokens': 13029899, 'total_tokens': 13171584}。
API 审计保存请求指纹、用量和保护动作；不包含真实模型 key。余额是账户快照，存在结算延迟和其他调用影响，不能当成该运行独立账单。

数据指纹：65b84203c8c2c3b6c7826be1b65742e0ad64c1b023b04f3c4de37a64393ac573。
实现指纹：a3840b2d3e8582080f9ffe22f8114fe36c513f88e3364d3906e47c79699d61a2。

[完整报告](../examples/openkylin-core/report.html) · [逐事件证据](../examples/openkylin-core/evidence.html) · [API 审计](../examples/openkylin-core/api-audit.jsonl)

## 挑战集答案标注订正（实测后公开修订）

两系统三轮均返回正确的“松柏项目”，原标注仅接受“松柏”，造成六次等价答案误判。订正版统一接受这两个显式别名；其余 156 个检查、原始提示、回答和全部执行错误均保持原样。原始报告仍保留，不能将原始 confusion 六项解释为记忆失败。

| 系统 | 原始下界 | 订正下界 | 订正上界 | 覆盖率 |
|---|---:|---:|---:|---:|
| openclaw | 70.37% | 78.70% | 81.48% | 97.22% |
| hermes | 87.50% | 95.83% | 95.83% | 100.00% |

[订正后完整报告](../examples/openkylin-challenge/reviewed-report.html) · [逐项订正记录](../examples/openkylin-challenge/score-review.json)。运行 `python3 scripts/review_challenge.py --check` 可独立复算，且不调用模型。下方标准表仍展示冻结的原始分数。

## 独立挑战集

运行 ID：23b54cdd-32a1-430b-b749-e0e8adadfff4。12 个案例，两款智能体各 3 轮，共 258 个步骤事件。状态：completed_with_errors。
UTC 起止：2026-10-03T07:00:32.932266+00:00 至 2026-10-03T07:34:03.252571+00:00。jobs=2；超时配置：openclaw=600 秒, hermes=600 秒。

| 系统 | 通过 | 失败 | 未知 | 错误项 | 已观测分 | 下界 | 上界 | 覆盖率 | 三轮标准差 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openclaw | 54 | 24 | 0 | 3 | 71.30% | 70.37% | 73.15% | 97.22% | 7.97% |
| hermes | 75 | 6 | 0 | 0 | 87.50% | 87.50% | 87.50% | 100.00% | 0.00% |

上表通过/失败等为未加权检查项数；得分与覆盖率为案例及维度宏平均，不能直接用项数相除替代。

| 维度 | openclaw 下界 / 覆盖率 | hermes 下界 / 覆盖率 |
|---|---:|---:|
| 长期保持 | 50.00% / 100.00% | 50.00% / 100.00% |
| 记忆调用 | 61.11% / 100.00% | 100.00% / 100.00% |
| 动态更新 | 100.00% / 100.00% | 100.00% / 100.00% |
| 相近区分 | 83.33% / 100.00% | 100.00% / 100.00% |
| 边界识别 | 100.00% / 100.00% | 75.00% / 100.00% |
| 任务复用 | 27.78% / 83.33% | 100.00% / 100.00% |

### 重复与运行故障

- openclaw 各轮下界：69.44%, 61.11%, 80.56%。记录步骤 P50 / P95：15.25 / 30.82 秒。
- hermes 各轮下界：87.50%, 87.50%, 87.50%。记录步骤 P50 / P95：8.48 / 18.75 秒。

执行错误事件 2 个，其中实际执行失败 1 个，前序失败后跳过 1 个。评分表中的“错误项”数量可能不同，因为各步骤的验证项数不同。

- [openclaw / 第 1 轮 / challenge-revised-artifact / correction](../examples/openkylin-challenge/evidence.html#event-123)：Adapter exited 1; stderr SHA256 is ac1db8891464813b91254cdd449022a06e2b2b5a85d6bb8d88f84055a4ff8703

时延含 CLI 启动、工具、预算代理队列、网络和模型，并包括跳过步骤的近零时长。它是本次全部记录步骤的描述指标，不能作为模型纯推理速度或跨数据集性能排名。

### 能力失败与证据不足

- openclaw 能力失败类别：{'confusion': 3, 'invalid_response': 8, 'wrong_reuse': 12, 'omission': 1}。
  - [分散消息中的项目与工单关联 / join](../examples/openkylin-challenge/evidence.html#event-9)：confusion。
  - [近似实体存在时拒绝补造未知事实 / known-query](../examples/openkylin-challenge/evidence.html#event-25)：invalid_response。
  - [近似实体存在时拒绝补造未知事实 / missing-entity](../examples/openkylin-challenge/evidence.html#event-31)：invalid_response。
  - [历史条件约定用于结构化文件交付 / file](../examples/openkylin-challenge/evidence.html#event-79)：wrong_reuse。
- hermes 能力失败类别：{'confusion': 3, 'wrong_reuse': 3}。
  - [分散消息中的项目与工单关联 / join](../examples/openkylin-challenge/evidence.html#event-5)：confusion。
  - [选择性遗忘必须保留仍获授权的信息 / forgotten](../examples/openkylin-challenge/evidence.html#event-72)：wrong_reuse。
  - [分散消息中的项目与工单关联 / join](../examples/openkylin-challenge/evidence.html#event-92)：confusion。
  - [选择性遗忘必须保留仍获授权的信息 / forgotten](../examples/openkylin-challenge/evidence.html#event-159)：wrong_reuse。

记忆快照默认仅部分可见。局部文件未出现某值，不足以证明全局删除或从未持久化；此类项保留 unknown，体现在上下界中。

### API 审计

事件计数：{'budget_stop': 1, 'completion': 741, 'finished': 1, 'rejected': 1, 'start': 1}。
已记录 completion 的 token 用量（可能不是全部上游请求）：{'completion_tokens': 87209, 'prompt_cache_hit_tokens': 21583104, 'prompt_cache_miss_tokens': 865657, 'prompt_tokens': 22448761, 'total_tokens': 22535970}。
API 审计保存请求指纹、用量和保护动作；不包含真实模型 key。余额是账户快照，存在结算延迟和其他调用影响，不能当成该运行独立账单。

数据指纹：12aee151ac934ac885bd90a2a5c7d18f5f061a72b788a81aa734c2033627c73a。
实现指纹：a3840b2d3e8582080f9ffe22f8114fe36c513f88e3364d3906e47c79699d61a2。

[完整报告](../examples/openkylin-challenge/report.html) · [逐事件证据](../examples/openkylin-challenge/evidence.html) · [API 审计](../examples/openkylin-challenge/api-audit.jsonl)

## 审计完整性与交付修复

标准集冻结代理中，后置余额查询失败可能导致已返回的模型结果丢失，并遗漏 completion 审计事件。独立对账见 evidence/core-api-accounting.json。交付源码已先落盘用量和审计，再尝试更新余额；不修改既有实验，也不将部分 usage 当作精确完整账单。

## 资源控制失败

挑战集第 1 轮 OpenClaw 的 revised-artifact/correction 出现重复工具读取，保守费用预留触发一次 budget_stop，随后文件生成步骤跳过。其余案例继续完成。这是给定工具配置与预算下的系统执行失败，不等于账户余额耗尽；没有选择性重跑替换。诊断见 evidence/challenge-resource-guard.json。Hermes 使用 file/memory 工具集，max_turns=6；OpenClaw 允许 read/write/edit/memory_search/memory_get 工具，本次未开启额外 loopDetection。结果是各自明确配置的系统组合评测，工具策略并非完全同构。

## 结论范围

标准集与挑战集分别报告。两套实验使用不同案例、证据需求与并发/超时配置，不比较跨集总分或延迟。三轮重复、小规模合成数据和单一模型服务不足以支持通用产品排名。
原始计划中的天数是明确标注的模拟逻辑时间。本项目没有实际等待相应天数，也没有验证真实时间 TTL、物理断电恢复或任意自然语言任务。
规则基线与历史 Ubuntu pilot 均独立保存；最终报告不将它们混入两套 openKylin 原生实验。
