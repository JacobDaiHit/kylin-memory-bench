#!/usr/bin/env python3
"""Build an offline presentation from actual, unmodified experiment results."""
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("28", "30", "34", "35")
DIMENSIONS = (("retention", "长期保持"), ("retrieval", "记忆调用"),
              ("update", "动态更新"), ("disambiguation", "相近区分"),
              ("boundary", "边界识别"), ("reuse", "任务复用"))


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object: " + str(path))
    return value


def safe_json(value):
    """Keep data inert inside application/json, including hostile closing tags."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def esc(value):
    return html.escape(str(value), quote=True)


def percent(value):
    if value is None:
        return "未提供"
    return "{:.2f}%".format(float(value) * 100)


def href(path, output, anchor=""):
    relative = os.path.relpath(Path(path).resolve(), output.resolve()).replace("\\", "/")
    return quote(relative, safe="/") + ("#" + quote(anchor, safe="-") if anchor else "")


def link(path, output, label, anchor=""):
    path = Path(path)
    if not path.is_file():
        return '<span class="pending">' + esc(label) + ' · pending</span>'
    return '<a href="{}">{}</a>'.format(esc(href(path, output, anchor)), esc(label))


def load_run(directory, score_file):
    manifest = read_json(directory / "manifest.json")
    scores = read_json(directory / score_file)
    if manifest.get("run_id") != scores.get("run_id"):
        raise ValueError("Run ID differs between manifest and scores: " + str(directory))
    agents = scores.get("agents")
    if not isinstance(agents, list) or not agents or any(a.get("is_baseline") for a in agents):
        raise ValueError("The presentation requires real agent results: " + str(directory))
    return {"manifest": manifest, "scores": scores,
            "cases": len({c["case_id"] for a in agents for c in a.get("cases", [])})}


def load_optional(path):
    if path is None or not path.is_file():
        return {"status": "pending", "summary": "尚未生成，不能视为已验证。"}
    return read_json(path)


def run_cards(run):
    cards = []
    for agent in run["scores"]["agents"]:
        overall = agent.get("overall", {})
        cards.append('<article class="score"><span>{}</span><strong>{}</strong>'
                     '<p>下界 · 覆盖率 {} · 上界 {}</p>'
                     '<p>记录步骤 {} · 运行错误 {} · 三轮标准差 {}</p></article>'.format(
                         esc(agent.get("label", agent.get("id", ""))),
                         percent(overall.get("lower_bound")), percent(overall.get("coverage")),
                         percent(overall.get("upper_bound")),
                         esc(agent.get("runtime", {}).get("steps", "未提供")),
                         esc(agent.get("runtime", {}).get("errors", "未提供")),
                         percent(agent.get("stability", {}).get("stddev"))))
    return "".join(cards)


def run_table(run):
    agents = run["scores"]["agents"]
    heads = ''.join('<th>{}</th>'.format(esc(a["id"])) for a in agents)
    rows = []
    for dimension, label in DIMENSIONS:
        cells = ''.join('<td>{}<small>覆盖 {}</small></td>'.format(
            percent(a.get("dimensions", {}).get(dimension, {}).get("lower_bound")),
            percent(a.get("dimensions", {}).get(dimension, {}).get("coverage"))) for a in agents)
        rows.append('<tr><th>{}</th>{}</tr>'.format(label, cells))
    return '<table><thead><tr><th>维度</th>{}</tr></thead><tbody>{}</tbody></table>'.format(heads, ''.join(rows))


def summary_block(data):
    status = data.get("status", "passed" if data.get("passed") is True else
                      "failed" if data.get("passed") is False else "provided")
    summary = data.get("summary")
    if isinstance(summary, str):
        lead = '<p>{}</p>'.format(esc(summary))
    elif isinstance(summary, dict):
        lead = '<dl>' + ''.join('<div><dt>{}</dt><dd>{}</dd></div>'.format(
            esc(k), esc(v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)))
            for k, v in summary.items()) + '</dl>'
    else:
        lead = '<p>下方展示输入的实际摘要；其状态与结论以原始材料为准。</p>'
    return '<span class="tag {}">{}</span>{}<details><summary>查看完整输入摘要</summary><pre>{}</pre></details>'.format(
        'pending' if status == 'pending' else '', esc(status), lead,
        esc(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)))


def case_events(directory, output):
    found = {}
    with (directory / "evidence.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            event_id = str(record.get("event_id"))
            if event_id not in EVENTS:
                continue
            if record.get("agent_id") != "hermes" or record.get("case_id") != "disambiguation-001-224906":
                raise ValueError("Unexpected historical case at event " + event_id)
            response = record.get("response") or {}
            found[event_id] = {"event_id": event_id, "prompt": record.get("prompt", ""),
                               "answer": response.get("text", ""), "memory": response.get("memory"),
                               "hash": record.get("hash", ""), "step_id": record.get("step_id", ""),
                               "href": href(directory / "evidence.html", output, "event-" + event_id)}
    if set(found) != set(EVENTS):
        raise ValueError("Historical example is missing its four required events.")
    notes = {"28": "先保存项目 A：星河-001-224906，Markdown-6234。",
             "30": "收到另一个项目 B，回答明确说替换旧记录，可见快照只剩 B。",
             "34": "查询 A，却返回 B 的旧约定-001-224906。",
             "35": "查询 B 正确：形成正负对照。"}
    for key, event in found.items():
        event["note"] = notes[key]
    return found


STYLE = """
:root{--ink:#173a32;--muted:#5d726a;--line:#dce6df;--green:#087c65;--paper:#f4f7f2;--amber:#82651d}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.65 system-ui,'Microsoft YaHei','Noto Sans CJK SC',sans-serif}a{color:var(--green);text-underline-offset:4px}nav{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--line);padding:12px 4vw;display:flex;gap:22px;flex-wrap:wrap;z-index:2}nav .brand{margin-right:auto;font-weight:700}header{padding:56px max(5vw,24px) 40px;background:#153d32;color:#fff}header h1{font-size:clamp(32px,4vw,56px);line-height:1.25;max-width:920px;margin:12px 0 18px}header p{color:#d5e8dd;max-width:860px}main{max-width:1360px;margin:auto;padding:30px max(4vw,22px)}section{scroll-margin-top:110px;margin-bottom:38px}.panel{background:white;border:1px solid var(--line);border-radius:14px;padding:27px;margin-bottom:20px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.score strong{display:block;font-size:42px;line-height:1.3;margin:8px 0;color:var(--green)}.score p{font-size:13px;color:var(--muted);margin:7px 0}.tag{display:inline-block;font-size:12px;border:1px solid currentColor;border-radius:18px;padding:3px 11px;margin:3px 8px 4px 0}.pending{color:var(--amber)}.eyebrow{font-size:13px;letter-spacing:.06em;color:var(--muted)}h2{font-size:29px;line-height:1.35;margin:0 0 12px}h3{font-size:20px;margin:14px 0 8px}p{margin:10px 0 16px}.muted,small{color:var(--muted)}small{display:block;font-size:12px}.notice{padding:15px 20px;background:#e8f0e7;border-left:4px solid #5b9976;border-radius:4px;margin:18px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:13px 9px;border-bottom:1px solid var(--line)}th{font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f8f4;border:1px solid var(--line);border-radius:7px;padding:14px;font:13px/1.65 ui-monospace,monospace;max-height:440px;overflow:auto}code{font-family:ui-monospace,monospace;font-size:13px;overflow-wrap:anywhere}.buttons{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}button{cursor:pointer;border:1px solid var(--green);border-radius:6px;background:white;color:var(--green);padding:10px 15px;font:inherit}button[aria-pressed=true]{background:var(--green);color:#fff}dl div{display:flex;gap:20px;border-bottom:1px solid var(--line);padding:9px 0}dt{font-weight:600;min-width:140px}dd{margin:0;overflow-wrap:anywhere}.links{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0}.flow{display:flex;gap:13px;flex-wrap:wrap;font-weight:600}.flow span{padding:12px 18px;background:#e8f0e7;border-radius:6px}.radar{max-width:100%;display:block;max-height:340px;margin:10px auto}details summary{cursor:pointer;color:var(--green)}footer{color:var(--muted);font-size:13px;margin:30px 0}.case-note{font-size:21px;font-weight:600}@media(max-width:850px){.grid{grid-template-columns:1fr}nav{gap:12px;font-size:13px}.panel{padding:20px}h2{font-size:25px}dl div{display:block}}@media print{nav{position:static}header{background:white;color:#173a32}header p{color:#5d726a}button{display:none}.panel{break-inside:avoid}pre{max-height:none}body{background:white}}
"""


def build(output, difficulty=None, calibration=None):
    core_dir = ROOT / "examples/openkylin-core"
    challenge_dir = ROOT / "examples/openkylin-challenge"
    core = load_run(core_dir, "scores.json")
    challenge = load_run(challenge_dir, "reviewed-scores.json")
    events = case_events(core_dir, output)
    difficulty_data, calibration_data = load_optional(difficulty), load_optional(calibration)
    payload = {"events": events, "difficulty": difficulty_data, "calibration": calibration_data,
               "historical_run_ids": [core["manifest"]["run_id"], challenge["manifest"]["run_id"]]}
    core_links = ' · '.join([link(core_dir / "report.html", output, "正式标准集报告"),
                              link(core_dir / "evidence.html", output, "逐事件证据"),
                              link(core_dir / "manifest.json", output, "运行记录")])
    challenge_links = ' · '.join([link(challenge_dir / "reviewed-report.html", output, "挑战集订正报告"),
                                   link(challenge_dir / "report.html", output, "冻结原始报告"),
                                   link(challenge_dir / "score-review.json", output, "六项订正记录")])
    data_links = ' · '.join([link(ROOT / "docs/dataset-card.md", output, "数据说明卡"),
                             link(ROOT / "docs/dataset.md", output, "案例协议与数据设计")])
    difficulty_link = link(difficulty, output, "输入难度摘要") if difficulty else ''
    calibration_link = link(calibration, output, "输入校准摘要") if calibration else ''
    delivery_links = ''.join('<p>' + link(ROOT / name, output, label) + '</p>' for name, label in (
        ("README.md", "使用说明"), ("docs/technical-report.pdf", "技术报告 PDF"),
        ("docs/demo-video.md", "录制方案"), ("docs/narration-script.md", "旁白与字幕稿"),
        ("docs/revision-validation.md", "0.2.1 修订验证与范围"),
        ("docs/evidence/foundation-openkylin-0.2.1.json", "离线隔离／篡改拒绝／状态隔离记录"),
        ("docs/evidence/scoring-version-comparison-v31.json", "当前评分版本独立对照"),
        ("docs/memory-revision-v31.md", "V3.1修复与离线验收；本版未付费实测"),
        ("experiments/math_memory/memory-v31/index.html", "数学记忆V3.1实例与持久状态对照"),
        ("docs/research-memory-v3-report.md", "V3历史付费失败与内容／格式诊断"),
        ("docs/evidence/scoring-revision/report.html", "16条新增契约校准"),
        ("CONTRIBUTING.md", "贡献指南"), ("ROADMAP.md", "维护路线图")))
    if not (ROOT / "docs/technical-report.pdf").is_file():
        delivery_links = delivery_links.replace(link(ROOT / "docs/technical-report.pdf", output, "技术报告 PDF"),
                                              link(ROOT / "output/pdf/KylinMemoryBench-technical-report.pdf", output, "技术报告 PDF"))
    buttons = ''.join('<button type="button" data-event="{}" aria-pressed="{}">#{}</button>'.format(
        event_id, 'true' if event_id == '28' else 'false', event_id) for event_id in EVENTS)
    content = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kylin Memory Bench · 离线导览</title><style>@@STYLE@@</style></head><body>
<nav aria-label="导览导航"><span class="brand">KYLIN MEMORY BENCH</span><a href="#data">数据</a><a href="#scoring">评分</a><a href="#case">案例</a><a href="#verify">复核</a><a href="#delivery">交付</a></nav>
<header><span class="tag">离线导览 · 真实材料入口</span><h1>让长期记忆评测<br>有据可查</h1><p>统一任务驱动原生智能体，保留回答、可见记忆、文件和工具结果，把表现转成可解释、可重算的检查。</p><p>适合开发者定位作用域混淆、更新遗漏与产物复用问题。系统范围：openKylin 2.0 SP1 用户空间 / UKUI，复用 WSL 2。</p></header>
<main><section class="panel"><div class="flow"><span>固定案例</span><span>双智能体执行</span><span>多源证据</span><span>六维报告</span><span>独立复核</span></div><div class="notice">历史正式实验、新操作演示、小规模难度试测分别记录。此页面是离线导览，不是实时运行控制台；新双智能体实跑需在原生终端录制。</div></section>
<section id="data"><h2>01 / 数据：覆盖什么，怎样验证</h2><p>标准集 @@CORE_CASES@@ 个案例，独立挑战集 @@CHALLENGE_CASES@@ 个案例。六维为长期保持、记忆调用、动态更新、相近区分、边界识别、任务复用。</p><p>@@DATA_LINKS@@</p><div class="grid"><article class="panel"><span class="tag">历史正式实验</span><h3>标准集 · @@CORE_REPEATS@@ 轮</h3><p>@@CORE_EVENTS@@ 个事件 · 状态 <code>@@CORE_STATUS@@</code></p><code>@@CORE_RUN@@</code><div class="links">@@CORE_LINKS@@</div>@@CORE_CARDS@@@@CORE_TABLE@@</article><article class="panel"><span class="tag">历史实验 · 标注订正版</span><h3>独立挑战集 · @@CHALLENGE_REPEATS@@ 轮</h3><p>@@CHALLENGE_EVENTS@@ 个事件 · 状态 <code>@@CHALLENGE_STATUS@@</code></p><code>@@CHALLENGE_RUN@@</code><div class="links">@@CHALLENGE_LINKS@@</div>@@CHALLENGE_CARDS@@<p>“松柏/松柏项目”的合法别名公开订正，原始报告与六项变更同时保留。其余证据保持原样。</p></article></div><article class="panel"><h3>小规模难度试测</h3>@@DIFFICULTY@@<p>@@DIFFICULTY_LINK@@</p><p class="muted">实际样本、轮次与配置以摘要为准。小样本探针观察不能替代正式三轮统计，也不能外推总体能力排名。</p></article></section>
<section id="scoring"><h2>02 / 评分：先看证据，再解释分数</h2><div class="grid"><article class="panel"><h3>四类结论</h3><p><strong>pass</strong>：判据及其所需证据满足。<br><strong>fail</strong>：已有证据明确否定判据。<br><strong>unknown</strong>：证据不完整，不足以验证。<br><strong>error</strong>：执行或采集未正常完成。</p><p>局部快照缺失某值不能证明全局删除。口头声称写文件不能代替真实文件。输出契约失败不能直接推断为记忆保留失败。</p><p>六维图使用下界，覆盖率反映可验证程度；实现可重复不等于已经证明总体判分准确率。</p></article><article class="panel"><h3>评分校准</h3>@@CALIBRATION@@<p>@@CALIBRATION_LINK@@</p><p class="muted">明确正确别名、错误实体、失败工具与部分证据的预期结论。未实施独立第三方人审时，不宣称第三方认证或独立标注准确率。</p></article></div></section>
<section id="case" class="panel"><span class="eyebrow">历史正式实验 · Hermes 第一轮 · disambiguation-001-224906</span><h2>03 / 从错误回答追到作用域混淆</h2><p>两个不同项目，被当作同一条信息的修订。按事件顺序查看提示、回答与可见快照，最后用正确的 B 召回形成对照。</p><div class="buttons" aria-label="案例事件">@@BUTTONS@@</div><p id="case-note" class="case-note"></p><p id="case-meta" class="muted"></p><div class="grid"><article><h3>发送的提示</h3><pre id="case-prompt"></pre><h3>原生回答</h3><pre id="case-answer"></pre></article><article><h3>可见记忆快照</h3><pre id="case-memory"></pre><a id="case-link" href="@@INITIAL_LINK@@">打开完整事件证据</a></article></div><p class="notice">现象与写入阶段的错误替换相一致，但不足以归因到某个数据库或检索算法。更多失败、未知和运行错误均保留在完整报告。</p></section>
<section id="verify" class="panel"><h2>04 / 复核：保存证据可以独立重算</h2><p>以下命令读取本地记录，不调用模型。订正重算与冻结原始结果分开检查。</p><pre>python3 -m kylin_memory_bench verify examples/openkylin-core\npython3 -m kylin_memory_bench verify examples/openkylin-challenge\npython3 scripts/review_challenge.py --check</pre><p>版本、运行 ID、数据指纹与证据链同时保留。散列一致性证明交付记录一致，不等同于第三方可信执行证明；逻辑时间也不等于真实跨天老化验证。</p></section>
<section id="delivery" class="panel"><h2>05 / 交付：能运行、能定位、能复核</h2><div class="grid"><article><h3>公开入口</h3><p><a href="https://github.com/JacobDaiHit/kylin-memory-bench">GitHub 仓库</a></p><p><a href="https://github.com/JacobDaiHit/kylin-memory-bench/releases">正式 Release 入口</a> · 附件以实际发布状态为准</p><p>核心 CLI 使用 Python 标准库，现有 .deb / wheel 与交付包的验证说明见仓库。录屏素材与视频链接以最终公开附件为准。</p></article><article><h3>本地材料</h3>@@DELIVERY_LINKS@@</article></div></section><footer>本页从已存在的 JSON 与原始事件生成。缺失的新数据明确显示 pending；历史证据与分数未被本生成器修改。</footer></main>
<script id="presentation-data" type="application/json">@@PAYLOAD@@</script><script>
'use strict';const data=JSON.parse(document.getElementById('presentation-data').textContent);const el=id=>document.getElementById(id);function showCase(id){const row=data.events[id];if(!row)return;el('case-note').textContent='#'+id+' · '+row.note;el('case-meta').textContent='STEP '+row.step_id+' · SHA256 '+row.hash;el('case-prompt').textContent=row.prompt;el('case-answer').textContent=row.answer||'(无返回)';el('case-memory').textContent=JSON.stringify(row.memory,null,2);el('case-link').setAttribute('href',row.href);document.querySelectorAll('[data-event]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.event===id)));}document.querySelectorAll('[data-event]').forEach(button=>button.addEventListener('click',()=>showCase(button.dataset.event)));showCase('28');
</script></body></html>'''
    replacements = {"STYLE": STYLE, "CORE_CASES": str(core["cases"]), "CHALLENGE_CASES": str(challenge["cases"]),
                    "DATA_LINKS": data_links, "CORE_LINKS": core_links, "CHALLENGE_LINKS": challenge_links,
                    "CORE_CARDS": run_cards(core), "CHALLENGE_CARDS": run_cards(challenge),
                    "CORE_TABLE": run_table(core), "DIFFICULTY": summary_block(difficulty_data),
                    "CALIBRATION": summary_block(calibration_data), "DIFFICULTY_LINK": difficulty_link,
                    "CALIBRATION_LINK": calibration_link, "BUTTONS": buttons,
                    "INITIAL_LINK": esc(events["28"]["href"]), "DELIVERY_LINKS": delivery_links,
                    "PAYLOAD": safe_json(payload)}
    for prefix, run in (("CORE", core), ("CHALLENGE", challenge)):
        for field, key in (("REPEATS", "repeats"), ("EVENTS", "event_count"),
                           ("STATUS", "status"), ("RUN", "run_id")):
            replacements[prefix + "_" + field] = esc(run["manifest"].get(key, "未提供"))
    for name, replacement in replacements.items():
        content = content.replace("@@" + name + "@@", replacement)
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/presentation", help="New output directory")
    parser.add_argument("--difficulty-summary", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--force", action="store_true", help="Explicitly replace index.html; no directory deletion")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and not args.force:
        parser.error("Output already exists; use a new directory or explicit --force: " + str(output))
    if output.exists() and not output.is_dir():
        parser.error("Output must be a directory: " + str(output))
    try:
        content = build(output, args.difficulty_summary, args.calibration)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(content, encoding="utf-8")
    print(output / "index.html")


if __name__ == "__main__":
    main()
