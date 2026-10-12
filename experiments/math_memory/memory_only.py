"""V3: research-record memory, no mathematical solver or paid calls.

python3 -m experiments.math_memory.memory_only --output experiments/math_memory/memory-v3
Gold and the review viewer are evaluator materials; adapters receive prompt only.
"""
import argparse
import copy
import hashlib
import html
import json
import random
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

from kylin_memory_bench.common import strict_json

RULES = '''研究档案规则：这里只恢复明确给出的研究记录，不求特征值、不计算常数、不证明引理。
每份记录有唯一ID、项目、状态和内容，按会话到达顺序处理。只有accepted生效，draft不生效。
patch只替换列出的字段，其余字段保持不变；当前revision取最后一份accepted patch/cancel登记的标签，不能按版本号大小选择。
cancel仅取消同项目指定patch的指定字段（all表示该patch全部字段），其他patch和未取消字段仍有效；按剩余有效修改恢复当前值。
采用引理必须匹配登记的project、lemma_id、edition、regime四项，不自行改用最新引理或别的项目/范围。
审阅结论、适用范围和常数都是已给出的登记事实，请原样恢复，不判断其数学真伪。
C0是标为checkpoint=C0的初始记录，查询C0时不应用后续修改。当前修改不能覆盖历史回答。
hint_permission=false表示暂存常数不允许在当前回答中复用；这不撤回已批准的引理常数。
从未提供的值，以及明确禁止复用的hint，返回null。允许保存研究笔记供后续独立会话使用。
'''
QUESTIONS = [
    ('q01','当前A11','field','a11','rational','atomic'),
    ('q02','当前A12','field','a12','rational','atomic'),
    ('q03','当前A22','field','a22','rational','atomic'),
    ('q04','当前D1','field','d1','rational','atomic'),
    ('q05','当前D2','field','d2','rational','atomic'),
    ('q06','当前耦合矩阵的登记标识','field','coupling','text','atomic'),
    ('q07','当前批准的研究分支','field','branch','text','atomic'),
    ('q08','当前批准修改的revision标签','revision',None,'text','atomic'),
    ('q09','当前引用的lemma_id','adoption','lemma_id','text','linked'),
    ('q10','该引用明确指定的edition','adoption','edition','text','linked'),
    ('q11','该引用明确指定的regime','adoption','regime','text','linked'),
    ('q12','与该引用四项完全匹配的引理记录中的bound','lemma','bound','rational','linked'),
    ('q13','当前归一化约定','field','normalization','text','atomic'),
    ('q14','当前记录的review_decision（抄登记结论，不自行审稿）','field','review_decision','text','atomic'),
    ('q15','C0检查点当时的D1','historical','d1','rational','historical'),
    ('q16','C0检查点当时的研究分支','historical','branch','text','historical'),
    ('q17','当前允许复用的暂存six_order_hint','hint','six_order_hint','rational','boundary'),
    ('q18','登记的error_bound_o8','field','error_bound_o8','rational','boundary'),
]
FAMILIES = {
    'binding':('相近项目绑定','候选项目数',2,8,'disambiguation'),
    'updates':('分散字段修订','主要字段修订数',1,6,'update'),
    'delay':('跨会话保持与旧检查点','后置干扰会话数',2,18,'retention'),
    'scope':('引理版本与范围绑定','额外同名引理登记数',0,6,'retrieval'),
    'cancel':('选择性取消','取消范围',0,1,'boundary'),
    'combined':('综合压力','多个因素共同增加',0,1,'reuse'),
}
POLICIES = ('ledger','stateless','stale','accept_draft','project_blind',
            'edition_blind','ignore_cancel','ignore_withdrawal','guess_missing')
ALIASES = {'q13':['u^T u=1','uTu=1','unit_norm'], 'q14':['approved','已批准']}


def record(project,kind,payload,status='accepted',revision=None,checkpoint=None):
    result={'project':project,'kind':kind,'status':status,'payload':payload}
    if revision is not None: result['revision']=revision
    if checkpoint is not None: result['checkpoint']=checkpoint
    return result


