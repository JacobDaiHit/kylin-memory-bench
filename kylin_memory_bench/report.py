"""Portable offline HTML/SVG and CSV reports; no CDN, telemetry or server required."""
import csv
import html
import io
import math
from pathlib import Path

from .common import DIMENSIONS, canonical, write_text, read_json

COLORS = ['#0f8b73', '#dc8840', '#6376d8', '#ce5b77', '#5387a6', '#8d6cb2']


def esc(value):
    return html.escape(str(value), quote=True)


def percent(value):
    return '未观测' if value is None else f'{value * 100:.1f}%'


def radar(agents):
    cx, cy, radius = 300, 205, 135
    def point(index, fraction):
        angle = -math.pi / 2 + index * math.pi / 3
        return cx + radius * fraction * math.cos(angle), cy + radius * fraction * math.sin(angle)
    def points(values):
        return ' '.join(f'{x:.2f},{y:.2f}' for x, y in (point(i, v) for i, v in enumerate(values)))
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 430" role="img" aria-label="六维评分下界雷达图">',
             '<rect width="600" height="430" fill="#ffffff"/>']
    for level in (.25, .5, .75, 1):
        parts.append(f'<polygon points="{points([level]*6)}" fill="none" stroke="#dbe5e1"/>')
    for i, dimension in enumerate(DIMENSIONS):
        x, y = point(i, 1)
        lx, ly = point(i, 1.28)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x}" y2="{y}" stroke="#dbe5e1"/>')
        parts.append(f'<text x="{lx}" y="{ly+5}" text-anchor="middle" font-size="15" fill="#425950" font-family="sans-serif">{DIMENSIONS[dimension]}</text>')
    for i, agent in enumerate(agents):
        values = [agent['dimensions'][d]['lower_bound'] or 0 for d in DIMENSIONS]
        parts.append(f'<polygon points="{points(values)}" fill="{COLORS[i%len(COLORS)]}" fill-opacity="0.08" stroke="{COLORS[i%len(COLORS)]}" stroke-width="2.5"/>')
    parts.append('</svg>')
    return ''.join(parts)


