# Memory Stress 0.2

第二阶段的 160 条独立历史：多跳、同字段更新、集合授权、反馈经验复用，四题族、四档、每格十条。128 条开发历史、32 条留出预留；全部仅离线准备。

[审查修复](../../../docs/memory-stress-audit-fixes.md)已补答案候选唯一性、实际文件失败反馈转发和逐事件 fsync。任务协议与输入不变，评分实现单独标版本；原源码和冻结协议归档，未调用模型。

首期审查修复另存为 [0.1.1 修正版](development-v1-1/index.html)，不覆盖 0.1 原件：未知工具轨迹不计为零，nullable 输出格式不依赖 gold，最后有效更新位置固定。六条原生小试与独立 reader_only 输入已预选，尚未执行模型。

打开 [分片式离线导览](development-v2/index.html)，阅读 [设计与完整用法](../../../docs/memory-stress-phase2.md)。候选方案完整对称，避免通过“中心方案”猜答案；主回答保持短值，反馈主任务另外验收真实文件。

```sh
python3 -X utf8 -m experiments.memory_stress.v2 prepare --cohort revision-v1 --output runs/stress-v1-1
python3 -X utf8 -m experiments.memory_stress.v2 prepare --output runs/stress-v2
python3 -X utf8 -m experiments.memory_stress.v2 verify-prepared runs/stress-v2
python3 -X utf8 -m experiments.memory_stress.v2 smoke --output runs/stress-v2-offline-smoke
python3 -X utf8 -m experiments.memory_stress.v2 chain-smoke --output runs/stress-v2-chain
```

`development-v2/` 冻结默认 memory 主查询、原始世界、证据、配对检查与导览。其他条件／表达／查询通过参数生成，所有相关版本保持分组。保留整个目录即可离线打开页面，无需服务器。

`environment.py` 是模拟验收器，规则不代表真实 OS 限制。受控迁移来自脚本工具经历；完整行动链另由 `chain.py` 保存实际尝试、失败和反馈，分开报告。`reference_adapter.py` 是有限语法的软件工具，用于验证管线，不是 LLM 基线。

未执行付费模型、原生健康、独立人审或盲测；真实难度和区分度未知。首期 30 条代码与材料没有被修改，仍可用原命令复核。
