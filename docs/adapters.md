# 适配器协议与真实智能体接入

## 通用 JSON 进程协议

`kind: command` 每步启动一次配置中的 argv 程序，以 stdin 发送一个 UTF-8 JSON 对象，stdout 只接受一个 JSON 响应。执行使用 `shell=False`；`{python}` 替换当前 Python 可执行文件，`{workspace}` 替换案例目录。其他字符串原样传递，不做 shell 展开。脚本路径应使用绝对路径，因为工作目录是案例工作目录。

请求格式：

```json
{"protocol_version":"1.0","session_id":"uuid","day":7,"prompt":"用户原文","workspace":"/absolute/case/workspace"}
```

响应格式：

```json
{
  "text":"{\"answer\":\"Markdown\"}",
  "memory":{"text":"长期记忆内容","complete":true,"scope":"完整长期存储"},
  "actions":[{"name":"write_file","arguments":{"path":"deliverables/summary.md"},"success":true}],
  "usage":{"input_tokens":100,"output_tokens":20},
  "provenance":"your-agent-bridge"
}
```

`text` 必需。不可观测的 `memory` 或 `actions` 省略或设为 null，不能用空字符串/空列表伪装成“已确认没有内容”。`complete:true` 是桥接实现对快照覆盖范围的声明：只有真正覆盖当前所评测的整个长期记忆存储时才能声明；外部数据库、插件存储等未覆盖时应为 false。评测器不能独立证明桥接声明诚实。

进程之间的长期状态放入当前 workspace；同一 session_id 的聊天上下文由桥接器自行管理，session_id 变化必须启动新的对话上下文并保留长期记忆。评测器不会帮桥接器把全部历史提示重新塞进上下文，也不向它发送 gold/checks。

进程非零退出、超时、输出超 2 MiB 或 JSON 不合约均记录为 execution_error。stderr 不进入公开报告，仅记其散列，避免错误消息带出认证内容；调试原生程序应在独立测试环境直接执行相同 CLI。Linux 超时终止所属进程组；Windows 当前终止直接子进程，对自行脱离的子孙进程不提供完整隔离保证。

`examples/protocol_agent.py` 是可运行、明确标注为无记忆的协议例子。复制 `configs/command.example.json`，把脚本绝对路径填入，再执行 `kmb run`。用于 KylinBot / kylin-agent 等其他框架时，将它们的真实会话、存储与工具事件接到该协议即可；本版不声称已存在这些框架的原生绑定。

## 环境与隔离

每个案例有独立 `.home`；`HOME/USERPROFILE/XDG_*` 定向到该目录。只继承启动所需的少量系统变量，以及 `env_allow` 中显式列出的变量。认证变量的值不在报告配置中展开，已知密钥值会在保存的事件中替换为 `[REDACTED]`。不要在 `command` 参数或 `native_config` 中写明文密钥；适配器私有工作目录中的原生配置/日志并不提供通用秘密清洗，公开提交时使用已检查的证据文件，不要盲目上传整个原生 workspace。

目录隔离防止意外串扰，不是 OS 沙箱。原生智能体有主机进程权限，正式比赛需要独立 VM/容器和最小挂载；测试只提供合成事实及案例内部相对产物路径。工具不启用 `--yolo`、不启动对外聊天渠道、不使用 `--deliver`。

## OpenClaw

配置 `kind: openclaw`，为每案例设置独立 `OPENCLAW_HOME`、`OPENCLAW_STATE_DIR`、`OPENCLAW_CONFIG_PATH` 和 workspace。在新状态中生成最小原生配置，设置 `agents.defaults.workspace` 与可选 model；不复制现有用户记忆或 auth profiles。认证使用显式允许的 provider 环境变量。

调用原生 CLI 的 `agent --local --session-id ... --message-file ... --json`。同案例同 session 使用固定 UUID；新 session 生成不同 UUID。解析 `final` 或 `payloads[].text`，并兼容包在 `result` 里的响应对象；检测协议级失败。官方 CLI 的 JSON 结构可能随版本改变，应以安装版本 `openclaw --version` 和 `openclaw agent --help` 核对。

