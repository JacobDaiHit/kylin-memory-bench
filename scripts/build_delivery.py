#!/usr/bin/env python3
"""Assemble the review-ready handoff without claiming native competition acceptance."""
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench import __version__
from kylin_memory_bench.common import digest, read_json
from kylin_memory_bench.runner import verify_run

START = '# Kylin Memory Bench — 提交材料入口\n\n版本：@@VERSION@@。材料日期：2026-10-03。\n\n本包包含评测方案、48 个合成任务、可安装工具、原生双智能体三轮实验、可重放证据、离线报告与固定源码快照。真实系统为 openKylin 2.0 SP1 / WSL 2；被测对象为固定版本 OpenClaw 与 Hermes，共用 DeepSeek Flash。执行错误和不可观测项保留在原始结果中。\n\n**最终 3–5 分钟演示视频由提交者录制。** 本机桌面和录屏脚本已经准备，见 source/docs/demo-video.md。本包没有把截图或文字说明替代为视频。\n\n## 接收方先做这三步\n\n1. 打开 Technical-Report.pdf，了解方案、数据设计、完整结果、局限和复现方式。\n2. 打开 source/examples/openkylin-core/report.html 和 source/examples/openkylin-challenge/reviewed-report.html；从评分项进入逐事件证据检查器。页面可离线使用。\n3. 用 Python 3.9+ 执行 `python3 verify-delivery.py`。它校验所有交付文件 SHA256，并独立重放四套证据的评分；不调用模型、不收费。\n\nWindows 本机可使用 `C:\\Python313\\python.exe verify-delivery.py`。普通接收者换成自己满足版本要求的 Python 即可。\n\n## 运行工具\n\n- 源码：进入 source 后执行 `python3 -m kylin_memory_bench demo --output runs/new-demo`。\n- Linux：`sh run-demo.sh`；Windows：`powershell -File run-demo.ps1 -Python <Python完整路径>`。\n- openKylin：`sudo apt install ./packages/kylin-memory-bench_@@VERSION@@_all.deb`，然后 `kmb demo --output "$HOME/kmb-demo"`。\n- wheel：`python3 -m pip install --no-index --no-deps packages/kylin_memory_bench-@@VERSION@@-py3-none-any.whl`。\n\n核心评测和证据复核只使用 Python 标准库。真实新实验需要固定原生 CLI、模型服务和部署者自己的凭据；本包不附带私人密钥或运行时二进制。OpenClaw 的压缩原生轨迹另使用系统 libzstd；不可用时相应证据为 unknown，不影响离线评分复核。\n\n## 四套结果的含义\n\n| 目录 | 用途与范围 |\n|---|---|\n| source/examples/openkylin-core | 最终标准集：36 案例，两款真实智能体，各三轮 |\n| source/examples/openkylin-challenge | 最终独立挑战集：12 案例，两款真实智能体，各三轮 |\n| source/examples/sample-run | 三种规则基线，各三轮；仅用于工程对照 |\n| source/examples/live-run | 早期 Ubuntu 单轮六维 pilot，保留研究过程，不计入最终两套成绩 |\n\n挑战集含一项公开的实测后答案标注订正，松柏与松柏项目统一接受；原始分数完整保留。`source/scripts/review_challenge.py --check` 可独立复算六个订正项。不同数据集分数不能直接混合排名。上下界表示缺少证据导致的范围，不是统计置信区间。模拟时间标签不等于真实等待天数。\n\n## 材料位置\n\n| 材料 | 位置 |\n|---|---|\n| 技术方案与实测报告 | Technical-Report.pdf |\n| 源码、数据、适配器、测试 | source/ |\n| 方法、接口、目标系统与验收说明 | source/docs/ |\n| 系统来源与自动测试证据 | source/docs/evidence/ |\n| 实测冻结源码与复现说明 | source/reproducibility/ |\n| 安装包 | packages/ |\n| 最终安装包生命周期验证日志 | validation/package-lifecycle.log |\n| 交付文件完整性清单 | FILES.sha256.json |\n| 3–5 分钟录屏讲稿 | source/docs/demo-video.md |\n\n`verify-delivery.py` 成功表示交付文件完整、评分可重放；不等于所有能力项通过或主办方认证。WSL 2 实测覆盖 openKylin 用户空间和桌面呈现，不代表裸机驱动、专用内核或完整登录管理器验证。\n\n包内未包含私人 .env、原生智能体工作区、开发临时目录、第三方运行时或原始赛题 PDF。\n'

