# Kylin Memory Bench

面向 openKylin 的智能体长期记忆自动化评测工具。以真实运行证据为评分输入，覆盖长期保持、记忆调用、动态更新、相近区分、边界识别和任务复用六个维度。

**当前正式版本：0.2.0；工作树正在准备 0.2.1。** 交付包含可安装 CLI、36 例标准集、12 例独立挑战集、原生 OpenClaw/Hermes 适配器、确定性评分和离线证据检查器。真实实验在 openKylin 2.0 SP1 / WSL 2 上运行，两款智能体共同使用 DeepSeek Flash，各执行三轮；规则基线与早期 Ubuntu pilot 独立保存。系统身份和运行错误如实记录。

项目仓库：https://github.com/JacobDaiHit/kylin-memory-bench 。[技术方案与实测报告 PDF](output/pdf/KylinMemoryBench-technical-report.pdf) 随源码保存。

优先打开 [标准集实测报告](examples/openkylin-core/report.html) 与 [挑战集实测报告](examples/openkylin-challenge/reviewed-report.html)。完整交付包中的 START_HERE.md 提供接收入口，技术报告 PDF、固定源码快照与安装包随包附带。最终 3–5 分钟演示视频由提交者按 [录屏脚本](docs/demo-video.md) 录制。

0.2.1 新增材料：[离线导览](docs/presentation/index.html)、[数据说明卡](docs/dataset-card.md)、[修订验证记录](docs/revision-validation.md)、[数学V3.1修复与离线验收](docs/memory-revision-v31.md)。原难度试测未达到预定门槛；V3.1已补评分、状态对照和运行准备，尚未付费实测。最终安装包和视频尚未冻结，现有PDF与安装生命周期记录属于0.2.0。

新增 [Memory Stress 首期 30 条开发历史](docs/memory-stress-design.md) 与 [离线题目／证据导览](experiments/memory_stress/development-v1/index.html)：多跳关联、同字段更新各 15 条，五种状态／资料条件、反事实配对和三种表达。仅完成离线构造与软件检查，未调用付费模型，也未验证真实难度或产品区分度。

第二阶段新增 [Memory Stress 160 条离线历史](docs/memory-stress-phase2.md) 与 [V2 导览](experiments/memory_stress/v2/development-v2/index.html)：四题族、四档，128 条开发／32 条留出预留；集合授权、实际文件验收与独立完整任务链。首期原件保持不变，仍未调用付费模型；预留分组不是盲测，尚无模型难度或区分度结论。

首期审查修复已另存为 [0.1.1 修正版与六条小试清单](docs/memory-stress-phase2.md)：未知行动轨迹、nullable 输出格式和更新证据距离已修正；原 0.1 冻结材料保留。小试与 reader_only 只准备输入，尚未执行模型。

后续补齐 [答案唯一性、真实文件反馈与中断证据修复](docs/memory-stress-audit-fixes.md)：矛盾答案不计内容通过，已完成事件逐条保存；题目与答案不变，原评分来源归档，仍无新增模型实测。

2026-10-14 完成 [Luna 两小时校题与提交判断](docs/submission-readiness-20261014.md)：独立 8 条短历史、两款原生 Agent、一轮及 reader_only 对照，32 个案例全部结束，保留执行错误；新运行不与历史结果或原 128 会话题库混算。237 项离线测试通过，最终观测可离线复算。新校题门槛未通过，集合题存在读者筛选混杂；新增题库保留探索定位，不能据此发布排名。此前“未模型实测”的说明记录各阶段当时状态，新结果以上述独立报告为准。最终 0.2.1 包和视频仍待冻结。

## 一分钟运行

需要 Python 3.9+。核心运行没有第三方 Python 依赖，不需要 GPU、模型密钥或网络。

```sh
python3 -m kylin_memory_bench demo --output runs/demo
python3 -m kylin_memory_bench verify runs/demo
```

Windows 将 `python3` 换成版本满足要求的 `python` 或其完整路径（先执行 `--version` 确认）。双击 `runs/demo/report.html` 即可离线查看图表和筛选结果。每次使用新的输出目录；工具拒绝覆盖已有证据。

