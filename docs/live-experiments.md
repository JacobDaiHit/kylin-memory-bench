# DeepSeek 真实智能体实验

本流程复用已有 Linux / WSL 环境、已安装的 OpenClaw/Hermes，以及用户提供的模型服务。无需桌面虚拟机即可执行真实智能体联调。若运行系统不是 openKylin，结果中的 `is_openkylin` 必须为 false，不能把它作为 openKylin 桌面终验证据。

## 最终 openKylin 双系统实验（0.2.0）

完整结果由 [results.md](results.md) 从已经通过 verify 的原始证据生成：

- 标准集：36 案例、每系统三轮，1,008 个步骤、648 个验证项判断。
- 独立挑战集：12 案例、每系统三轮；规模与结果以其 manifest 和报告为准。
- 固定 OpenClaw 2026.9.8 (fc23bc8)、Hermes 提交 4b8a43719b2a259cea88a72f9f13a2b6962e7ac3，同一 deepseek-flash 服务。
- 实际系统为 openKylin 2.0 SP1 / WSL 2，Python 3.12.2；不是将 Ubuntu 的 OS 标识改写成 openKylin。
- 标准集采用 jobs=4、双方 timeout=180 秒。观察到网络请求失败和队列等待引起的超时风险后，挑战集预先固定为 jobs=2、双方 timeout=600 秒。保留标准集原始错误，不重跑覆盖。
- 两套实验使用同一冻结实现，源码及实现指纹见 reproducibility。报告呈现可以改进，原始回答、manifest 和 scores.json 保留。
- 标准集以累计 10 CNY 保护上限启动；挑战集仍使用同一账本，将整个项目的累计上限设为 12 CNY。这是累计额度，不是每套各 12 CNY。低于用户提供的账户可用余额，不清零已使用或预留的费用。

API 审计中的 start/finished、usage 和网络拒绝记录均随实际结果保存。不同并发与超时意味着不能比较两套数据集的延迟。标准集含 19 个执行错误事件，其中 6 个原始步骤失败、13 个后续步骤跳过；失败、未知和能力错误分别报告。

### 复现完整实验

先在公开示例配置中填写本机实际安装路径，复制为受忽略规则保护的 .local.json。两个智能体使用相同模型与输出参数；工具策略各按原生配置固定（Hermes file/memory，max_turns=6；OpenClaw 允许 read/write/edit/memory_search/memory_get）；标准配置双方 timeout=180，挑战配置双方 timeout=600。建议在已准备的 openKylin Linux 文件系统内运行：

```sh
# 标准集；源数据可使用归档内 core.jsonl
python3 scripts/live_deepseek.py \
  --env-file /path/to/authorized.env --key-name DEEPSEEK_API_KEY \
  --config configs/core.local.json --dataset kylin_memory_bench/data/sample.jsonl \
  --output "$HOME/kmb-runs/core-3trials" --repeats 3 --jobs 4 \
  --audit runs/core/api-audit.jsonl --ledger runs/shared-budget.local.json \
  --budget-cny 10 --request-limit 2700

# 挑战集；等待上一个进程结束后使用同一账本
python3 scripts/live_deepseek.py \
  --env-file /path/to/authorized.env --key-name DEEPSEEK_API_KEY \
  --config configs/challenge.local.json --dataset kylin_memory_bench/data/challenges.jsonl \
  --output "$HOME/kmb-runs/challenge-3trials" --repeats 3 --jobs 2 \
  --audit runs/challenge/api-audit.jsonl --ledger runs/shared-budget.local.json \
  --budget-cny 12 --request-limit 900
```

新运行会付费；接收者只复核已有结果时运行 verify 即可，无需凭据。运行有执行错误时会使用非零退出码，原始数据仍保存，不应删除该目录或用一次成功的单案例重跑替换它。

## 历史 Ubuntu pilot（不计入最终成绩）



结果位于 `examples/live-run/report.html`。原始运行 ID：`12d24f12-b194-4681-a5e7-5a10594a062d`。系统为 Ubuntu 26.04 LTS / WSL2 x86_64，Python 3.14.4；manifest 如实记录 `is_openkylin:false`。

- 选择六个维度各一例，两个智能体各执行 28 步，共 56 个事件、36 次验证项判断；1 轮实验，执行错误为 0。
- 原生进程 OpenClaw 2026.9.8 (fc23bc8)，Hermes 固定提交 `4b8a43719b2a259cea88a72f9f13a2b6962e7ac3`，共同调用 DeepSeek Flash。
- 运行耗时约 9 分 50 秒。完成 131 次真实模型请求，API 审计没有 rejected 事件。Token 用量和环境细节见 `experiment.json`。
- 两个系统都实际创建了历史约定路径下的文件，路径、UTF-8 内容和 SHA256 随最后一个 evidence 事件保存。