def history(seed,family,level):
    rng=random.Random(seed)
    project='SCHUR-'+str(rng.randrange(100000,999999))+'-research'
    suffix=str(rng.randrange(1000,9999))
    initial={'a11':'29/20','a12':'1/20','a22':'89/20','d1':str(rng.randrange(4,9)),
             'd2':'5','coupling':'B-'+suffix,'branch':'branch-green-'+suffix,
             'normalization':'u^T u=1','review_decision':'approved',
             'adoption':{'lemma_id':'L-Schur-'+suffix,'edition':'e2','regime':'finite'},
             'six_order_hint':'7/31','hint_permission':True}
    # All queried changes are stated facts; the benchmark never derives them.
    final={'a11':str(Fraction(rng.randrange(11,31),7)), 'a12':str(Fraction(rng.randrange(1,7),13)),
           'a22':str(Fraction(rng.randrange(31,51),11)), 'd1':'2','d2':'3',
           'branch':'branch-blue-'+suffix}
    bound=str(Fraction(rng.randrange(2,11),17))
    high=level=='high'
    projects=8 if high and family in ('binding','combined') else 2
    updates=6 if high and family in ('updates','combined') else 1
    scopes=6 if high and family in ('scope','combined') else 0
    gaps=18 if high and family in ('delay','combined') else 2
    selective=high and family in ('cancel','combined')
    cancelling=family in ('cancel','combined')
    records=[record(project,'patch',initial,revision='v0',checkpoint='C0'),
             record(project,'lemma',{'lemma_id':initial['adoption']['lemma_id'],'edition':'e2',
                    'regime':'finite','bound':bound})]
    if updates==1:
        revised=dict(final)
        if selective: revised['branch']=initial['branch']
        records.append(record(project,'patch',revised,revision='v4'))
    else:
        # Larger approved version labels precede v4: latest-number shortcuts fail.
        for (key,value),revision in zip(final.items(),('v8','v3','v7','v2','v1','v4')):
            if key=='branch' and selective: value=initial['branch']
            records.append(record(project,'patch',{key:value},revision=revision))
    if cancelling:
        temporary={'d1':'19'}
        if selective: temporary['branch']=final['branch']
        patch_index=len(records)
        records.append(record(project,'patch',temporary,revision='v5'))
        records.append(record(project,'cancel',{'target_index':patch_index,
                       'fields':['d1'] if selective else 'all'},revision='v6'))
    # The draft is a complete tempting alternative, never an accepted revision.
    records.append(record(project,'patch',{'a11':'99','d1':'97','branch':'draft-red-'+suffix},
                          status='draft',revision='v99'))
    records.append(record(project,'patch',{'hint_permission':False}))
    for i in range(scopes):
        records.append(record(project,'lemma',{'lemma_id':initial['adoption']['lemma_id'],
                       'edition':'e'+str(3+i),'regime':'finite' if i%2==0 else 'infinite',
                       'bound':str(Fraction(20+i,19))}))
    for i in range(projects):
        nearby=project+('-archive' if i==0 else '-grid-'+str(i))
        payload=dict(initial,**{'a11':str(40+i),'d1':str(50+i),'d2':str(60+i),
                    'coupling':'B-near-'+str(i),'branch':'branch-near-'+str(i),
                    'normalization':'max_norm=1','review_decision':'pending'})
        records.append(record(nearby,'patch',payload,revision='v4',checkpoint='C0'))
        records.append(record(nearby,'lemma',{'lemma_id':initial['adoption']['lemma_id'],
                       'edition':'e2','regime':'finite','bound':str(Fraction(30+i,23))}))
    for i in range(gaps):
        records.append(record('seminar-'+str(i),'discussion',{'topic':'算子研讨会安排',
                       'room':'ROOM-'+str(700+i),'note':'不修改任何研究项目的数学登记记录。'}))
    for index,r in enumerate(records): r['id']='R'+suffix+'-'+str(index).zfill(3)
    for r in records:
        if r['kind']=='cancel': r['payload']['target_id']=records[r['payload'].pop('target_index')]['id']
    return project,records,{'candidate_projects':projects,'main_parameter_revisions':updates,
                            'temporary_revision_count':1 if cancelling else 0,'permission_update_count':1,
                            'additional_lemma_records':scopes,'post_interference_sessions':gaps,
                            'selective_cancel':selective}


