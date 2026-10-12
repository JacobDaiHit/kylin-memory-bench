# 数据结构与扩展

数据为 UTF-8 JSONL，每行一个案例。结构声明见 `schemas/dataset.schema.json`；唯一 ID、单调时间、跨会话、路径和各 source/op 的组合由 `kmb validate` 进一步检查。JSON Schema 不能代替这些语义约束。

## 最小案例

```json
{
  "schema_version": "1.0",
  "id": "preference-001",
  "title": "跨会话保留输出格式",
  "dimension": "retention",
  "synthetic": true,
  "tags": ["preference", "session-gap"],
  "steps": [
    {
      "id": "learn", "kind": "message", "day": 0, "session": "a",
      "prompt": "我的报告默认使用 Markdown。请长期记住。",
      "checks": []
    },
    {
      "id": "recall", "kind": "probe", "day": 7, "session": "b",
      "prompt": "我的报告格式是什么？只返回 JSON 的 answer 字段；未知返回 null。",
      "checks": [{"id":"format","source":"response","op":"equals","pointer":"/answer","value":"Markdown","failure":"omission","weight":1}]
    }
  ]
}
```

添加自定义案例不要求遵循默认生成器的语言模板。内置规则基线只理解示范模板，对任意自然语言数据的表现没有参考意义；真实智能体接入收到的始终是原文提示。

## 字段与语义

| 字段 | 含义 |
|---|---|
| schema_version | 固定 `1.0`，未知版本拒绝 |
| id / step.id / check.id | ASCII 字母数字、下划线、连字符；长度不超过 80；拒绝 CON/NUL 等平台保留名；案例/步骤/验证项在各自作用域内唯一 |
| dimension | retention/retrieval/update/disambiguation/boundary/reuse |
| synthetic | v1 必须为 true；禁存测试值也使用虚构标记 |
| steps[].kind | message（学习或干扰）、probe（回答）、task（执行任务）；适配器输入不包含此标签 |
| session | 相同值沿用对话会话，不同值切换会话；记忆仍保留 |
| day | 非负整数、按步骤不递减；模拟时间，非真实经过时间 |
| prompt | 用户可见原文；无隐含标准答案注入 |
| checks | 评测端判定条件；任何步骤都可检查，适合检查当步错误持久化 |
| source | response / memory / actions / artifact |
| op | equals / one_of / contains / excludes / exists / absent / json_subset |
| pointer | response/artifact 中严格 JSON 字段位置，采用 JSON Pointer 转义规则 |
| path | artifact 的 POSIX 相对路径，仅在案例目录中读取 |
| weight | 有限正数，默认为 1，布尔值无效 |
| failure | 失败归因类别；缺失或无效类别拒绝 |

memory 只允许 contains/excludes；actions 只允许 json_subset/absent。字符串匹配大小写敏感，无隐式模糊匹配或多余文本清洗。响应为 JSON 时，类型严格相等，`true` 不等于 `1`。

生成扩展实例：

```sh
python3 -m kylin_memory_bench generate --seed 42 --variants 100 --noise 15 --output expanded.jsonl
python3 -m kylin_memory_bench validate expanded.jsonl
```

种子和参数相同产生相同数据指纹。建议将新增任务模板单独命名，避免将不同版本的内容写入同一案例 ID。所有正式比较应固定数据集文件和 SHA256；筛选后的子集会产生不同指纹。`compare` 对数据指纹不一致的运行直接拒绝。


## 独立挑战集

`generate --suite challenge --seed 7331` 生成 12 个案例、27 项验证。每维两个独立任务：事件关联与否定约束；受众条件偏好与未知近似项；项目内修订与临时覆盖到期；同名实体与更名版本；不可信引用覆盖与选择性撤销；条件 JSON 文件和修订后的逐行产物。

挑战集不是标准集的随机编号扩容。它保留严格 JSON 与实际文件检查，避免引入不稳定的自由文本裁判；也不宣称涵盖任意同义改写。默认模型输入仍不包含检查条件。标准集与挑战集分别报告，不能用数据数量差异或存储可见性差异进行跨集排名。

`one_of` 接受 1–32 个显式列出的 JSON 标量答案，逐项严格比较类型和值，不做包含或模糊匹配。用于预先声明同一实体的合法别名。挑战集“松柏/松柏项目”的实测后标注订正单独保存，见 `examples/openkylin-challenge/score-review.json`；原始证据与分数保持不变。


## 0.2.1可选修订契约

旧案例、原始证据和旧分数保持原样。`generate --suite challenge-v21`生成独立修订集：精确文件字段、撤销归因和引文后续探针。新契约使用`grading_contract: "1.1"`；仍兼容外层schema_version 1.0，并额外报告判据来源域，不与旧数据混分。

- `json_keys`：response/artifact的完整JSON对象键集合须与value中的唯一字符串列表精确相同。
- `json_exact`：完整JSON对象、列表及标量类型和值匹配；对象键顺序不影响结果。文件始终使用严格JSON解析，重复键及代码围栏拒绝。
- `mismatch_values`：显式标量值与失败类别的映射；用于区分已撤销备注复用和合法公开编号混淆。不能给同一值重复登记冲突分类。
- `measurement_domain`：content、format、authorization、storage、artifact、actions。新契约分域指标另列；既有总分保留。
- `state_policy`：默认persistent；fresh_each_session让不同session进入不同HOME、工作区及原生状态目录。同一session内继续使用其状态。原生适配器必须有挂载命名空间包装器，先验证其他状态和评分端不可见。
- `steps[].output_tokens`：可选256..8192整数。V3.1学习1024、最终4096，使用per_turn_proxy_limits与回环费用代理执行共同额度。该标签不是答案，不携带checks或gold。

V3.1的内容封装评分是独立实验契约，支持唯一明确JSON答案块并单列外围格式。它不会回写本协议下的旧严格响应评分；完整JSON文件仍严格验证。[设计与范围](../experiments/math_memory/memory-v31-design.md)。