| 系统 | 通过 | 能力失败 | 未知 | 执行错误 | 六维宏平均证据覆盖率 | 得分下界–上界 |
|---|---:|---:|---:|---:|---:|---:|
| OpenClaw | 14 | 0 | 4 | 0 | 81.94% | 81.94%–100% |
| Hermes | 15 | 0 | 3 | 0 | 87.50% | 87.50%–100% |

两者在已观察检查项上的得分都是 100%，不代表完整能力均为 100%。覆盖率为维度宏平均，不能用通过项数除以总项数替代。三个共同未知项来自记忆删除/临时信息未持久化：局部文件中没有找到内容，不足以证明所有存储中都不存在。OpenClaw 另缺逐条结构化工具行动轨迹；文件本身已验证，但 action-trace 仍为 unknown。Hermes 提供了原生 write_file 事件，因此该项有证据。

六维 pilot 与前置 API 探针共用累计费用账本。私人账户余额数值仅保留于本地原始记录，不随公共仓库发布；余额差不能当成精确独立账单。本轮范围为 6/36 个案例、单次重复，尚未完成完整 36 案例 × 两款智能体 × 3 轮实验，不计算重复稳定性，也不声称智能体排名。

原生 pilot 的 manifest 保留当时的 0.1.0 开发版本及实现指纹；修复整理后发布为 0.1.1，未修改原始实验记录。新版本的 verify 可独立重算并验证该证据。

## 实验设置

- 两个实际 CLI，共用 `deepseek-flash`，通过官方 `https://api.deepseek.com` 请求推理。
- 固定非思考模式、temperature=0、每次请求最多 2,048 输出 tokens。代理会记录这些控制项；它们是本次实验设置，不代表两个产品的默认表现。
- OpenClaw：只开放工作区内的 read/write/edit 和 memory_search/memory_get，关闭首次身份引导；不接聊天渠道、不开放执行终端。
- Hermes：只开放 file 和 memory 工具集，最多 6 次工具循环；关闭自动会话标题和技能维护，不开启浏览器或桌面控制。
- 每个案例的 HOME、记忆与会话彼此独立；新会话不传旧对话，只能依靠智能体自己的持久记忆。
- 7/30/90 天为提示中明确标注的模拟天数。本实验没有实际等待相应时间，不验证真实 TTL。
- 本地预算代理会缓冲上游非流式结果，再为需要流式接口的客户端输出 SSE。因此延迟含 CLI 启动、工具执行、预算检查和传输开销，不是模型裸推理速度。
- 默认记忆快照是部分可见范围。无法证明删除或不曾持久化的检查保留 unknown；不为提高覆盖率强行标记完整。

## 复用安装依赖

核心评测器沿用现有 Python 3.9+，无需第三方库。OpenClaw/Hermes 的运行时要求以固定安装版本为准；两者使用各自官方启动器。

OpenClaw 对状态目录有私有权限要求。WSL 下把 `--output` 放到 Linux 文件系统，如 `$HOME/kmb-runs/...`；某些 `/mnt/c`、`/mnt/d` 挂载设置无法表达所需权限，首次本机实测已遇到该问题。报告和证据可以事后复制到 Windows 项目目录。

新版 Hermes 的依赖代际存放在安装时 HERMES_HOME 的 `installs/` 下。配置可选 `dependency_home` 指向已安装依赖的 home；适配器仅把 `installs/` 链接给案例目录，复用 `tools/`，禁用自动安装。记忆、配置、会话与认证文件均不共享。此方式在 Linux 验证，Windows 需要符号链接权限。该链接是依赖复用机制，不是安全沙箱。

## 凭据与预算

先复制 `configs/deepseek-live.example.json` 为忽略提交的 `.local.json`，把 executable 与 dependency_home 改成已有安装的实际路径。`KMB_PROXY_BASE_URL` 由启动脚本填入。模型凭据只由预算代理从用户明确指定的 `.env` 读取，作为数据解析，绝不 source/执行该文件。智能体只收到短期本机代理令牌。