也可直接打开仓库中的 [样例报告](examples/sample-run/report.html)，查看 [样例指标](examples/sample-run/metrics.csv) 和 [逐项评分](examples/sample-run/scores.json)。

## 安装与一键复现

源码无需安装即可运行。可选安装到虚拟环境：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
kmb demo --output runs/installed-demo
```

源码安装的构建阶段需要 setuptools；离线且没有构建工具时，使用上面的 `python3 -m` 入口或 `.deb` 包。

从 GitHub 克隆后，可使用标准库脚本在本机构建 `.deb` 与源码 ZIP；无需调用模型：

```sh
python3 scripts/build_release.py
```

在 Debian/openKylin 系统安装生成的包：

```sh
sudo apt install ./dist/kylin-memory-bench_0.2.1_all.deb
kmb demo --output "$HOME/kmb-demo"
kmb verify "$HOME/kmb-demo"
```

完整复现（环境诊断、测试、三轮评测、证据校验）：

```sh
sh scripts/reproduce.sh runs/reproduce
```

Windows：`powershell -File scripts/reproduce.ps1 -Python python -Output runs/reproduce`。环境信息会记录到每次运行的 `manifest.json`，不会把 Ubuntu/Windows 标成 openKylin。

## 能做什么

- 36 个标准合成案例、108 项验证；六类场景各 6 个案例。另有 12 个独立挑战案例、27 项验证，覆盖条件偏好、临时覆盖、同名消歧与实际文件任务。
- 同一配置批量比较多个智能体，多轮独立重复；按维度或案例筛选；--jobs 1–16 按案例并发，案例内保持顺序。
- 对话回答、记忆快照、结构化行动、实际文件四类证据；逐项保留评分原因与证据编号。
- 严格结构化回答检查，避免“提到答案就算正确”；不需要另一个模型当裁判。
- `pass / fail / unknown / error` 四状态；输出已观测分、证据覆盖率、保守下界和乐观上界。
- 识别遗漏、混淆、旧记忆复用、错误持久化和错误任务复用；协议格式错误与运行错误单列。
- 通用 stdin/stdout JSON 适配器，以及 OpenClaw / Hermes 原生 CLI 接入实现。
- 离线 HTML 报告、六维 SVG 雷达图、CSV/JSON 导出；证据散列链和独立重评分。
- 无网络构建 `.deb` 和源码 ZIP；构建时间、文件顺序及权限固定，可验证重复构建散列一致。

## 常用命令

```sh
# 数据集验证与规模化生成
python3 -m kylin_memory_bench validate kylin_memory_bench/data/sample.jsonl
python3 -m kylin_memory_bench generate --suite challenge --seed 7331 --output challenge.jsonl
python3 -m kylin_memory_bench generate --seed 17 --variants 50 --noise 20 --output data-expanded.jsonl

# 指定配置、多轮批量评测
python3 -m kylin_memory_bench run --config kylin_memory_bench/data/baselines.json --output runs/batch --repeats 3 --jobs 4

# 仅测动态更新；默认仍使用内置样例数据
python3 -m kylin_memory_bench run --config kylin_memory_bench/data/baselines.json --dimension update --output runs/update

# 原证据独立重评分 / 报告重建 / 完整校验
python3 -m kylin_memory_bench score runs/batch
python3 -m kylin_memory_bench report runs/batch
python3 -m kylin_memory_bench verify runs/batch

# 比较相同数据集的多次运行；数据指纹不同会拒绝比较
python3 -m kylin_memory_bench compare runs/demo runs/batch --output runs/comparison

