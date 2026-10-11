# openKylin 运行环境与桌面复现

本项目使用 **openKylin 2.0 SP1（nile）用户空间 + 本机已有 WSL 2**。评测器由 openKylin 自带 Python 3.12.2 执行，调用真实 OpenClaw、Hermes 和 DeepSeek 模型服务。UKUI 组件运行在 Xvfb 的 X11 桌面中，通过仅本机可访问的 noVNC 显示。

无需另外安装 VMware 虚拟机。WSL 2 本身使用虚拟化；本次验证覆盖 openKylin 用户空间、原生 CLI、软件包安装与桌面报告显示，**不覆盖裸机启动、openKylin 专用内核、登录管理器或硬件驱动认证**。

## 已有环境如何复用

- 沿用本机 WSL 2；新增发行版名称为 `openKylin-KMB`。
- rootfs 来自 [openKylin 官方 WSL 仓库](https://gitee.com/openkylin/openkylin-wsl)。固定提交、归档 SHA256、实际 OS、内核与软件包版本见 [环境证据](evidence/openkylin-environment.json)。
- OpenClaw 与 Hermes 沿用本机 Ubuntu 内已经安装的运行时。大部分目录通过只读 bind mount 共享；Hermes 的依赖代际目录允许其正常写入锁和租约。
- 智能体的配置、认证、会话与记忆使用每个案例独立的目录，不从个人配置复制。正式结果写入 `/home/kmb/runs` 的 Linux 文件系统。
- 录屏使用专用用户 `kmb`；未修改 Windows 的默认 Python、已有 Ubuntu 的桌面或个人浏览器配置。

## 本机启动录屏桌面

在 Windows 项目目录开一个 PowerShell：

```powershell
powershell -File scripts/start_desktop.ps1
```

保持该窗口运行，在浏览器打开脚本打印的地址：
`http://127.0.0.1:6084/vnc.html?autoconnect=1&resize=scale`。

再开一个 PowerShell，恢复已有智能体运行时的跨发行版挂载：

```powershell
powershell -File scripts/reuse_wsl_runtime.ps1
```

这些挂载在 WSL 停止后可能消失；重新执行脚本即可，无需重新安装智能体。请先保持桌面会话运行，再恢复挂载和启动实验。脚本拒绝覆盖符号链接或在非空目录上隐藏已有文件。

在桌面中打开最终标准集报告：

```powershell
wsl -d openKylin-KMB -u kmb -- bash /mnt/d/github/openkylin/scripts/open_report.sh
```

挑战集报告可作为参数传入 `.../examples/openkylin-challenge/reviewed-report.html`。Firefox 使用该项目独立的录屏 profile。再次启动前关闭这个 profile 已有的 Firefox 窗口，避免 profile 锁冲突。

停止桌面时，在第一个 PowerShell 按 Ctrl+C。不要在付费评测期间执行 `wsl --shutdown`。

## 新机器的部署路径

已有可用 openKylin 桌面时，直接使用项目源码或 .deb；不需要 Xvfb/noVNC。使用 Python 3.9+：

```sh
python3 -m kylin_memory_bench doctor
python3 -m kylin_memory_bench demo --output "$HOME/kmb-demo"
python3 -m kylin_memory_bench verify "$HOME/kmb-demo"
```

复用 WSL 路线时，从上述官方仓库获取固定 rootfs 并校验归档指纹，使用 `wsl --import <发行版名> <安装目录> <rootfs归档> --version 2` 导入。不要把别人机器的发行版或安装目录直接覆盖。为实验创建普通用户，并锁定供应方 rootfs 中的默认 root 密码。

在专用 openKylin 实验发行版中，原生包依赖为：

```sh
apt-get update
apt-get install python3 sqlite3 ca-certificates libzstd1
apt-get install --no-install-recommends ukui-desktop-environment-core \
  ukui-session-manager ukui-panel ukui-settings-daemon peony kwin-x11 \
  xvfb x11vnc novnc firefox dbus-x11 xterm fonts-noto-cjk ukui-wallpapers
```

以实际官方仓库的软件包版本和依赖求解结果为准，不混入其他发行版软件源。模型和两个智能体需使用已安装、固定版本的真实 CLI；示例配置中的路径应替换为部署者自己的安装路径。

## 本次已定位的兼容问题

| 问题 | 处理与边界 |
|---|---|
| WSLg 的 Wayland 环境影响 X11 组件 | 启动脚本清除 WAYLAND_DISPLAY，固定 X11/xcb；关闭 X11 合成。 |
| Peony 进程存在但桌面未绘制 | 使用原生 `-w -d` 参数显示桌面窗口并注册 D-Bus 服务。 |
| UKUI 会话依赖完整系统登录服务 | 本次以共享 D-Bus 会话启动 KWin、UKUI panel/settings 与 Peony；不声称验证了登录管理器。 |
| 部分主题包文件冲突 | 使用官方桌面 core 元包和已有 openKylin 主题，不强制覆盖冲突文件。 |
| Windows 挂载目录不能满足原生状态权限 | 真实案例工作区放在 Linux 文件系统，完成后仅导出审核过的证据。 |
| Hermes 通过符号链接运行时安装 ID 改变 | 保留相同绝对安装路径，跨发行版 bind mount 共享运行时；仅依赖租约目录需要写权限。 |

noVNC/VNC 仅绑定本机回环地址，不对局域网发布。该桌面使用专用合成实验数据；目录隔离不是针对恶意智能体的安全沙箱。

## 验证与录屏

`scripts/verify_openkylin.sh` 读取真实 OS 标识，在非 openKylin 系统退出失败。测试、包安装与卸载记录见 [验证记录](validation.md)；3–5 分钟的画面顺序与讲解稿见 [录屏脚本](demo-video.md)。完整实测已经保存时，展示报告及运行离线 verify 无需再次付费调用模型。