def view(records,project,policy='ledger',historical=False):
    admitted=[r for r in records if r['status']=='accepted' or policy=='accept_draft']
    if historical:
        checkpoint=next((r for r in admitted if r['project']==project and r.get('checkpoint')=='C0'),None)
        if checkpoint is None: return {},None,[]
        admitted=admitted[:admitted.index(checkpoint)+1]
    same=(lambda r:r['project']==project) if policy!='project_blind' else (lambda r:r['kind']!='discussion')
    disabled={}
    if policy!='ignore_cancel':
        for r in admitted:
            if same(r) and r['kind']=='cancel':
                disabled.setdefault(r['payload']['target_id'],[]).append(r['payload']['fields'])
    state,revision,lemmas={},None,[]
    seen_patch=False
    for r in admitted:
        if not same(r): continue
        if r['kind']=='lemma': lemmas.append(r); continue
        if r['kind']=='cancel': revision=r.get('revision',revision); continue
        if r['kind']!='patch': continue
        if policy=='stale' and seen_patch: continue
        seen_patch=True
        for key,value in r['payload'].items():
            if any(fields=='all' or key in fields for fields in disabled.get(r['id'],[])): continue
            if policy=='ignore_withdrawal' and key=='hint_permission' and value is False: continue
            state[key]=copy.deepcopy(value)
        revision=r.get('revision',revision)
    return state,revision,lemmas


def recover(records,project,policy='ledger'):
    state,revision,lemmas=view(records,project,policy)
    initial,_,_=view(records,project,policy,historical=True)
    adoption=state.get('adoption',{})
    matched=[r for r in lemmas if all(r['payload'].get(k)==adoption.get(k)
                                    for k in ('lemma_id','regime')) and
             (policy=='edition_blind' or r['payload'].get('edition')==adoption.get('edition'))]
    lemma=matched[-1]['payload'] if matched else {}
    answers={}
    for qid,label,kind,key,typ,group in QUESTIONS:
        if kind=='field': value=state.get(key)
        elif kind=='revision': value=revision
        elif kind=='adoption': value=adoption.get(key)
        elif kind=='lemma': value=lemma.get(key)
        elif kind=='historical': value=initial.get(key)
        else: value=state.get(key) if state.get('hint_permission') else None
        if policy=='guess_missing' and value is None: value='1'
        answers[qid]=value
    return answers


def combined_history(seed,level):
    parts=[]
    projects=[]
    for i,offset in enumerate((0,101,202)):
        project,records,loads=history(seed+offset,'combined' if i==0 else 'cancel',level if i==0 else 'high')
        projects.append(project)
        ids={r['id']:project+'-'+r['id'] for r in records}
        for r in records:
            r['id']=ids[r['id']]
            payload=r['payload']
            if r['kind']=='cancel':payload['target_id']=ids[payload['target_id']]
            # Shared lemma name across projects; exact project/edition/scope still matters.
            if 'adoption' in payload:
                payload['adoption']['lemma_id']='L-Schur-shared'
                if i and r['project']==project:payload['adoption']['edition']='e'+str(2+i)
            if r['kind']=='lemma':
                payload['lemma_id']='L-Schur-shared'
                if i and r['project']==project:payload['edition']='e'+str(2+i)
            if i and r['project']==project and r['kind']=='patch' and payload.get('d1')=='2':
                payload['d1']=str(2+i)
        parts.append(records)
    # Alternate projects in each block of the diary; final query targets are not announced before it.
    records=[part[index] for index in range(max(map(len,parts))) for part in parts if index<len(part)]
    active={r['project'] for r in records if r['kind']!='discussion'}
    return projects,records,{'query_projects':3,'candidate_projects':len(active),
                            'nearby_projects':len(active)-3,'main_parameter_revisions':6 if level=='high' else 1,
                            'main_post_interference_sessions':18 if level=='high' else 2,
                            'main_additional_lemma_records':6 if level=='high' else 0,
                            'selective_cancel':level=='high'}


