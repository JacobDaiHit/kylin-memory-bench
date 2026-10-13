# 0.2.1／数学V3.1修订记录

本轮按授权修复代码、数据契约与运行准备，**未调用付费模型**。真实难度验证仍未通过；本轮软件验收不是能力排名、原生记忆健康或最终提交就绪证明。

## 评分与实例

新增[版本化挑战集](../kylin_memory_bench/data/challenges-v21.jsonl)，原`challenges.jsonl`、原始实测、别名订正及旧分数保留。

- JSON文件新增精确字段集合检查；严格JSON仍拒绝重复键和Markdown围栏。`json_exact`比较完整对象并保留标量类型，字段顺序无关。
- 选择性撤销区分禁止备注复用、公开编号字段混淆和正确null；最终整份回答中的禁止值泄露单独检查。
- 引文注入增加两个后续引用／使用探针。部分快照、未检索到恶意值和保存不可信引文都不能证明全局未存储或恶意事实已被采纳。
- 新契约暴露content、format、authorization、artifact、actions等指标；旧数据的score结构和计算保持兼容。

新增[16条预先声明的固定样例](evidence/scoring-revision-fixtures.jsonl)及[校准报告](evidence/scoring-revision/report.html)。它们覆盖五条文件、四条撤销、五条响应封装、两条引文行为场景。预期标签和理由先写定；这些是AI辅助的契约样例，没有独立人审，不代替难度验证。

原30条＋4组校准保留；当前源码对应的[重新复算报告](evidence/scoring-calibration-v31/report.html)与[旧评分器对照](evidence/scoring-version-comparison-v31.json)独立保存，不覆盖之前记录。

## 数学记忆与状态对照

[V3.1设计](../experiments/math_memory/memory-v31-design.md)和[交互实例](../experiments/math_memory/memory-v31/index.html)仅恢复登记事实。修订了不带revision补丁的含义，并将唯一明确答案块的内容与外围格式分开判断；18项分母保持不变。多候选、重复键和截断保持未知，不事后挑答案。

新增无持久状态组，与记忆组收到相同历史和问题。每个新会话采用新HOME、工作区和原生状态目录；同一会话内保留连续状态。原生配置必须配合同一版本的挂载/PID隔离包装器；否则在模型调用前拒绝。它是跨会话状态可用性消融，不是原生记忆模块的纯开关实验。

binding、updates、scope三组低高实例配平历史会话数和UTF-8字节；公开中性填充及其局限。实际Token和工具注入量不能由字节数代替。合成家族、模板变体和不同条件不包装为独立研究问题。

scope改为三个独立项目的指定引用恢复，保留18项分母；预设忽略版本策略可造成三项bound错误，检查判据稀释问题。这个离线策略对照不作为真实模型难度效应。

## 执行与保护

回环代理按数据中声明的学习1024／最终4096上限统一处理两系统请求。余额按短周期核查，不在每次模型结果返回前同步查询；失效核查失败会停止新的提供方调用，防止并发重复排队查询。累计上界、整段保守费用、在途预留及原有余额底线同时限制调用。失败或缺失／非法usage保留预留；有效调用原文不因余额查询故障丢失。

转发仍是缓存上游完整结果后生成SSE，尚不能称为上游实时流式传输。超时、限流、断流、余额故障、并行预留、非法usage和输出额度使用本地模拟与故障注入检验；客户端内部恢复仍由原生实现决定，不把重试当独立样本。

原V3转发的两个源版本已归档，见[历史源指纹映射](evidence/historical-source-archives.json)。原V3生成器、主评分、运行器准备协议和隔离脚本不回写。

## 离线验收与后续入口

[机器验收记录](evidence/memory-revision-v31-validation.json)记录测试、冻结材料、历史复核、公开范围和无新增费用检查。[openKylin原生离线检查](evidence/research-v31-native-offline.json)仅验证隔离、CLI启动、解码及真正生效的输出额度：提供方请求方法被本地stub覆盖，provider网络调用为0，不能据此宣布原生记忆健康。

该机器验收记录对应提交`a92f17a`的离线快照。后续[CI兼容性修订记录](evidence/ci-compatibility-20261013.json)处理Windows默认编码及Python 3.9目录名尾斜杠问题：当前V3.1工具显式使用UTF-8，历史冻结脚本在UTF-8模式下运行；新回归还主动关闭UTF-8默认模式验证当前工具。准备材料重新核对源码指纹，题目、答案、输入、参考结果和历史实测保持原件。

```sh
python3 -m unittest discover -s tests -q
python3 scripts/calibrate_revision.py --check --output docs/evidence/scoring-revision
python3 scripts/calibrate_scoring.py --check docs/evidence/scoring-calibration-v31
python3 scripts/compare_scoring_versions.py --check docs/evidence/scoring-version-comparison-v31.json
python3 -m kylin_memory_bench validate kylin_memory_bench/data/challenges-v21.jsonl
```

健康、小试、正式三轮的题目、标准答案和准备协议已经离线生成；均标记prepared_not_executed。下一阶段的真实健康、完整记录18/18、有效观测至少90%和三家族难度效应门槛见V3.1设计。本轮不生成新的真实成绩，不冻结视频或发布最终Release。
