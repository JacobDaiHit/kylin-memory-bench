# 难度与区分度前置试测

来源运行：`c49728c3-101a-4c94-9556-18b85d9c3406`。状态：`failed_gate`。

此报告由 verify_run/read_run 独立重放，不改变原运行。能力域为 content/artifact/action；memory 仅作可见性诊断。格式、执行和 unknown 不冒充内容错误。

有效判据使用等权计数；原正式加权评分完整保留在源运行。门槛为描述性验收，不是统计显著性或广泛排名。

重算：`python scripts/analyze_difficulty.py --run <源运行目录> --output <本报告目录> --check`。退出 0 为通过，3 为门槛未通过但报告有效，2 为输入或复核错误。

源文件 SHA256：

- manifest.json: `7b9eb88706427ff5937c380cf45e409a446138fc8f9028779d729c011f16a239`
- dataset.jsonl: `bf8e05ac2f31462a9e54ae898eb5aa5f8cb8a1c3d892d121bc009e3bc2e1ee62`
- config.json: `7bf39fb4a89797eda6a9e4124ba79525d4ac6ec9493f2516926e9788341341c5`
- evidence.jsonl: `c45c77d5eae7d1b7684e39869891e1f7b462e96ce05fe9330fde51ca93cf871b`
- scores.json: `98d78be364a5410d7ab1b545c6a869db4a0db72795855945c4536ca4ad186bf7`
