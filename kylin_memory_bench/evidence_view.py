"""Self-contained, offline evidence inspector generated from recorded run files."""
import json
from pathlib import Path
from .common import write_text, strict_json


def render_evidence(output):
    output=Path(output)
    if not (output/'evidence.jsonl').exists() or not (output/'dataset.jsonl').exists():
        return
    cases=[strict_json(l) for l in (output/'dataset.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    checks={(c['id'],s['id']):s.get('checks',[]) for c in cases for s in c['steps']}
    events=[strict_json(l) for l in (output/'evidence.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    records=[dict(event,gold_checks=checks.get((event['case_id'],event['step_id']),[])) for event in events]
    # Escape the script raw-text terminator; all subsequent rendering uses textContent.
    payload=json.dumps(records,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    write_text(output/'evidence.html',TEMPLATE.replace('@@DATA@@',payload))


TEMPLATE='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>证据检查器 · Kylin Memory Bench</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f2;color:#173c32;font:14px/1.65 system-ui,"Microsoft YaHei",sans-serif}header{background:#173c32;color:white;padding:22px 32px;display:flex;gap:20px;align-items:center}header a{color:#d7f2e7}h1{font-size:20px;margin:0}.layout{display:grid;grid-template-columns:310px 1fr;max-width:1700px;margin:auto;min-height:calc(100vh - 80px)}aside{padding:22px;border-right:1px solid #dce5df}input{width:100%;padding:12px;border:1px solid #c9d9d0;border-radius:6px}#events{max-height:80vh;overflow:auto;margin-top:15px}button{width:100%;text-align:left;border:0;background:transparent;color:inherit;padding:12px;cursor:pointer;border-bottom:1px solid #dce5df}button.active{background:#dbeee3;border-left:3px solid #0f8b73}button small{display:block;color:#64766e}main{padding:28px;min-width:0}h2{font-size:18px;margin:0 0 10px}h3{font-size:13px;color:#49695b;margin:24px 0 8px}pre{white-space:pre-wrap;word-break:break-word;font:12px/1.7 Consolas,monospace;background:white;border:1px solid #dce5df;border-radius:7px;padding:18px;max-height:520px;overflow:auto;margin:0}.meta{font:12px/1.7 Consolas,monospace;overflow-wrap:anywhere;color:#64766e}.notice{background:#e5ede2;padding:12px 16px;border-radius:7px;margin:16px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}#counter{font-size:12px;color:#64766e;margin-top:8px}@media(max-width:850px){.layout{grid-template-columns:1fr}aside{border:0}#events{max-height:180px}.grid{grid-template-columns:1fr}main{padding:20px}}
</style></head><body><header><h1>KYLIN / 证据检查器</h1><a href="report.html">返回评分报告</a><a href="evidence.jsonl">原始 JSONL</a></header><div class="layout"><aside><input id="search" aria-label="筛选证据" placeholder="系统、案例、步骤、事件编号"><div id="counter"></div><div id="events"></div></aside><main><h2 id="title"></h2><div id="meta" class="meta"></div><div class="notice">左侧选择一次已记录步骤，下方并列展示发给智能体的提示、原生返回、实际文件和评分标准。评分标准只用于评测器，未随提示发送给被测智能体。记忆快照的 complete=false 表示仅部分可见。</div><h3>发送的提示</h3><pre id="prompt"></pre><div class="grid"><section><h3>回答</h3><pre id="answer"></pre><h3>持久记忆快照</h3><pre id="memory"></pre></section><section><h3>实际采集的文件</h3><pre id="artifacts"></pre><h3>评分标准（仅评测器可见）</h3><pre id="gold"></pre></section></div><h3>结构化工具轨迹</h3><pre id="actions"></pre><h3>原生轨迹来源与完整性</h3><pre id="trace"></pre><h3>执行错误与使用量</h3><pre id="runtime"></pre></main></div>
<script id="data" type="application/json">@@DATA@@</script><script>
const records=JSON.parse(document.getElementById('data').textContent);const el=id=>document.getElementById(id);const pretty=x=>JSON.stringify(x===undefined?null:x,null,2);let selected='';
function show(r){selected=r.event_id;el('title').textContent='#'+r.event_id+' · '+r.agent_id+' · '+r.case_id+' / '+r.step_id;el('meta').textContent='轮次 '+(r.trial+1)+' · 模拟第 '+r.day+' 天 · '+r.duration_ms+' ms\\nSESSION '+r.session_id+'\\nSHA256 '+r.hash;el('prompt').textContent=r.prompt;const response=r.response||{};el('answer').textContent=response.text||'(无返回)';el('memory').textContent=pretty(response.memory);el('artifacts').textContent=pretty(r.artifacts);el('gold').textContent=pretty(r.gold_checks);el('actions').textContent=pretty(response.actions);el('trace').textContent=pretty(response.trace||{provenance:response.provenance});el('runtime').textContent=pretty({error:r.error,usage:response.usage});document.querySelectorAll('#events button').forEach(b=>b.classList.toggle('active',b.dataset.id===selected));}
function list(){const q=el('search').value.trim().toLowerCase();el('events').replaceChildren();let count=0;for(const r of records){if(q&&!['#'+r.event_id,r.agent_id,r.case_id,r.step_id].join(' ').toLowerCase().includes(q))continue;const b=document.createElement('button');b.dataset.id=r.event_id;b.classList.toggle('active',r.event_id===selected);b.textContent='#'+r.event_id+' · '+r.agent_id+' · 轮次 '+(r.trial+1);const detail=document.createElement('small');detail.textContent=r.case_id+' / '+r.step_id;b.append(detail);b.onclick=()=>{location.hash='event-'+r.event_id;show(r);};el('events').append(b);count++;}el('counter').textContent=count+' / '+records.length+' 个事件';}
function fromHash(){const id=location.hash.replace('#event-','');show(records.find(r=>r.event_id===id)||records[0]);}el('search').addEventListener('input',list);window.addEventListener('hashchange',fromHash);list();if(records.length)fromHash();
</script></body></html>'''