def plan_for(projects):
    if len(projects)==1:
        specs=[(q[0],projects[0],q[0]) for q in QUESTIONS]
    else:
        specs=[]
        for index,project in enumerate(projects):
            specs.extend([('q'+str(1+2*index).zfill(2),project,'q04'),
                          ('q'+str(2+2*index).zfill(2),project,'q07')])
        specs += [('q'+str(7+i).zfill(2),project,'q10') for i,project in enumerate(projects)]
        specs += [('q'+str(10+i).zfill(2),project,'q12') for i,project in enumerate(projects)]
        specs += [('q'+str(13+i).zfill(2),project,'q15') for i,project in enumerate(projects)]
        specs += [('q16',projects[0],'q08'),('q17',projects[1],'q17'),('q18',projects[2],'q18')]
    definitions={q[0]:q for q in QUESTIONS}
    return [{'qid':qid,'project':project,'source_qid':source,'label':definitions[source][1],
             'kind':definitions[source][2],'key':definitions[source][3],'type':definitions[source][4],
             'group':definitions[source][5]} for qid,project,source in specs]


def planned_answers(records,projects,plan,policy='ledger'):
    states={project:recover(records,project,policy) for project in projects}
    return {q['qid']:states[q['project']][q['source_qid']] for q in plan}


def query(projects,records,condition,plan):
    prompt=RULES+'\n请恢复项目 '+', '.join(projects)+' 的研究登记事实。所有当前问题都指历史结束后的有效状态。\n'
    prompt+='\n'.join(q['qid']+'：'+('['+q['project']+'] ' if len(projects)>1 else '')+q['label'] for q in plan)
    prompt+='\n不要求证明、计算或交付文件。请按q01至q18回答，值用字符串或null。\n'
    prompt+='两种合法格式任选：扁平JSON对象，或每行 q01 = 值；null不加引号。不要添加长解释。\n'
    if condition=='open_book':
        prompt+='下面重给相同顺序的完整历史记录，用于读懂记录与格式的对照，不是整理好的答案：\n'
        prompt+='\n'.join('RECORD='+json.dumps(r,ensure_ascii=False) for r in records)
    return prompt


def build(seed=20261011):
    cases,gold=[],{}
    for family in FAMILIES:
        for level in ('low','high'):
            if family=='combined':projects,records,loads=combined_history(seed,level)
            else:
                project,records,loads=history(seed,family,level)
                projects=[project]
            plan=plan_for(projects)
            expected=planned_answers(records,projects,plan)
            for condition in ('memory','open_book','no_history'):
                shown=records if condition!='no_history' else [r for r in records if r['project'] not in projects]
                caseid='research-v3-'+family+'-'+level+'-'+condition
                sessions=[{'day':i,'session':'s'+str(i),'prompt':'请保存这份完整研究记录到后续独立会话，不计算、不推导。最终查询会明确给出记录处理规则。\nRECORD='+json.dumps(r,ensure_ascii=False)}
                          for i,r in enumerate(shown)]
                sessions.append({'day':len(shown),'session':'final','prompt':query(projects,shown,condition,plan)})
                cases.append({'id':caseid,'family':family,'level':level,'condition':condition,'project':projects[0],
                              'target_projects':projects,'query_plan':plan,
                              'sessions':sessions,'loads':loads,'synthetic':True})
                gold[caseid]=expected if condition!='no_history' else {q[0]:None for q in QUESTIONS}
    return cases,gold


def reference(case,policy='ledger'):
    records=[]
    for session in case['sessions']:
        if policy=='stateless' and session is not case['sessions'][-1]: continue
        for line in session['prompt'].splitlines():
            if line.startswith('RECORD='): records.append(strict_json(line[7:]))
    # open_book repeats the exact history; deduplicate record IDs while preserving order.
    unique={}
    for r in records: unique.setdefault(r['id'],r)
    return planned_answers(list(unique.values()),case['target_projects'],case['query_plan'],
                           'ledger' if policy=='stateless' else policy)


