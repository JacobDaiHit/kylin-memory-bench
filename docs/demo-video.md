# 3–5 分钟桌面演示脚本

建议录制约 4 分钟。真实双智能体完整评测已保存；录屏展示原始结果与本地复核，不必把长时间云模型实验重新塞进四分钟。若现场演示新的模型调用，应明确它是单案例补充演示，不能替代或覆盖完整实验。

## 准备画面

按 [openKylin 说明](openkylin.md) 启动桌面与 Firefox。桌面上准备两个窗口：原生终端和标准集报告；另开挑战集 reviewed-report.html（标注订正版）标签。使用 1600×900 桌面，浏览器放大到合适宽度。关闭无关标签，不显示任何 .env、私有配置或个人项目。

可以使用本机已经可用的录屏工具录制浏览器中的完整 noVNC 桌面。不需要新增桌面虚拟机。画面中保留 UKUI 任务栏或开头的系统验证，避免把宿主 Windows 浏览器直接打开 HTML 的画面描述为 openKylin 内运行。

## 时间与讲解

| 时间 | 画面与操作 | 建议讲解 |
|---|---|---|
| 0:00–0:25 | UKUI 桌面；终端执行 cat /etc/os-release、python3 --version、kmb --version | “这是 openKylin 2.0 SP1 用户空间，复用本机 WSL 2。项目用原生 Python 运行；这里验证用户空间和桌面，不声称裸机或专用内核认证。” |
| 0:25–0:55 | 展示 validate 标准集与挑战集，随后 doctor 或固定版本记录 | “标准集 36 例覆盖六个维度，独立挑战集增加 12 个复杂语义场景。每个案例包含多个会话，答案不发送给被测智能体。” |
| 0:55–1:45 | 打开标准集 report.html；展示两个原生智能体、运行状态、覆盖率和雷达图 | “OpenClaw 和 Hermes 使用同一个 DeepSeek Flash 服务，各跑三轮。图上绘制得分下界；缺少存储证据不会直接算作通过。” |
| 1:45–2:35 | 筛选任务复用，展开验证项，点击事件链接，查看实际文件和工具轨迹 | “文件必须真实存在且内容正确。OpenClaw 使用原生 SQLite 工具调用与结果配对；Hermes 使用原生事件。口头声称写入文件不会得分。” |
| 2:35–3:15 | 挑战集选择一个失败或边界案例；并列展示提示、回答和判分标准 | “困难项和失败没有被删掉。执行故障、能力失败和证据不足分别报告，便于定位问题。” |
| 3:15–3:45 | 终端运行两套真实结果的 verify | “复核只读取保存的证据，检查散列链并重算分数，无需再次联网调用模型。” |
| 3:45–4:10 | 展示源码、技术报告、安装包与一键入口 | “交付包含方案、数据、原生适配器、可安装 CLI、离线报告和固定源码快照。后续可扩展真实长时间 TTL、更多场景和模型。” |

## 可复制的终端命令

源码方式（安装 .deb 后可以把 python3 -m kylin_memory_bench 换成 kmb）：

```sh
cd /mnt/d/github/openkylin
cat /etc/os-release
python3 --version
python3 -m kylin_memory_bench --version
python3 -m kylin_memory_bench validate kylin_memory_bench/data/sample.jsonl
python3 -m kylin_memory_bench validate kylin_memory_bench/data/challenges.jsonl
python3 -m kylin_memory_bench verify examples/openkylin-core
python3 -m kylin_memory_bench verify examples/openkylin-challenge
python3 scripts/review_challenge.py --check
```

如需在视频中展示一键运行，可加一段 `python3 -m kylin_memory_bench demo --output /home/kmb/runs/video-demo-新编号`，并口头说明这是离线规则基线，用于演示工具工作流。不要将其三个基线成绩误称为两款真实智能体的成绩。

## 录制完成后的检查

- 时长在 3–5 分钟，文字可读，系统身份、两款智能体、六维图、证据跳转与复核命令均出现。
- 提及三轮、逻辑时间、部分存储可见性及已记录执行错误，不使用“全能力满分”等外推。
- 视频中没有真实 API key 或私有配置。输出 mp4 文件加入最终提交目录。
- 视频是本交付唯一明确交由提交者完成的材料；完整软件与可复核实验材料由项目提供。

演示挑战集时说明：两款系统都把“松柏项目”答对，原始标注曾只接受“松柏”。项目公开订正这一标注缺陷，原始与订正报告并列保存；不能将这六次误判继续解释为记忆混淆。
