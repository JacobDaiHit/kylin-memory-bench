# 参与 Kylin Memory Bench

项目地址：[JacobDaiHit/kylin-memory-bench](https://github.com/JacobDaiHit/kylin-memory-bench)。通过 [Issues](https://github.com/JacobDaiHit/kylin-memory-bench/issues) 报告问题或讨论方案，通过 Pull Request 提交实现。项目采用 MIT 许可证；提交的代码与文档应允许按该许可证分发。

## 有价值的贡献

- 新的真实任务与明确判据，尤其是相似项目、撤销、边界、文件复用和长任务链。
- 评分校准样例，展示合法别名、错误实体、部分证据、运行故障和输出合约的区别。
- 新原生智能体适配器，以及可核对来源、调用结果和完整性的工具轨迹解析。
- openKylin 用户空间中的安装、运行、离线复核验证；跨平台问题修复。
- 文档、无障碍展示、去敏后的可复现实验与维护说明。

## 开发与检查

使用 Python 3.9 及以上版本。核心运行和测试使用标准库；生成 PDF 等作者工具的依赖另行说明，不把它们加入核心 CLI 的运行依赖。

```sh
python -m unittest discover -s tests -v
python -m kylin_memory_bench validate kylin_memory_bench/data/sample.jsonl
python -m kylin_memory_bench validate kylin_memory_bench/data/challenges.jsonl
python -m kylin_memory_bench demo --output /tmp/kmb-contribution-demo
python -m kylin_memory_bench verify /tmp/kmb-contribution-demo
```

Windows 请为 `--output` 指定新的本地目录；现有结果目录不能被复用覆盖。离线 `demo` 是规则基线，不能当成真实模型实测。适配器、评分或证据采集逻辑变化需要相应行为测试；纯文档修改检查链接、术语和事实即可。

## 提交一个可审查的 PR

说明触发问题、预期行为、实际变化和验证方式。评分修改要展示此前误判与修复后的预期，并包含能区分错误答案和正确别名的反例。新数据应说明覆盖的能力、上下文条件、判据与已知局限，不仅报告条数。

接口或判分语义变化应写入 CHANGELOG，说明对既有结果的影响。历史实测目录、冻结源码和审计记录不得原地改写。标注订正采用单独的规则、订正记录和派生报告，保留原始成绩；新配置重新运行到独立目录。

## 报告实验与问题

报告版本或 commit、操作系统、Python、适配器与模型版本、案例 ID、轮次、run_id、错误状态和最小复现。提供去敏后的必要证据；`unknown`、执行故障和能力失败分开描述。不同题库与协议下的分数不能直接解释为总体能力排名。

不要提交 API key、私人 .env、账户余额、私人聊天、模型服务凭据或完整私人智能体工作区。先检查变更清单和公开附件；敏感细节不要贴到公开 Issue。一般缺陷使用公开 Issue；涉及凭据泄露时先撤销凭据并使用 GitHub 仓库提供的私密安全报告入口（仅在该入口可用时）。

项目尚无正式响应时限、独立第三方认证或已成立的评审委员会；维护状态以仓库实际 Issue、PR 与 Release 为准。
