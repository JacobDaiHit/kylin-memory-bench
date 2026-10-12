# 基础设施中断尝试：不是完整三轮能力结果

运行 ID：`5adbf74e-5a59-4c46-a2e8-55e2ae2025b8`。状态 `interrupted`，101 个事件、81 个执行错误。manifest 中 repeats=3 是计划轮次，不表示三轮已完成。

工作区放在 Windows 共享盘。OpenClaw 拒绝非用户所有的状态目录；Hermes 报 SQLite 权限错误并重建状态库。两款系统的持久化前提失效，因此主动中断，避免继续无效付费调用。这些执行问题不作为记忆能力差异。

本目录原样复制 manifest、dataset、config 和 evidence；scores 是对中断证据另行生成的独立重放，缺失步骤保留 unknown。源运行没有被补写分数或改成 completed，后续本地文件系统修正尝试另存。

API 审计导出仅保留白名单元数据，移除余额原值和自由文本错误；私有原审计仍在本地。两次尝试共用原累计账本与新增 5 元上限，没有清零费用记录。

```sh
python3 -m kylin_memory_bench verify examples/openkylin-difficulty-interrupted
```

复核成功仅表示保存证据完整、分数可重放，不表示实验完成或智能体能力通过。