def render_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    from .evidence_view import render_evidence
    render_evidence(output)
    agents = report['agents']
    graphic = radar(agents)
    write_text(output / 'radar.svg', graphic)
    all_checks = [(agent, case, check) for agent in agents for case in agent['cases'] for check in case['checks']]
    cards = []
    legend = []
    for i, agent in enumerate(agents):
        overall = agent['overall']
        color = COLORS[i % len(COLORS)]
        kind = '规则基线 · 演示数据' if agent['is_baseline'] else '外部智能体 · 运行证据'
        cards.append(f'<article class="agent-card" style="--agent:{color}"><div class="eyebrow">{kind}</div>'
                     f'<h2>{esc(agent["label"])}</h2><div class="big">{percent(overall["lower_bound"])}</div>'
                     f'<div class="muted">保守得分下界</div><dl><div><dt>已观测得分</dt><dd>{percent(overall["score"])}</dd></div>'
                     f'<div><dt>得分上下界</dt><dd>{percent(overall["lower_bound"])} – {percent(overall["upper_bound"])}</dd></div>'
                     f'<div><dt>证据覆盖率</dt><dd>{percent(overall["coverage"])}</dd></div>'
                     f'<div><dt>重复试验标准差</dt><dd>{percent(agent["stability"]["stddev"])}</dd></div>'
                     f'<div><dt>运行错误</dt><dd>{agent["runtime"]["errors"]}</dd></div></dl></article>')
        legend.append(f'<span><i style="background:{color}"></i>{esc(agent["label"])}</span>')
    dimension_rows = []
    for dimension, label in DIMENSIONS.items():
        cells = ''.join(f'<td><strong>{percent(a["dimensions"][dimension]["lower_bound"])}</strong>'
                        f'<small>覆盖 {percent(a["dimensions"][dimension]["coverage"])}</small></td>' for a in agents)
        dimension_rows.append(f'<tr><th>{label}</th>{cells}</tr>')
    rows = []
    labels = {'pass': '通过', 'fail': '失败', 'unknown': '证据不足', 'error': '运行错误'}
    for agent, case, check in all_checks:
        searchable = (agent['label'] + ' ' + case['title'] + ' ' + case['case_id'] + ' ' + check['category']).lower()
        rows.append(f'<tr data-agent="{esc(agent["id"])}" data-dimension="{case["dimension"]}" data-status="{check["status"]}" data-search="{esc(searchable)}">'
                    f'<td>{esc(agent["label"])}</td><td><strong>{esc(case["title"])}</strong><small>{esc(case["case_id"])} · 轮次 {case["trial"]+1}</small></td>'
                    f'<td>{DIMENSIONS[case["dimension"]]}</td><td><span class="status {check["status"]}">{labels[check["status"]]}</span></td>'
                    f'<td><details><summary>{esc(check["check_id"])} · {esc(check["source"])}</summary><p>{esc(check["reason"])}</p>'
                    f'<code>{esc(check["category"])}</code><p class="muted"><a href="evidence.html#event-{esc(check["evidence_id"])}">查看事件 #{esc(check["evidence_id"])}</a> · 步骤 {esc(check["step_id"])}</p></details></td></tr>')
    agent_options = ''.join(f'<option value="{esc(a["id"])}">{esc(a["label"])}</option>' for a in agents)
    dimension_options = ''.join(f'<option value="{d}">{label}</option>' for d, label in DIMENSIONS.items())
    headers = ''.join(f'<th>{esc(a["label"])}</th>' for a in agents)
    baseline_notice = '当前包含规则基线，仅用于证明评测流程与错误区分能力；不代表真实大模型或 openKylin 实机成绩。' if any(a['is_baseline'] for a in agents) else '此报告来自外部适配器。请结合 manifest.json 核对系统、模型配置及运行状态；接入不等于实机认证。'
    environment_text = 'Environment provenance is recorded in manifest.json.'
    if (output / 'manifest.json').is_file():
        environment = read_json(output / 'manifest.json').get('environment', {})
        system_name = environment.get('os_release', {}).get('PRETTY_NAME') or environment.get('system', 'unknown')
        environment_text = system_name + ' / ' + environment.get('execution_context', environment.get('release', 'unknown')) + ' / Python ' + environment.get('python', 'unknown')
    if report.get('run_status') == 'comparison':
        environment_text = 'Multiple source runs: see sources.json.'
    dimension_count = sum(any(a['dimensions'][d]['cases'] for a in agents) for d in DIMENSIONS)
    content = TEMPLATE.replace('@@CARDS@@', ''.join(cards)).replace('@@RADAR@@', graphic)
    replacements = {'LEGEND': ''.join(legend), 'DIMENSION_ROWS': ''.join(dimension_rows), 'HEADERS': headers,
                    'ROWS': ''.join(rows), 'AGENT_OPTIONS': agent_options, 'DIMENSION_OPTIONS': dimension_options,
                    'RUN_ID': esc(report['run_id']), 'DATASET_HASH': report['dataset_sha256'],
                    'AGENTS': str(len(agents)), 'CHECKS': str(len(all_checks)), 'NOTICE': baseline_notice,
                    'RUN_STATUS': esc(report['run_status']), 'ENVIRONMENT': esc(environment_text), 'DIMENSIONS': str(dimension_count)}
    for key, value in replacements.items():
        content = content.replace('@@' + key + '@@', value)
    if report.get('run_status') == 'comparison':
        import re
        content = re.sub(r'href="evidence.html(?:#event-[^"]*)?"', 'href="sources.json"', content)
        content = content.replace('href="evidence.jsonl">原始证据', 'href="sources.json">源运行索引')
    write_text(output / 'report.html', content)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(['agent', 'kind', 'dimension', 'score', 'coverage', 'lower_bound', 'upper_bound', 'cases'])
    for agent in agents:
        for dimension, metrics in agent['dimensions'].items():
            # Prevent spreadsheet formula execution from user-controlled labels.
            label = agent['id']
            if label.startswith(('=', '+', '-', '@')):
                label = "'" + label
            writer.writerow([label, agent['kind'], dimension, *[metrics[k] for k in ('score', 'coverage', 'lower_bound', 'upper_bound', 'cases')]])
    write_text(output / 'metrics.csv', buffer.getvalue())


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>Kylin Memory Bench · 长期记忆评测</title><style>
:root{--ink:#173c32;--muted:#65786f;--line:#dfe7e2;--paper:#f3f6f2;--green:#0f8b73}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.6 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}header{background:#173c32;color:white;padding:35px max(5vw,24px) 42px}.topline{display:flex;justify-content:space-between;gap:20px;align-items:center;font-size:13px;letter-spacing:.08em}.brand{font-weight:700}.pill{border:1px solid #789389;border-radius:30px;padding:4px 12px;color:#d2e7dc;font-size:11px}h1{font-size:clamp(27px,4vw,43px);letter-spacing:-.03em;line-height:1.25;margin:28px 0 12px}header p{max-width:700px;color:#c6dad0;margin:0}main{max-width:1440px;margin:0 auto;padding:28px max(3vw,20px) 64px}.notice{background:#e8efe7;border-left:3px solid #73a88c;padding:12px 18px;border-radius:4px;color:#486451;font-size:13px;margin-bottom:24px}.summary{display:flex;gap:28px;align-items:center;margin:0 0 22px}.summary b{font-size:21px;margin-right:5px}.summary span{color:var(--muted);font-size:12px}.summary .run{margin-left:auto;font:12px monospace;color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-bottom:26px}.agent-card{background:white;border:1px solid var(--line);border-top:3px solid var(--agent);border-radius:10px;padding:23px 26px}.eyebrow{font-size:11px;letter-spacing:.06em;color:var(--muted)}h2{font-size:18px;margin:8px 0 14px}.big{font-size:43px;line-height:1.15;font-weight:650;letter-spacing:-.04em;color:var(--agent)}.muted{color:var(--muted);font-size:12px}dl{border-top:1px solid var(--line);margin:19px 0 0;padding-top:12px}dl div{display:flex;justify-content:space-between;font-size:12px;margin:6px 0}dt{color:var(--muted)}dd{font-weight:600}.middle{display:grid;grid-template-columns:1fr 1.2fr;gap:22px}.panel{background:white;border:1px solid var(--line);border-radius:10px;padding:24px}.panel h2{margin:0 0 4px}.panel p{margin:0 0 12px}.panel svg{display:block;width:100%;max-height:380px}.legend{display:flex;gap:16px;flex-wrap:wrap;justify-content:center;font-size:11px}.legend span{display:flex;align-items:center;gap:6px}.legend i{width:9px;height:9px;border-radius:50%;display:inline-block}table{border-collapse:collapse;width:100%;font-size:12px;text-align:left}th,td{border-bottom:1px solid var(--line);padding:15px 11px;vertical-align:top}thead th{font-size:11px;color:var(--muted);font-weight:500;background:#fafcf9}small{display:block;font-size:10px;color:var(--muted);margin-top:3px;overflow-wrap:anywhere}.table-scroll{overflow:auto}.method{margin:20px 0 26px;color:var(--muted);font-size:12px}.audit-title{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}.audit-title h2{margin:0}.downloads{display:flex;gap:14px;font-size:12px}a{color:var(--green);text-underline-offset:3px}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 18px}select,input{font:inherit;font-size:12px;border:1px solid var(--line);background:#fff;color:var(--ink);border-radius:5px;padding:8px 10px;min-width:120px}input{flex:1;min-width:190px}.status{display:inline-block;white-space:nowrap;padding:3px 9px;border-radius:20px;font-size:10px}.pass{color:#12694b;background:#e1f2e8}.fail{color:#a2482f;background:#fcebe4}.unknown{color:#775e23;background:#f6f0dc}.error{color:#9f3753;background:#f9e6ed}summary{cursor:pointer;min-width:170px}details p{margin:9px 0}code{font-size:11px;overflow-wrap:anywhere}footer{font-size:11px;color:var(--muted);margin-top:22px;overflow-wrap:anywhere}#empty{display:none;text-align:center;padding:30px;color:var(--muted)}@media(max-width:900px){.middle{grid-template-columns:1fr}.summary .run{display:none}.audit-title{display:block}.downloads{margin-top:12px}.panel{padding:18px}}@media print{header{background:white;color:black}.filters{display:none}.panel{break-inside:avoid}.table-scroll{overflow:visible}body{background:white}.notice{background:white}}
</style></head><body><header><div class="topline"><div class="brand">KYLIN / MEMORY BENCH</div><span class="pill">EVIDENCE FIRST · v0.2</span></div><h1>记住什么，也要知道何时忘记。</h1><p>从跨会话对话到实际任务产物，沿着可追溯证据，观察智能体长期记忆的六个维度。</p></header>
<main><div class="notice">@@NOTICE@@<br/><span class="muted">@@ENVIRONMENT@@</span></div><div class="summary"><div><b>@@AGENTS@@</b><span>个被测系统</span></div><div><b>@@DIMENSIONS@@</b><span>个能力维度</span></div><div><b>@@CHECKS@@</b><span>项验证</span></div><span class="run">RUN · @@RUN_STATUS@@</span></div><section class="cards">@@CARDS@@</section>
<div class="middle"><section class="panel"><h2>六维能力画像</h2><p class="muted">绘制保守得分下界；缺少证据的部分不计作通过。</p>@@RADAR@@<div class="legend">@@LEGEND@@</div></section><section class="panel"><h2>维度对比</h2><p class="muted">每个维度等权；得分与证据覆盖率一起阅读。</p><div class="table-scroll"><table><thead><tr><th>能力维度</th>@@HEADERS@@</tr></thead><tbody>@@DIMENSION_ROWS@@</tbody></table></div></section></div>
<p class="method">计分：每案例内验证项加权，再按案例与维度取宏平均。已观测得分 = 通过 / 已判定；下界将未知项视为未通过，上界将未知项视为通过。部分记忆快照不能证明完整存储中不存在某项。模拟天数不是实际经过的时间。</p>
<section class="panel"><div class="audit-title"><div><h2>逐项检查 · 可解释评分</h2><span id="count" class="muted"></span></div><nav class="downloads"><a href="scores.json">评分 JSON</a><a href="metrics.csv">指标 CSV</a><a href="radar.svg">雷达图 SVG</a><a href="evidence.html">证据检查器</a><a href="evidence.jsonl">原始证据</a></nav></div><div class="filters"><select id="agent" aria-label="筛选系统"><option value="">全部系统</option>@@AGENT_OPTIONS@@</select><select id="dimension" aria-label="筛选维度"><option value="">全部维度</option>@@DIMENSION_OPTIONS@@</select><select id="status" aria-label="筛选状态"><option value="">全部状态</option><option value="pass">通过</option><option value="fail">失败</option><option value="unknown">证据不足</option><option value="error">运行错误</option></select><input id="search" aria-label="搜索案例" placeholder="搜索案例、编号或错误类型"></div><div class="table-scroll"><table><thead><tr><th>系统</th><th>案例</th><th>维度</th><th>结果</th><th>评分依据</th></tr></thead><tbody id="checks">@@ROWS@@</tbody></table></div><div id="empty">没有匹配的验证项。</div></section><footer>RUN @@RUN_ID@@<br>DATASET SHA256 @@DATASET_HASH@@<br>本报告可离线打开。证据链与独立重评分使用 kmb verify 检查；散列完整性不等同于可信执行证明。</footer></main>
<script>const rows=Array.from(document.querySelectorAll('#checks tr'));const controls=['agent','dimension','status','search'].map(id=>document.getElementById(id));function filter(){let n=0;for(const row of rows){let ok=true;for(const el of controls){const value=el.value.toLowerCase();if(value&&(el.id==='search'?!row.dataset.search.includes(value):row.dataset[el.id].toLowerCase()!==value))ok=false;}row.hidden=!ok;if(ok)n++;}document.getElementById('count').textContent=n+' / '+rows.length+' 项';document.getElementById('empty').style.display=n?'none':'block';}controls.forEach(el=>el.addEventListener('input',filter));filter();</script></body></html>
'''