VERIFY = r'''#!/usr/bin/env python3
"""Verify delivered bytes, then independently replay the bundled benchmark evidence."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

root = Path(__file__).resolve().parent
if sys.version_info < (3, 9):
    raise SystemExit('Python 3.9+ is required.')
manifest = json.loads((root / 'FILES.sha256.json').read_text(encoding='utf-8'))
for name, expected in manifest['files'].items():
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise SystemExit('Unsafe manifest path: ' + name)
    path = root.joinpath(*relative.parts)
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise SystemExit('Path escapes delivery directory: ' + name)
    if path.is_symlink() or not path.is_file():
        raise SystemExit('Missing or unsafe file: ' + name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Checksum mismatch: ' + name)
print('SHA256 verified:', len(manifest['files']), 'files', flush=True)
for name in ('sample-run', 'live-run', 'openkylin-core', 'openkylin-challenge',
             'openkylin-difficulty', 'openkylin-difficulty-interrupted'):
    if (root/'source/examples'/name).exists():
        result = subprocess.run([sys.executable, '-m', 'kylin_memory_bench', 'verify', 'examples/'+name], cwd=root/'source')
        if result.returncode:
            raise SystemExit(result.returncode)
result = subprocess.run([sys.executable, 'scripts/review_challenge.py', '--check'], cwd=root/'source')
if result.returncode: raise SystemExit(result.returncode)
for command in ([sys.executable, 'scripts/calibrate_scoring.py', '--check', 'docs/evidence/scoring-calibration-v31'],
                [sys.executable, 'scripts/compare_scoring_versions.py', '--check', 'docs/evidence/scoring-version-comparison-v31.json'],
                [sys.executable, 'scripts/calibrate_revision.py', '--check', '--output', 'docs/evidence/scoring-revision']):
    result = subprocess.run(command, cwd=root/'source')
    if result.returncode: raise SystemExit(result.returncode)
if (root/'source/examples/openkylin-difficulty').exists():
    result = subprocess.run([sys.executable, 'scripts/analyze_difficulty.py', '--run',
                             'examples/openkylin-difficulty', '--output',
                             'docs/evidence/difficulty-analysis', '--check'], cwd=root/'source')
    if result.returncode not in (0, 3): raise SystemExit(result.returncode)
    print('Difficulty acceptance gate:', 'passed' if result.returncode == 0 else 'not met; claims remain limited')
'''

SH = """#!/bin/sh
set -eu
cd "$(dirname "$0")/source"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Python 3.9+ required")'
OUT="runs/delivery-$(date +%Y%m%d-%H%M%S)-$$"
python3 -m kylin_memory_bench demo --output "$OUT" --quiet
python3 -m kylin_memory_bench verify "$OUT"
printf '\\nOpen source/%s/report.html in your browser.\\n' "$OUT"
"""
PS = """param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "source")
try {
    & $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 2)"
    if ($LASTEXITCODE) { throw "Python 3.9+ required. Specify -Python with a supported interpreter path." }
    $runOutput = "runs/delivery-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + ([guid]::NewGuid().ToString("N").Substring(0,8))
    & $Python -m kylin_memory_bench demo --output $runOutput --quiet
    if ($LASTEXITCODE) { throw "Benchmark execution failed." }
    & $Python -m kylin_memory_bench verify $runOutput
    if ($LASTEXITCODE) { throw "Evidence verification failed." }
    Write-Output ("Open source/" + $runOutput + "/report.html in your browser.")
} finally { Pop-Location }
"""


