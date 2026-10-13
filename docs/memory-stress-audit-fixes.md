# Memory Stress：答案唯一性、真实反馈与中断证据修复

本次针对 **a7f4d496ead18875eb83d6c800c56238f2d5c6d0** 的三处离线复现进行修复。任务协议仍为 0.1.1／0.2，题目、答案、种子、案例 ID、原生输入和预选六条清单不变；不新增题族，不调用模型。

## 内容评分：先确认只有一个答案候选

新 Stress 评分器增加唯一性检查，保留“普通说明文字 + 唯一 JSON 围栏”的内容宽容处理。围栏外另有明确 JSON answer 键或未完成的答案键／值修正时，不挑选围栏内的正确候选，记为 unknown、parse_error_code=ambiguous_answer。未知项留在计划分母，格式仍单独记录为失败。

检查也识别 JSON 转义形式的 answer 键。两个相同答案块同样不符合唯一候选约定；这里不通过选择一个答案来提高成绩，也不尝试推断任意自然语言修正的语义。

| 输出情况 | 修复前内容 | 修复后内容 | 格式 |
| --- | --- | --- | --- |
| 普通说明 + 唯一正确 JSON 围栏 | 通过 | 通过 | 失败 |
| 错误裸 JSON + 正确围栏 | 通过 | 未知／歧义 | 失败 |
| 正确围栏 + 错误裸 JSON | 通过 | 未知／歧义 | 失败 |
| 正确围栏 + 截断的 answer 修正 | 通过 | 未知／歧义 | 失败 |
| 唯一、合规、正确 JSON | 通过 | 通过 | 通过 |

实现标签为 **stress-content-unique-answer-1**，每条评分及分析结果携带该标签，分析另存评分源码指纹。数学 V3.1 的历史实现及其冻结材料保留；当前 Stress 在调用旧解析器前完成唯一性检查，不回写旧数学或旧 Stress 分数。

## 完整任务链：把文件失败真正交给下一轮

每次实际验收保存两层观察：组件规则与所选参数检查，以及实际文件验收。selected_values 表示回答选择的方案；submitted_artifact 表示文件快照。参数全对但缺文件时，组件可为 accepted，整体文件结果仍为 rejected／missing_file。

下一轮提示保留原始组件反馈，并添加 **DELIVERY_FEEDBACK**，包含实际文件的存在性、内容快照、验收结果、失败原因与工具要求的路径。非法 JSON、格式不符、内容不符和文件不可观测也如实转发。原始工具判据保留，额外的诊断标签不替换原始结果。

只读校验器从实际文件快照重新验收，并核对保存的反馈和下一轮收到的反馈。即使重算散列链，错误转发的诊断也会被拒绝。该检查不等同于来源签名或原生隔离证明。

## 完整任务链：每个事件持久化后再发下一次请求

开始运行即创建证据文件和运行清单。每次任务结果及反馈投递完成后，追加一个散列事件，flush／fsync，再更新原子清单，最后才发起后续请求。清单记录正在执行的请求；正常结束、执行错误和可捕获中断分别标记。

KeyboardInterrupt／SystemExit 保留已完成事件，状态为 interrupted，完整链成功为 false；异常继续向调用方传播。进程直接退出绕过 finally 时，已 fsync 的事件和上一个 running 清单仍保留，未执行阶段为未知，不通过自动重跑补齐。

只读校验区分完整成功、仍运行／中断的有效前缀、清单尚未更新的事件和最后一个截断行。未完成状态不会变成完整成功；损坏的完整事件仍被拒绝。这里验证进程中断下的证据保存，不宣称覆盖所有断电或存储硬件故障。

## 验收与兼容

[最新离线验收记录](evidence/memory-stress-audit-fixes-validation.json)保存前后对照、测试与软件任务链结果。回归包括普通说明与唯一答案、多个／截断答案、计划分母、四种文件故障后修正、任务与反馈投递中断、子进程强制退出、截断前缀及重散列后的错误诊断。

用户提供的 sandbox 下载链接不在当前工作区，因此没有声称执行该外部脚本；这些等价场景已经进入仓库测试。复核命令：

    python3 -X utf8 -m unittest discover -s tests -p test_memory_stress_v2.py
    python3 -X utf8 -m experiments.memory_stress.v2 verify-prepared experiments/memory_stress/v2/development-v2
    python3 -X utf8 -m experiments.memory_stress.v2 chain-smoke --output runs/stress-chain-audit

修复前源码、原冻结协议及原离线验收以精确字节保存在 [a7f4d49 源码归档](../experiments/memory_stress/source-archives/a7f4d49-before-audit-fixes.zip)，[逐文件 SHA256](evidence/memory-stress-a7-source-archive.json)可独立核对。当前冻结文件只更新执行／评分来源及相关元数据指纹；原输入和答案不变。前次验收的旧协议 SHA256 对应归档中的原协议，旧验收记录不回写。

本次仍是离线软件修复，没有真实 Agent 难度、区分度或原生记忆健康成绩，也没有全量或完整链的付费授权。