def parse_response(text):
    if not isinstance(text,str) or len(text)>100000: raise ValueError('Response must be bounded text')
    text=text.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```',text,re.DOTALL)
    if fenced: text=fenced.group(1)
    if text.startswith('{'):
        answers=strict_json(text)
        if not isinstance(answers,dict): raise ValueError('JSON answer must be object')
        return answers,'json'
    answers={}
    for line in text.splitlines():
        m=re.fullmatch(r'\s*(q\d{2})\s*[:=]\s*(.*?)\s*',line)
        if not m or m[1] in answers: raise ValueError('Invalid/duplicate key-value row')
        value=m[2]
        if value=='null': value=None
        elif value.startswith('"'): value=strict_json(value)
        answers[m[1]]=value
    if not answers: raise ValueError('Empty answer')
    return answers,'key_value'


def same(expected,actual,qid,typ):
    if expected is None: return actual is None
    if typ=='rational':
        if type(actual) not in (str,int) or len(str(actual))>200: return False
        value=str(actual).strip()
        if not re.fullmatch(r'(?:[+-]?\d+/[+-]?\d+|[+-]?(?:\d+(?:\.\d*)?|\.\d+))',value): return False
        try: return Fraction(expected)==Fraction(value)
        except (ValueError,ZeroDivisionError): return False
    return isinstance(actual,str) and actual.strip() in ALIASES.get(qid,[expected])


def grade(case,expected,text,error=None):
    parsed,mode,problem=None,None,None
    if not error:
        try: parsed,mode=parse_response(text)
        except (ValueError,TypeError,RecursionError) as exc: problem=str(exc)
    rows=[]
    for q in case['query_plan']:
        qid,typ,group=q['qid'],q['type'],q['group']
        reason=None
        if error: status='error';reason='execution_error'
        elif parsed is None: status='unknown';reason='unparseable_response'
        elif qid not in parsed: status='unknown';reason='missing_field'
        elif parsed[qid] is not None and (type(parsed[qid]) not in (str,int) or
                                         (typ=='text' and not isinstance(parsed[qid],str))):
            status='unknown';reason='invalid_field_type'
        else:
            status='pass' if same(expected[qid],parsed[qid],q['source_qid'],typ) else 'fail'
            reason='correct' if status=='pass' else ('omission' if parsed[qid] is None else 'wrong_record_value')
        rows.append({'qid':qid,'group':group,'status':status,'reason':reason})
    observed=sum(r['status'] in ('pass','fail') for r in rows)
    correct=sum(r['status']=='pass' for r in rows)
    return {'case':case['id'],'condition':case['condition'],'format':mode,
            'format_error':problem,'execution_error':error,
            'extra_fields':sorted(set(parsed)-{q[0] for q in QUESTIONS}) if parsed is not None else [],
            'check_count':18,'observed_count':observed,'correct_count':correct,
            'coverage':observed/18,'correct_over_all':correct/18,
            'correct_over_observed':correct/observed if observed else None,'checks':rows,
            'primary_memory_eligible':case['condition']=='memory',
            'claim_limit':'Reference/offline or external-answer scoring; no proof of native-agent difficulty'}


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def answer_trace(case,expected):
    records=[]
    for session in case['sessions'][:-1]:
        for line in session['prompt'].splitlines():
            if line.startswith('RECORD='): records.append(strict_json(line[7:]))
    traces={}
    for q in case['query_plan']:
        qid,kind,key=q['qid'],q['kind'],q['key']
        target=[r for r in records if r['project']==q['project'] and r['status']=='accepted']
        state,_,_=view(records,q['project'])
        matches=[]
        value=expected[qid]
        if value is None:
            if kind=='hint':
                matches=[r['id'] for r in target if r['kind']=='patch' and r['payload'].get('hint_permission') is False]
            reason='withdrawn_by_record' if matches else 'not_provided_for_target'
        else:
            for r in target:
                if kind=='revision' and r.get('revision')==value: matches.append(r['id'])
                elif kind=='historical' and r.get('checkpoint')=='C0' and r['payload'].get(key)==value: matches.append(r['id'])
                elif kind=='adoption' and r['payload'].get('adoption',{}).get(key)==value: matches.append(r['id'])
                elif kind=='lemma' and r['kind']=='lemma' and r['payload'].get(key)==value and all(
                     r['payload'].get(k)==state.get('adoption',{}).get(k) for k in ('lemma_id','edition','regime')): matches.append(r['id'])
                elif kind=='field' and r['kind']=='patch' and r['payload'].get(key)==value: matches.append(r['id'])
            reason='literal_from_record_with_declared_selection_rules'
            if not matches: raise AssertionError('Answer requires unstated inference: '+qid)
        traces[qid]={'value':value,'supporting_literal_records':matches,'reason':reason}
    return traces


def native_dataset(cases,gold):
    result=[]
    for c in cases:
        steps=[]
        for i,s in enumerate(c['sessions']):
            final=i==len(c['sessions'])-1
            checks=[{'id':qid,'source':'response','op':'equals','pointer':'/'+qid,
                     'value':gold[c['id']][qid],'failure':'wrong_reuse','measurement_domain':'content'}
                    for qid,*_ in QUESTIONS] if final else []
            steps.append({'id':'final' if final else 'note'+str(i),'session':s['session'],'day':s['day'],
                          'kind':'probe' if final else 'message','prompt':s['prompt'],'checks':checks})
        result.append({'schema_version':'1.0','id':c['id'],'title':c['id'],'dimension':FAMILIES[c['family']][4],
                       'synthetic':True,'steps':steps,'research_condition':c['condition'],'research_level':c['level'],
                       'research_family':c['family'],'score_note':'Core strict-JSON equality is supplemental; primary V3 semantic grading is separate and preserved.'})
    return result


def write_viewer(output,cases,gold,results):
    payload=json.dumps({'cases':cases,'gold':gold,'questions':QUESTIONS,'families':FAMILIES},ensure_ascii=False).replace('</','<\\/')
    table=''.join('<tr><td>'+policy+'</td>'+''.join('<td>'+str(sum(r['correct_count'] for r in results if r['policy']==policy and r['condition']==condition))+'/'+str(sum(r['check_count'] for r in results if r['policy']==policy and r['condition']==condition))+'</td>' for condition in ('memory','open_book','no_history'))+'</tr>' for policy in POLICIES)
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>研究档案记忆 V3</title>
<style>body{font:16px/1.65 sans-serif;color:#1c3041;max-width:1150px;margin:25px auto;padding:18px}select,button{font:inherit;margin:6px;padding:7px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2f7;padding:14px}details{margin:8px 0}table{border-collapse:collapse;width:100%}td,th{padding:7px;border:1px solid #c8d1db}aside{background:#fff3d5;padding:12px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}@media(max-width:800px){.columns{display:block}}</style>
<h1>研究档案记忆：恢复记录，不做数学题</h1><p>数学研究场景中的相近项目、分散修订、指定引理版本、旧检查点和选择性取消。所有答案由记录明确给出。</p>
<aside>这是一版设计与离线原型。未调用付费模型；人工参考策略结果只检查预设故障能否被识别，尚未验证真实难度或排名。</aside>
<p><a href="../memory-v3-design.md">完整设计说明</a> · <a href="inputs.jsonl">只含题目输入</a> · <a href="gold.json">评分端答案</a> · <a href="protocol.json">冻结规则与指纹</a></p>
<label>任务 <select id="family"></select></label><label>负载 <select id="level"><option value="high">高</option><option value="low">低</option></select></label>
<label>资料条件 <select id="condition"><option value="memory">历史记忆</option><option value="open_book">最后重给完整原始记录</option><option value="no_history">目标资料未提供</option></select></label>
<p id="stats"></p><div class="columns"><section><h2>此前独立会话</h2><div id="notes"></div></section><section><h2>最终查询</h2><pre id="query"></pre><button id="reveal">展开评分端答案</button><pre id="gold" hidden></pre></section></div>
<h2>人工策略检查</h2><p>表内是正确项/全部18项的合计。资料缺失组单独检验拒绝编造，不混入历史记忆分数。</p><table><tr><th>预设策略</th><th>历史组</th><th>完整记录组</th><th>缺资料组</th></tr>'''+table+'</table>'
    page+='<script id="data" type="application/json">'+payload+'</script>'
    page+='''<script>const D=JSON.parse(document.getElementById('data').textContent);const F=document.getElementById('family'),L=document.getElementById('level'),C=document.getElementById('condition');for(const[k,v]of Object.entries(D.families)){const o=document.createElement('option');o.value=k;o.textContent=v[0];F.append(o)}F.value='combined';function draw(){const c=D.cases.find(c=>c.family===F.value&&c.level===L.value&&c.condition===C.value);document.getElementById('stats').textContent=`${c.id}；${c.sessions.length-1}个历史会话；每例查询18项。负载：${JSON.stringify(c.loads)}`;const n=document.getElementById('notes');n.replaceChildren();for(const[s,i]of c.sessions.slice(0,-1).map((s,i)=>[s,i])){const d=document.createElement('details'),t=document.createElement('summary'),p=document.createElement('pre');t.textContent=`会话${i+1}：${s.session}`;p.textContent=s.prompt;d.append(t,p);n.append(d)}document.getElementById('query').textContent=c.sessions.at(-1).prompt;const g=document.getElementById('gold');g.textContent=JSON.stringify(D.gold[c.id],null,2);g.hidden=true;}for(const e of[F,L,C])e.addEventListener('change',draw);document.getElementById('reveal').addEventListener('click',()=>{const g=document.getElementById('gold');g.hidden=!g.hidden});draw();</script></html>'''
    (output/'index.html').write_text(page,encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('experiments/math_memory/memory-v3'))
    p.add_argument('--seed',type=int,default=20261011)
    p.add_argument('--grade-case');p.add_argument('--answer',type=Path)
    args=p.parse_args()
    if args.grade_case:
        protocol=strict_json((args.output/'protocol.json').read_text())
        for name,sha in protocol['data_sha256'].items():
            if hashlib.sha256((args.output/name).read_bytes()).hexdigest()!=sha: p.error('Frozen data changed: '+name)
        cases=[strict_json(line) for line in (args.output/'inputs.jsonl').read_text().splitlines()]
        case=next((c for c in cases if c['id']==args.grade_case),None)
        if case is None or args.answer is None: p.error('Valid --grade-case and --answer required')
        print(json.dumps(grade(case,strict_json((args.output/'gold.json').read_text())[case['id']],args.answer.read_text()),ensure_ascii=False,indent=2));return
    args.output.mkdir(parents=True,exist_ok=False)
    cases,gold=build(args.seed)
    inputs=args.output/'inputs.jsonl'
    inputs.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf-8')
    dump(args.output/'gold.json',gold)
    dump(args.output/'answer-trace.evaluator.json',{c['id']:answer_trace(c,gold[c['id']]) for c in cases})
    native=args.output/'native-dataset.evaluator.jsonl'
    native.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in native_dataset(cases,gold)),encoding='utf-8')
    from kylin_memory_bench.dataset import load_dataset
    load_dataset(native)
    results=[]
    for policy in POLICIES:
        for case in cases:
            results.append({'policy':policy,**grade(case,gold[case['id']],json.dumps(reference(case,policy)))})
    dump(args.output/'reference-results.json',results)
    protocol={'version':3,'status':'offline-design-not-native-validated','seed':args.seed,'cases':36,'checks_per_case':18,
              'design':'6 families x 2 loads x 3 information conditions','paid_calls':0,
              'query_spec':QUESTIONS,'combined_query_plan':next(c['query_plan'] for c in cases if c['family']=='combined'),
              'accepted_aliases':ALIASES,'numeric_formats':['integer','fraction','finite_decimal_string'],
              'primary_memory_conditions':['memory'],'separate_conditions':['open_book','no_history'],
              'rules':RULES,'inference':'Record selection and bookkeeping only; no math derivation. Open-book controls rule reading, not internal memory mechanism.',
              'difficulty_gate':{'open_book_correct_over_all':0.95,'effective_observation':0.90,
                                 'pure_family_load_effects':3,'drop_pp':15,'repeats':3,'consistent_rounds':2,
                                 'note':'Predeclared descriptive targets; combined is excluded from independent load-effect count. No claim these targets are achieved.'},
              'data_sha256':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in
                             (inputs,args.output/'gold.json',native,args.output/'answer-trace.evaluator.json')},
              'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'runner_note':'Native dataset contains evaluator checks. Send only step.prompt, never complete cases, gold, reference results or this viewer.'}
    dump(args.output/'protocol.json',protocol)
    write_viewer(args.output,cases,gold,results)
    print(json.dumps({'cases':len(cases),'reference_trials':len(results),'checks':len(results)*18,
                      'ledger_all_pass':all(r['correct_count']==18 for r in results if r['policy']=='ledger'),
                      'max_history_sessions':max(len(c['sessions'])-1 for c in cases),'paid_calls':0},ensure_ascii=False))


if __name__=='__main__':main()
