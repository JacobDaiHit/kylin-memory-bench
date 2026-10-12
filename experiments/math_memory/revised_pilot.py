"""Version 2: explicit supersession, small rationals, fresh oracle control."""
import copy
import hashlib
import json
from pathlib import Path
from .math_core import make_inputs, solve
from .prototype import METHOD, SCHEMA, notes, dump
from .native_pilot import SUPPORT

RULE = '''\n版本规则：研究笔记按给出的会话时间顺序到达。
对同一项目，后来到达的accepted snapshot明确替代此前所有accepted snapshot；
draft永不生效。当前来源为B记录、branch记录、最后一份accepted snapshot，按此顺序返回。
每次收到accepted修订，请更新当前版本并注明旧快照已被替代；不要猜测题目设计者意图。
'''


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    project = 'SCHUR-V2-731942'
    sources = [project+'-B', project+'-branch', project+'-v4']
    initial = make_inputs([[1,1],[1,-1]],[4,5],version='v0',sources=sources[:2]+[project+'-v0'])
    current = make_inputs([[1,1],[1,-1]],[2,3],version='v4',sources=sources)
    draft = make_inputs([[1,1],[1,-1]],[7,11],version='v99')
    other = make_inputs([[1,2],[2,1]],[3,5],kappa=2,other=7,version='v4')
    history = notes(project,initial,'v0')+[notes(project,current,'v4')[-1],notes(project,draft,'v99','draft')[-1]]
    noise = '归档项目的三份记录，全部只属于归档项目：\n'+json.dumps(notes(project+'-archive',other,'v4'),ensure_ascii=False)
    selected = [('reasoning-low','memory',4),('reasoning-low','oracle',4),
                ('reasoning-high','memory',6),('reasoning-high','oracle',6),
                ('reasoning-high','no_history',6),('applicability-singular','oracle',6)]
    cases, dataset, gold = [],[],{}
    for profile, condition, order in selected:
        cid = 'math-v2-'+profile+'--'+condition
        inputs = copy.deepcopy(current)
        if profile=='applicability-singular': inputs['D'][0]='0'
        prompts = ([RULE+'\n研究笔记，请可靠保留至后续独立会话：\nRECORD='+json.dumps(r,ensure_ascii=False) for r in history]
                   if condition=='memory' else [])
        prompts.append(RULE+noise if condition!='oracle' else '这是一条无目标参数的准备会话。下次会话会提供研究任务，请等待。')
        prompt = METHOD+RULE+SUPPORT+'\n目标项目：'+project+'；展开至'+str(order)+'阶。\n'
        prompt += '只返回严格JSON，形状：'+json.dumps(SCHEMA,ensure_ascii=False)+'\n'
        prompt += '资料不足inputs=null；方法不适用保留inputs；两种情况下所有系数和证书字段=null。\n'
        prompt += '必须用实际文件工具写入deliverables/research-certificate.json，随后返回同一JSON，不加解释。\n'
        if condition=='oracle': prompt += 'CURRENT_INPUTS='+json.dumps(inputs)+'\n'
        prompts.append(prompt)
        expected = None if condition=='no_history' else inputs
        gold[cid] = {'inputs':expected,'result':solve(expected,order)}
        sessions = [{'day':i,'prompt':p} for i,p in enumerate(prompts)]
        cases.append({'id':cid,'profile':profile,'condition':condition,'order':order,'project':project,'sessions':sessions})
        steps=[]
        for i,s in enumerate(sessions):
            final=i==len(sessions)-1
            steps.append({'id':'final' if final else 'note-'+str(i),'kind':'task' if final else 'message',
                          'day':i,'session':'session-'+str(i),'prompt':s['prompt'],
                          'checks':([{'id':'status','source':'response','op':'equals','pointer':'/result/status',
                                      'value':gold[cid]['result']['status'],'failure':'wrong_reuse'},
                                     {'id':'actual-file','source':'artifact','op':'exists',
                                      'path':'deliverables/research-certificate.json','failure':'wrong_reuse'}] if final else [])})
        dataset.append({'schema_version':'1.0','id':cid,'title':cid,'dimension':'reuse','synthetic':True,'steps':steps,
                        'math_profile':profile,'math_condition':condition,'math_order':order})
    (root/'dataset.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in dataset))
    dump(root/'learner-cases.json',cases);dump(root/'gold.json',gold)
    from kylin_memory_bench.dataset import load_dataset
    load_dataset(root/'dataset.jsonl')
    dump(root/'protocol.json',{'status':'frozen-before-paid-run','version':2,'cases':6,'repeats':1,
         'changes':['Explicit chronological supersession and source order','Two-dimensional Q block with small rationals',
                    'Oracle is a fresh-current-input capability control; histories are not matched'],
         'claim_limit':'Feasibility only; no causal memory attribution, ranking or difficulty gate claim',
         'prior_attempt':'v1 retained in full; stopped after identifying specification ambiguity',
         'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}})


if __name__=='__main__':
    prepare(Path('experiments/math_memory/pilot-v2'))