```sh
# 只验证模型工具调用往返，不作为智能体评测成绩
python3 scripts/live_deepseek.py \
  --env-file /path/to/authorized.env --key-name DEEPSEEK_API_KEY \
  --audit runs/api-probe/audit.jsonl --probe

# 六维代表案例：每个维度各一例，1 轮，仅用来联调
python3 scripts/live_deepseek.py \
  --env-file /path/to/authorized.env --key-name DEEPSEEK_API_KEY \
  --config configs/deepseek-live.local.json \
  --output "$HOME/kmb-runs/six-dimensions" \
  --audit runs/six-dimensions/audit.jsonl --request-limit 160 \
  --case retention-001-224906 --case retrieval-001-224906 \
  --case update-001-224906 --case disambiguation-001-224906 \
  --case boundary-001-224906 --case reuse-001-224906

python3 -m kylin_memory_bench verify "$HOME/kmb-runs/six-dimensions"
```

默认预算上限为 10 CNY。`runs/deepseek-budget.local.json` 保存首次余额和累计保守费用估计；连续实验使用同一个账本，不删除或重置。每次付费调用之前都会查询余额、检查请求次数和单次费用预留；网络失败时保留已预留的额度。预算同时受余额下限和累计费用估计约束。不同进程通过操作系统文件锁防止并发覆盖账本；不要用不同账本并行消费同一个账户。

费用估计采用 2026-10-03 查到的 Flash 高峰单价：每百万 cache miss 输入 2 元、cache hit 输入 0.04 元、输出 8 元。保守预留按请求 UTF-8 字节数加协议余量计输入，实际成功后按返回 usage 修正；若价格变化必须先更新上限。账号余额有分位精度、可能延迟更新，且账户其他调用也会影响余额，余额差不是本实验的精确独立账单。

完整数据集为 36 案例，每款智能体每轮 168 个评测步骤。去掉 `--case` 并用 `--repeats 3` 可以跑完整三轮，但应先检查代表案例无执行错误、评测配置已经固定，再按费用和请求额度执行。达到预算上限会停止发送付费请求，后续执行错误必须如实保留。

## 保存和审查

保留每次运行的 dataset/config/manifest/evidence/scores/metrics/report/radar 以及对应 audit。账本、真实模型 key、原生私有工作目录不进入公开交付包。导出时只选需要的证据文件；原生工作区可能保存工具上下文和内部日志，应单独审查。

审阅结果先看 execution_errors 与 coverage，再看得分。成功跑通不意味着所有记忆能力检查通过；能力失败是有效实验结果。单个六维代表案例集仅能说明流程可用，不能作为统计稳健的智能体排名。

## 官方依据

- [DeepSeek 当前模型与价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [DeepSeek 余额接口](https://api-docs.deepseek.com/api/get-user-balance/)
- [OpenClaw 自定义模型服务](https://docs.openclaw.ai/gateway/config-tools/custom-providers)
- [Hermes 模型服务](https://hermes-agent.nousresearch.com/docs/integrations/providers)

本实验使用服务模型列表核对的 `deepseek-flash`，不修改来源项目的 .env。

## 交付版代理的可靠性修复

标准集冻结代理累计计数增加 2242 次上游返回，但写入 2237 个 completion 审计事件。5 个差额与“先更新计数、再查余额、最后写审计”的旧顺序有关；余额查询失败时会遗漏该次审计，并向智能体报错。详见 evidence/core-api-accounting.json。交付源码调整为先保存费用和审计、再刷新余额；后置查询失败保留已付费回答，下一次付费调用仍须成功通过前置余额检查。余额查询使用 10 秒时限，模型请求仍为 150 秒。该修复有离线故障注入测试，未暗改冻结实验或用新结果替代旧错误。

## 最终费用快照与订正

2026-10-03 07:51 UTC 完成最后一次只读余额查询，未发起模型付费请求。保守累计费用估算为 11.59562904 CNY，保护上限为 12 CNY；估算并非实际账单。账户余额原值与详细快照仅保留在本地，不随公共仓库发布。

挑战集已完成全部三轮，共 258 个事件，含一次真实执行失败与一次后续跳过。等价答案标注问题统一订正，对原始证据另行重算，不覆盖原始结果。对应原始与订正报告、说明、判分差异及离线复算脚本均随交付保存。

## 公共仓库审计字段处理

GitHub 版本的 API 审计和实验元数据将私人账户余额字段替换为 `[PRIVATE ACCOUNT VALUE]`。请求计数、token 用量、预算保护动作、错误原因和时间戳保留。原始 benchmark 的 manifest、数据、对话证据及评分均未改写；本地原始审计备份保留在被忽略的临时目录中。
