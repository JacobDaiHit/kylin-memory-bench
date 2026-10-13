# 从录制到提交：完整操作手册

展示版本为 0.2.1。先使用最终交付包的 `verify-delivery.py` 核对材料；视频是你最后需要完成的实物，文字稿和安装包不代替视频。建议成片 4 分 10 秒，允许范围 3–5 分钟。

## 先认识三组材料

1. 历史正式实验：DeepSeek Flash，openKylin 2.0 SP1 用户空间／WSL 2，36 个标准案例、12 个挑战案例，两款原生 Agent 各三轮。主要统计和相近项目混淆案例来自这里。
2. Luna 压力校题：8 条开发历史、每条 24 次学习，memory 与 reader_only 分开，两款各一轮。读者正确 11/16，未过 14/16 门槛，不用于排名。160 条仅指离线题库，不能说全量已跑完。
3. 视频专用 Luna 六维演示：框架和两款原生 Agent 在真实 openKylin 中执行，六维各一例、各一轮，56 个计划步骤。Ubuntu 只运行模型转发桥和无状态嵌入服务，OAuth 不复制。另保留此前 Ubuntu 六维演示，来源独立，不混算。

## 第一步：准备录制环境

在 Windows 打开项目目录的 PowerShell，执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_desktop.ps1
```

保留这个窗口运行。浏览器打开 `http://127.0.0.1:6084/vnc.html?autoconnect=1&resize=scale`，进入 UKUI 桌面；全屏，关闭无关标签。若桌面已有会话，不要重复启动；按已有窗口继续。更换端口或显示编号见 `docs/openkylin.md`。退出时在启动窗口按 Ctrl+C，不执行 `wsl --shutdown`。

在另一个 PowerShell 窗口打开导览（脚本会绑定正确的 X11 显示器）：

```powershell
wsl -d openKylin-KMB -u kmb -- bash /mnt/d/github/openkylin/scripts/open_report.sh /mnt/d/github/openkylin/docs/presentation/index.html
```

使用你已有的录屏工具，推荐设置为 1600×900 或 1920×1080、30 fps、MP4；关闭麦克风，先录屏，后期中文配音。先录 10 秒检查终端和网页文字是否清楚、鼠标是否可见。页面缩放约 110%–125%，终端字体约 18–22 px。关闭通知，不打开 OAuth 文件、私有配置、账户余额或原生工作区。

录制文件放在交付包外独立目录：`01-desktop.mp4`、`02-live-run.mp4`、`03-results.mp4`、`04-case.mp4`、`05-calibration.mp4`、`06-verify.mp4`。保留连续原片和实际等待耗时。

## 第二步：录素材，按这个顺序操作

| 素材 | 操作 | 必须拍到 |
|---|---|---|
| 桌面与身份 | UKUI 中打开终端，执行下方系统命令 | openKylin 身份、Python、CLI 0.2.1、UKUI 桌面 |
| 主案例 | 打开 `docs/presentation/index.html`，进入“案例” | #28 → #30 → #34 → #35 的提示、回答、可见记忆 |
| 历史成绩 | 导览“数据”，打开两套报告 | 三轮标识、六维图、下界、覆盖率；挑战集订正版来源 |
| Luna 新演示 | 打开 `examples/openkylin-luna-video/report.html` 和 `docs/openkylin-luna-video.md` | 实际 openKylin 环境、run_id、结束状态、错误、双系统雷达图；与历史统计分开 |
| 校题边界 | 打开提交判断和校题摘要 | reader_only 11/16，门槛未通过；不声称排名 |
| 校准 | 打开 `docs/evidence/scoring-calibration-v31/report.html` | 30 条契约样例、4 组指标；正确／错误／未知对照 |
| 离线复核 | 执行下方命令 | 原件通过、订正重算、Luna 公开观测复算 |
| 篡改拒绝 | 执行 `scripts/recording_verify.py --output <新目录>` | 仅修改临时副本，出现 `TAMPER REJECTED` |
| 下载入口 | 打开最终解压包入口、摘要和技术报告 | ZIP、wheel、.deb、PDF、SHA256、仓库维护入口 |

在 openKylin 桌面终端执行：

```sh
cd /mnt/d/github/openkylin
cat /etc/os-release
python3 --version
python3 -m kylin_memory_bench --version
python3 -m kylin_memory_bench verify examples/openkylin-core
python3 -m kylin_memory_bench verify examples/openkylin-challenge
python3 scripts/review_challenge.py --check
python3 scripts/check_luna_pilot_inputs.py --run experiments/memory_stress/v2/luna-short24-candidates16
python3 scripts/replay_luna_short_pilot.py --data experiments/memory_stress/v2/luna-short24-candidates16 --evidence docs/evidence/luna-short24-final-evidence.json --check docs/evidence/luna-short24-candidates16-results.json
python3 scripts/recording_verify.py --output /tmp/kmb-video-tamper-01
```

通过 .deb 安装后用 `/usr/bin/kmb --version` 核对 0.2.1；若裸 `kmb` 指向旧 wheel，使用 `/usr/bin/kmb` 明确选择已验收安装包，不需要删除已有 wheel。