# 只读诊断与发布包构建
python3 -m kylin_memory_bench doctor
python3 scripts/build_release.py
```

退出码：`0` 命令成功（能力检查可能失败）；`2` 输入/完整性错误；`3` 评测有执行错误或缺少所配置程序；`130` 用户中断。`verify` 成功表示证据完整且评分可重放，不表示智能体满分。

## 接入真实智能体

复制 `configs/native-agents.example.json` 为 `configs/native-agents.local.json`，设置本机实际安装的 CLI、provider/model 和所需环境变量名。配置中 `REPLACE_*` 是有意要求填写的部署参数，示例不冒充现成模型服务。

```sh
python3 -m kylin_memory_bench doctor --config configs/native-agents.local.json
python3 -m kylin_memory_bench run --config configs/native-agents.local.json --output runs/native
```

请先阅读 [接入协议与适配器说明](docs/adapters.md)。工具为每案例创建新 HOME、智能体状态目录及会话；原生用户配置不会自动复制。认证通过显式 `env_allow` 传递，原有网关、聊天渠道和私人记忆不会用于样例。OpenClaw 2026.9.8 和 Hermes 提交 4b8a437 的固定运行时已在 openKylin 中复用，并调用 DeepSeek Flash 完成真实评测。WSL 环境不等同于裸机或完整登录管理器认证；详见 [实测说明](docs/live-experiments.md) 和 [系统证据](docs/evidence/openkylin-environment.json)。

## 输出目录

```text
run/
  manifest.json       环境、版本、配置/数据指纹、运行状态、证据链头
  config.json         已脱敏的配置快照
  dataset.jsonl       此次实际使用的数据集（含评分规则）
  evidence.jsonl      按步骤持久化的运行证据、耗时与散列链
  scores.json         六维指标、稳定性、错误分类、逐项原因
  metrics.csv         可用于横向比较的指标表
  report.html         可离线打开的交互筛选报告
  evidence.html       可离线搜索的逐步骤证据检查器
  radar.svg           可导出的矢量雷达图
  workspaces/         每系统/轮次/案例的独立运行产物
```

同一 seed 的数据相同；同一证据的分数相同；真实模型可能随机，使用重复实验衡量波动。运行 ID、真实耗时和时间戳故意保持真实，不承诺运行目录字节相同。

## 方案、复现与验收材料

- [完整评测方案](docs/design.md)：目标、前提、数据设计、证据收集、公式、偏差和局限。
- [数学研究记忆真实试测](docs/math-memory-pilot-report.md)：付费可行性结果、失败分类与测量边界，尚未达到正式推进条件。
- [研究档案记忆V3设计](experiments/math_memory/memory-v3-design.md)：只测跨会话记录恢复与管理；[离线实例](experiments/math_memory/memory-v3/index.html)、[真实付费结果](docs/research-memory-v3-report.md)。已完成小试测，充分难度尚未验证。
- [研究档案记忆V3.1](experiments/math_memory/memory-v31-design.md)：唯一明确答案块的内容评分、无持久状态消融、三家族配平及分阶段健康检查；[离线实例](experiments/math_memory/memory-v31/index.html)，本版未付费实测。
- [数据格式](docs/dataset.md)、[JSON Schema](schemas/dataset.schema.json)、[适配器协议](docs/adapters.md)。
- [openKylin 部署与验收](docs/openkylin.md)、[3–5 分钟录屏脚本](docs/demo-video.md)。
- [交付要求逐项对应](docs/acceptance.md)、[本地验证记录](docs/validation.md)。

## 开发

```sh
python3 -m unittest discover -s tests -v
```

Windows运行包含历史数学脚本的完整测试时，使用 `python -X utf8 -m unittest discover -s tests -v`；CI采用相同UTF-8模式。当前V3.1工具显式按UTF-8读写文件。

测试使用标准库 `unittest`。CI 配置覆盖 Linux/Windows 与 Python 3.9/3.12；CI 工作流文件已提供，本地验证不能等同于远程 CI 已运行。MIT 许可证；原始赛题 PDF 不在发布包中重新分发。

挑战集的公开标注订正：统一接受“松柏”和“松柏项目”，六个等价答案误判得到修正。原始结果仍保留，详见 `examples/openkylin-challenge/score-review.json`，可用 `python3 scripts/review_challenge.py --check` 复算。

公共仓库保留可复核的原始 benchmark 证据；API 审计的私人账户余额数值已移除，详情见 [实验说明](docs/live-experiments.md)。密钥、私人配置、原生智能体工作区和开发临时文件均不随仓库上传。

ChatGPT 套餐接入的独立授权／模型检查工具：见 [WSL 操作指南](docs/chatgpt-plan-setup.md)。尚未完成原生双 Agent 对接，不属于已完成实测。