def build():
    verify_run(ROOT/'examples/sample-run')
    if (ROOT/'examples/live-run').exists():
        verify_run(ROOT/'examples/live-run')
    for name,count in [('openkylin-core',36),('openkylin-challenge',12)]:
        verify_run(ROOT/'examples'/name)
        manifest=read_json(ROOT/'examples'/name/'manifest.json')
        if manifest['repeats']!=3 or not manifest['environment']['is_openkylin'] or manifest['status'] not in ('completed','completed_with_errors'):
            raise RuntimeError('Final delivery requires finished three-trial openKylin experiments.')
        from kylin_memory_bench.runner import read_run
        run=read_run(ROOT/'examples'/name)
        if len(run[1])!=count or {a['kind'] for a in run[3]['agents']}!={'openclaw','hermes'}:
            raise RuntimeError('Unexpected dataset size or native agent lineup.')
    pdf=ROOT/'output/pdf/KylinMemoryBench-technical-report.pdf'
    validation=ROOT/'output/validation/package-lifecycle.log'
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
        raise RuntimeError('Build and visually verify the technical PDF first.')
    if not validation.is_file() or 'LIFECYCLE PASS' not in validation.read_text(encoding='utf-8'):
        raise RuntimeError('Final .deb lifecycle validation is required.')
    code = {p.name: p.read_text(encoding='utf-8') for p in sorted((ROOT/'kylin_memory_bench').glob('*.py'))}
    if digest(code) != read_json(ROOT/'examples/sample-run/manifest.json')['implementation_sha256']:
        raise RuntimeError('Sample evidence is from a different implementation; rerun before delivery')
    spec = importlib.util.spec_from_file_location('build_release', ROOT/'scripts/build_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    deb, source_zip = module.build(ROOT/'dist')
    expected='DEB_SHA256='+hashlib.sha256(deb.read_bytes()).hexdigest()
    if expected not in validation.read_text(encoding='utf-8'):
        raise RuntimeError('Package changed after lifecycle validation; validate the final bytes again.')
    wheel = ROOT/'dist'/f'kylin_memory_bench-{__version__}-py3-none-any.whl'
    with zipfile.ZipFile(wheel) as archive:
        for path in sorted((ROOT/'kylin_memory_bench').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.json','.jsonl'):
                name = path.relative_to(ROOT).as_posix()
                if archive.read(name) != path.read_bytes():
                    raise RuntimeError('Wheel is stale: ' + name)
    start = START.replace('@@VERSION@@', __version__).replace('材料日期：2026-10-03', '材料日期：以本包冻结记录为准')
    start += ('\n## 0.2.1 修订材料\n\n先打开 source/docs/presentation/index.html，按问题、运行、结果、证据、校准与复核路径阅读。'
              '数据说明见 source/docs/dataset-card.md；评分修订及底座验证见 source/docs/revision-validation.md。'
              '新增难度试测与历史正式实验分别报告；共享盘基础设施中断尝试也保留，不当成完成的三轮成绩。'
              '难度验收是否通过以 source/docs/evidence/difficulty-analysis/report.html 为准，不能把交付校验成功当成难度通过。\n')
    entries = {'START_HERE.md': start.encode('utf-8'), 'verify-delivery.py': VERIFY.encode('utf-8'),
               'run-demo.sh': SH.encode('utf-8'), 'run-demo.ps1': PS.encode('utf-8'),
               'Technical-Report.pdf':pdf.read_bytes(), 'validation/package-lifecycle.log':validation.read_bytes(),
               'packages/'+deb.name: deb.read_bytes(), 'packages/'+wheel.name: wheel.read_bytes()}
    with zipfile.ZipFile(source_zip) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if info.is_dir():
                continue
            if len(parts) < 2 or '..' in parts or PurePosixPath(info.filename).is_absolute():
                raise RuntimeError('Unsafe source archive path')
            entries['source/' + '/'.join(parts[1:])] = archive.read(info)
    inventory = {name: hashlib.sha256(data).hexdigest() for name,data in sorted(entries.items())}
    entries['FILES.sha256.json'] = (json.dumps({'schema_version':'1.0','files':inventory},ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    output = ROOT/'dist'/f'KylinMemoryBench-{__version__}-delivery.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(entries.items()):
            info = zipfile.ZipInfo(f'KylinMemoryBench-{__version__}-delivery/'+name,(2026,10,3,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            archive.writestr(info,data)
    (ROOT/'dist/DELIVERY.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n',encoding='ascii')
    print(str(output), output.stat().st_size, 'bytes')


if __name__ == '__main__':
    build()
