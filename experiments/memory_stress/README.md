# Memory Stress 0.1

首期 30 条开发历史的离线实现：多跳关联 15 条、同字段更新／局部撤销 15 条，各家族三档、每档五个独立种子。代码使用 Python 标准库，没有模型调用入口。

先打开 [交互导览](development-v1/index.html)，再阅读 [设计与完整使用说明](../../docs/memory-stress-design.md)。主查询只输出一个短值，默认准备五种资料／状态条件，每条件 30 个独立查询案例；题量始终按 30 条历史统计。

本次 [离线验收记录](../../docs/evidence/memory-stress-offline-validation.json) 包含构造检查、回归测试、子进程状态控制和费用计数核对。

```sh
python3 -X utf8 -m experiments.memory_stress prepare --output runs/stress-development
python3 -X utf8 -m experiments.memory_stress verify-prepared runs/stress-development
python3 -X utf8 -m experiments.memory_stress smoke --output runs/stress-offline-smoke
```

| 文件 | 职责 |
| --- | --- |
| `world_generator.py` | 可复现实体图、批准／草稿／撤销事件、随机事实与反事实配对 |
| `oracle.py` | 有效状态、历史状态、答案、充分证据与整组删除检查 |
| `render_history.py` | 同事实三种确定性表达及独立语法读回 |
| `calibrate_stress.py` | 分离内容／格式，保留计划分母，按历史统计与配对检查 |
| `suite.py` | 五条件输入、一次独立最终探针、冻结、重放与导览生成 |
| `reference_adapter.py` | 无模型的模板软件适配器，用于子进程持久状态检查 |

`development-v1/` 保存冻结的默认基础题与评测方材料。原数学 V3.1 与旧实验没有被修改；软件预设策略不代表真实 LLM 记忆基线。此题库尚未经过付费原生试测、独立人审或留出集验证。
