# 用 ChatGPT 登录验证 GPT-5.6-Luna 接入

这是仓库新增的**授权与可用性检测工具**，尚不是 OpenClaw／Hermes 的模型代理，也不是一次记忆 benchmark。它依据官方 Sign in with ChatGPT 文档实现独立授权，不读取或复制 Codex 的登录文件。已做离线模拟验证，真实账户授权、模型权限和推理仍待用户操作确认。

你不需要购买或复制 API 密钥，需要在官方浏览器页面授权本项目使用 ChatGPT 套餐。登录 Codex 不会自动完成此授权。模型固定检查 `gpt-5.6-luna`，不会替换为 GPT-6 或其他型号。

## 1. 打开当前电脑的 WSL 终端

Windows Terminal 中打开 Ubuntu／正在使用的 WSL 发行版。下面命令在 Linux 终端输入，不在 Windows PowerShell 中直接执行。

```bash
cd /mnt/d/github/openkylin
python3 --version
mkdir -p tmp
python3 -m venv tmp/chatgpt-plan-venv
tmp/chatgpt-plan-venv/bin/python -m pip install -r scripts/chatgpt-plan-requirements.txt
```

使用独立虚拟环境，核心 benchmark 仍无第三方运行依赖。如果创建 venv 提示缺少 ensurepip，需要先安装该发行版相应的 Python venv 包，再重试。

## 2. 在浏览器授权

```bash
tmp/chatgpt-plan-venv/bin/python scripts/chatgpt_plan.py login --no-browser
```

终端打印官方 `https://auth.openai.com/…` 登录链接。复制到这台 Windows 电脑的浏览器打开，保持终端运行：

1. 登录你使用 Codex 的 ChatGPT 账号。
2. 选择正确的工作区，核对应用名称为 **Kylin Memory Bench**。
3. 按官方页面确认是否允许应用使用 ChatGPT 套餐；仅完成身份登录不代表授予推理权限。
4. 授权后浏览器返回 `http://127.0.0.1:1455/auth/callback`。
5. 回到终端；只有出现 `Authorized. Credentials saved outside the repository. Next: models` 才说明令牌和身份校验通过。浏览器显示收到回调尚不是最终成功。

登录等待五分钟。链接和回调是本次尝试专用，过期后重新运行命令，不必手动复制回调码。

端口已被占用时可以改用：

```bash
tmp/chatgpt-plan-venv/bin/python scripts/chatgpt_plan.py login --no-browser --port 1456
```

如果浏览器最后提示无法连接 127.0.0.1，先检查登录命令是否仍在运行，以及 Windows 到 WSL 的 localhost 转发；不要把整个回调地址发给别人。首次注册与重登保留相同的回调路径，只允许改变端口。

凭据放在 **WSL 用户目录**的 `~/.config/kmb-chatgpt-plan/`，文件权限 0600、目录 0700。默认不在项目仓库，也不在 Agent 的评测工作区。不要提交或发送这些文件。切换另一个账号请对下面每条命令使用同一个新参数，例如 `--profile second`，避免覆盖原账号注册。

## 3. 确认当前账户确实能看到 Luna

```bash
tmp/chatgpt-plan-venv/bin/python scripts/chatgpt_plan.py models --model gpt-5.6-luna
```

这会查询当前账户的官方模型列表，不发送推理请求。检查输出包含：

```json
{"requested_model": "gpt-5.6-luna", "available": true}
```

实际输出还包含模型列表。如果 `available` 是 false，停止该型号的接入；Codex 的缓存／界面名称不足以证明此 OAuth 授权拥有同样权限。不要通过修改显示名称或偷偷换模型继续试验。

## 4. 可选：只发一次最小模型请求

**这一步消耗 ChatGPT 套餐额度。每次执行会发一个新请求。** 前三步不发模型推理，授权也不会自动开始本步骤。

```bash
tmp/chatgpt-plan-venv/bin/python scripts/chatgpt_plan.py smoke --model gpt-5.6-luna --allow-one-request
```

提示仅为 `Reply with exactly OK.`，没有仓库、题目、历史、工具或标准答案。工具等待完整流结束，记录返回模型标识、usage 和 `text_is_ok`。完整结束且 `text_is_ok: true` 说明最小文本调用可用；不是工具调用、原生 Agent 健康或记忆能力验证。

诊断修订：`status: completed` 表示服务请求完成，文本检查单独记录。输出新增 `reply_text`、`text_source`、`completed_output_text`、`stream_delta_text`、`stream_event_counts` 和 `text_check_status`。最终事件未包含文本时，可以使用已完整结束的流中的文本增量；两处文本冲突或均不可见则标记未知，不直接算失败或通过。

`text_check_status` 为 `pass` 才是预期回复通过；`mismatch` 表示看到了不同回复，`unobserved` 表示没有提取到文本，`conflicting_text` 表示流式与最终文本不一致。后三种情况命令退出码为 2，但不撤销已观察到的服务端完成状态。旧版只保存了布尔值，无法据此恢复当时实际回复；新请求单独记录，不覆盖旧记录，也不自动重跑。

失败和中断不会自动重跑。开始请求前就写入一条本地 `probe-*.json` 记录；后续中断保留失败／未知状态。超时后手动重复命令也会是一个新请求，先确认上次记录。

此官方预览路线不支持 `max_output_tokens`；工具只限制请求次数和本地接收规模，**不宣称具有服务端 Token／人民币硬上限**。请求“只回答 OK”也不是输出长度的硬限制。可在 ChatGPT Settings → Usage 管理应用套餐使用权限与额度。

## 5. 接下来才是两款 Agent 的适配

本工具到步骤 4 为止，不会启动 OpenClaw／Hermes。当前仓库的 DeepSeek 代理是 Chat Completions 接口，而这条 OAuth 路线使用 Responses API。原生双 Agent 试测还需要：

- 对接消息、工具定义、工具调用与返回值；任何不支持的字段显式失败，不静默省略。
- 在外部服务中保管令牌并串行刷新，Agent 工作区不接触账户凭据。
- 固定同一型号、配置和历史条件，记录请求及失败，定义适用于套餐的资源限制；不能冒充原 DeepSeek 的逐轮硬上限协议。
- 先验证实际模型、工具往返、工作目录、跨会话记忆与案例隔离，再运行预选小试。

授权结果出来前，不需要你修改 Agent 原生配置。你可以只报告 `Authorized` 是否出现以及模型检查的 `available` 值；不要发送凭据、完整登录链接或回调地址。

## 常见结果

| 结果 | 下一步 |
| --- | --- |
| 登录超时 | 确认浏览器与 WSL 在同一电脑，重新运行 login |
| 推理权限未授予 | 检查授权页面的套餐使用权限和工作区限制 |
| `available: false` | 当前授权没有列出目标模型，暂不调用 |
| HTTP 401／invalid_grant | 重新执行 login；不要复制 Codex token |
| HTTP 429／额度错误 | 查看套餐使用页面，不自动重试 |
| active.lock 已存在 | 确认没有别的命令运行；仅在原进程已退出后清理该锁文件 |

登录不消耗推理额度；套餐调用并非无限免费。脚本没有替你修改账户额度，也没有替你接受授权。

官方依据（2026-10-13 核对）：[注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[账号与刷新](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)、[模型列表与推理](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)、[接口限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)。