默认只收集 workspace 中 `MEMORY.md`、`USER.md`、`memory/**/*.md`，`memory_complete` 默认为 false。CLI 的 `toolSummary` 只是汇总计数。0.2.0 从每案例私有 SQLite 的 transcript_events 读取本会话本步骤新增行，配对 toolCall/toolResult，保留序号和行散列；支持通过系统 libzstd 有界解压。失败工具调用不能满足成功行动检查；缺失库、版本不兼容或不完整轨迹均保留 unknown。原生名称、参数与结果不丢失，再规范化为统一行动对象。`--local` 的可选后台整理行为和网关模式可能不同，本配置测试的是该显式执行模式；不能将结果推广为网关长期运行的效果。

接口依据：[OpenClaw Agent CLI](https://docs.openclaw.ai/cli/agent)、[环境变量](https://docs.openclaw.ai/help/environment)、[记忆存储](https://docs.openclaw.ai/concepts/memory)。文档核对日期：2026-10-03。固定版本已在 openKylin 2.0 SP1 / WSL 2 实际运行；结果、版本和配置见 live-experiments.md。

## Hermes

配置 `kind: hermes`，为每案例设置独立 `HERMES_HOME`。将 `native_config` 以 JSON（YAML 子集）写入该目录的 `config.yaml`。调用 `hermes chat --query-file ... --format stream-json`；同一逻辑会话后续步骤使用返回的 session_id 加 `--resume`，逻辑会话变化时不 resume。

解析一个成功的终止 `result` 事件，要求 `exit_code:0`、有效 session_id 和 text。`tool_use` 事件保留为 actions，`input` 映射为 arguments。默认快照 `.hermes/memories/*.md`；外部 memory provider 未覆盖，所以默认 `memory_complete:false`。

接口依据：[Hermes CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands/)、[文件位置](https://hermes-agent.nousresearch.com/docs/user-guide/which-file-does-what)、[Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/)。文档核对日期：2026-10-03。固定版本已在 openKylin 2.0 SP1 / WSL 2 实际运行；结果、版本和配置见 live-experiments.md。

## 实测前固定实验配置

1. 固定两个智能体的已安装版本、模型 ID、provider、推理参数、记忆插件及工具权限。将无敏感信息的版本记录随实验提交。
2. 从默认 36 案例选择一个案例试跑，确认真实会话边界和记忆路径。保留 protocol errors，不手工补齐模型回答或记忆。
3. 对所有系统使用同一数据指纹、相同重复次数和相同文件任务能力。不能为了某系统分数更好而独立调整检查权重。
4. 正式跑三轮；保留失败、超时、unknown 和完整度声明。比较分数时同时报告覆盖率；原生 CLI 可见性不同可能使上下界区间不同。

此处模型/provider 占位符是必须由部署者提供的环境参数。没有真实模型服务时使用 `demo` 验证基础设施，不运行占位配置并把失败包装成真实能力结果。


## 真实联调与依赖复用（0.2.0）

实测启动器、固定模型与预算代理见 [真实实验说明](live-experiments.md)。OpenClaw/Hermes 的私有 HOME 和状态目录以 0700 创建；WSL 输出使用 Linux 文件系统。

Hermes 允许可选 `dependency_home`，指向已有安装时的 HERMES_HOME。该目录必须含 `installs/`、`tools/`。适配器为每案例保留独立 `.hermes`，仅链接依赖代际目录，设置 HERMES_RUNTIME_DIR 并禁用运行中自动安装。依赖目录由配置者明确指定和信任；认证、记忆、配置、会话不复制、不链接。未提供该字段时保留已有行为。

OpenClaw 2026.9.8 的数据库轨迹格式按本次固定版本实现；其他版本若改变表结构，评测器应显式保留不可观测状态。交付源码对异常轨迹的拒绝检查比冻结实测版本更严格；真实实验使用的完整源码已独立归档，原始记录没有被重写。
