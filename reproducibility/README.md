# 实验源码与结果复现

真实 openKylin 实验使用开始前冻结的实现。标准集与挑战集均引用以下指纹：

- 实现 SHA256：`a3840b2d3e8582080f9ffe22f8114fe36c513f88e3364d3906e47c79699d61a2`
- 源码归档：`experiment-source-0.2.0.zip`
- 归档 SHA256：`ecdebfe27a7935d70256c11d2bce96422eeb041aa6862166ad0a76ba896e5c18`

归档中的 SNAPSHOT.json 列出文件指纹。归档包含运行时 Python 源码、当时的预算代理、两套实际数据与 MIT 许可证，不包含模型凭据、原生安装二进制或案例工作区。该归档在实验运行过程中生成，生成时检查实现指纹与正在运行的 manifest 一致。

## 原始实现与交付实现

原始事件、manifest、数据、配置和 scores.json 按字节导出。交付版本增加了离线证据检查器、运行环境展示，以及对异常/不完整 OpenClaw 轨迹的更严格拒绝检查。新源码只重新生成 HTML/SVG/CSV 展示，不回填或修订真实回答与成绩。

因此实验 manifest 与当前交付源码的 implementation_sha256 可以不同。接收者可以用冻结源码复核原始实验，也可以用当前源码的 verify 独立重放已有证据。散列用于检测修改，不是可信执行签名。

## 不调用模型的复核

解压源码归档，进入其目录，用 Python 3.9+：

```sh
python3 -m kylin_memory_bench verify /path/to/examples/openkylin-core
python3 -m kylin_memory_bench verify /path/to/examples/openkylin-challenge
```

## 重新运行真实模型实验

沿用固定原生版本与独立用户目录，按 docs/live-experiments.md 配置已有 CLI 和模型服务。数据直接使用归档内 core.jsonl、challenge.jsonl，分别跑三轮，保留所有失败。

标准集配置为两款智能体统一超时 180 秒、jobs=4。实际发现网络长请求和超时后，挑战集作为独立实验预先固定为统一超时 600 秒、jobs=2。模型、温度、输出上限、记忆工具和种子保持一致。两个数据集单独报告，不比较跨集延迟，不选择性替换失败案例。

预算代理默认累计上限 10 CNY，实际使用值以 API 审计中的 start 记录和实验说明为准。连续实验必须复用同一个累计账本；不可删除账本或新建并行账本绕过限额。重新运行将产生模型费用，离线 verify 不收费。

交付预算代理还修复了后置余额查询失败导致已付费结果丢失的问题，增加 10 秒余额查询时限。冻结实验保持旧实现，原始失败不替换；对账说明见 docs/evidence/core-api-accounting.json。完整实验的 usage 汇总仅覆盖实际写入 completion 审计的请求。

交付版另增加 `one_of` 显式等价答案操作，用于修正挑战集一题的答案标注。原始数据和分数完整保留；订正版本另存 `reviewed-*`，用 `scripts/review_challenge.py --check` 复算。这是公开的实测后标注修订，不是重新实验或选择性重跑。