最后一个目录必须不存在；已运行过就换成 `02`。命令全部离线、不调用模型。完整解压包另执行 `python3 verify-delivery.py`，拍摄最后的验收输出即可。

## 第三步：怎样拍“新执行”

已有本轮 Luna 六维实测可以录制结果浏览，但完成后的结果回放不能称为现场执行。若成片要出现模型运行进度，有两个选择：使用你在真实执行时保存的连续录屏；或者在录像开始后启动一个明确标为“视频新演示”的新运行。它不能替换本轮结果，也不要求重现历史失败。

新录制分为两个终端，框架和 Agent 必须在 **openKylin** 中执行。

先在 Ubuntu 终端启动已缓存嵌入服务；若 18789 已有服务，不重复启动：

```sh
cd /mnt/d/github/openkylin
/tmp/kmb-embedding-venv/bin/python -m scripts.local_embeddings --cache /tmp/kmb-embedding-model --ready tmp/local-embedding-ready-recording.json
```

再在另一个 Ubuntu 终端启动模型桥（保持运行，不录私人 control 文件）：

```sh
cd /mnt/d/github/openkylin
tmp/chatgpt-plan-venv/bin/python -m scripts.serve_luna_video_bridges --state-dir tmp/openkylin-recording-service-01
```

若 WSL 已重启，在 PowerShell 先恢复只读运行时挂载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/reuse_wsl_runtime.ps1
```

现在 **先开始连续录屏**，再在 UKUI 的 openKylin 终端执行：

```sh
cd /mnt/d/github/openkylin
cat /etc/os-release
python3 -m kylin_memory_bench --version
python3 -m scripts.run_openkylin_video --bridge-config tmp/openkylin-recording-service-01/control.local.json --output /home/kmb/.local/share/kmb-live/runs/kmb-plan-video-recording-01
```

模型桥与运行目录必须为新目录，已有就统一换成 `02`。control 文件只包含临时回环认证，不含 OAuth，但也不打开或录制。录屏保留两款 Agent 的 CASE 进度、结束状态、原始耗时；结束后打开刚生成的 `report.html` 和 `radar.svg`。可在 UKUI 终端执行：

```sh
bash scripts/open_report.sh /home/kmb/.local/share/kmb-live/runs/kmb-plan-video-recording-01/report.html
```

保留连续原片；成片可以省略等待，但明确标“省略等待 X 分钟，实际耗时 Y 分钟”。新视频运行不会覆盖本次验收结果，不要求重现历史失败。失败／未知仍如实展示。录完后在 Ubuntu 模型桥窗口按 Ctrl+C，结束临时服务；不执行 `wsl --shutdown`。

建议采用这个新执行方案，以满足赛题“openKylin 桌面下运行两款智能体”的要求。单纯播放 Ubuntu 结果或用规则 demo 代替原生 Agent，不作为本视频方案的完成依据。

## 第四步：配音和剪辑

使用 `docs/narration-script.md` 的逐段旁白，`docs/narration.zh.srt` 的字幕底稿。字幕时间是约 4:10 的剪辑基准；按实际语速调整，不要求逐帧照搬。

时间线：0:00–0:20 失败开场；0:20–0:40 系统与流程；0:40–1:20 本轮真实六维结果或明确的新执行；1:20–1:50 历史三轮统计；1:50–2:45 主案例；2:45–3:15 校准与未通过的校题；3:15–3:45 离线原件／篡改复核；3:45–4:10 交付入口。

每段只突出一个信息。不要念长 run_id 和 SHA256，让画面呈现。字幕放底部两行以内，避开终端输出；原片可加速，解释性证据页面不要快速滑过。背景音乐可以不用，旁白清楚最重要。

## 第五步：检查成片与提交

1. 导出 `KylinMemoryBench-0.2.1-demo.mp4`，时长 3–5 分钟。从头看一遍，确认没有黑屏、静音、过小字体、隐私和错误的数据来源标签。
2. 逐条核对视频数字：历史标准 36、挑战 12、各三轮；Luna 校题 8 条历史、32 案例、reader_only 11/16；六维演示按 `docs/openkylin-luna-video.md` 的实际状态。失败／未知不讲成通过。
3. 在干净目录重新解压交付 ZIP，运行 `verify-delivery.py`；不要把源码中的临时工作区放进交付包。
4. 发布 `v0.2.1` 时上传验收过的 ZIP、.deb、wheel、两页摘要、技术报告、SHA256 和 MP4。仓库的 Issues 是维护入口。Release 发布状态必须以实际页面为准，录制时尚未发布就拍本地交付页。
5. 将最终 MP4 和交付附件提交到主办方实际指定入口。比赛入口、文件大小上限、收件确认以主办方要求为准；现有材料不能证明已收件。
6. 用无需登录的窗口检查仓库、Release、视频下载链接。保存提交回执和原始录像。若文件后改动，重新校验散列，不复用旧的“已验收”记录。

**录制就绪不等于已提交。** 最终还需你完成桌面录制／配音和主办方提交动作；本手册提供执行路径、材料和核对口径。
