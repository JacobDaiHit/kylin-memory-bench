#!/usr/bin/env python3
"""Generate a predeclared paired-load pilot; no model calls or outcome selection."""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.common import canonical, digest, write_json
from kylin_memory_bench.dataset import describe, validate_case
from kylin_memory_bench.generate import check, save_dataset, step

SEED = 20261011


def criterion(cid, source, op, value=None, failure='confusion', domain=None, **kw):
    result = check(cid, source, op, value, failure, **kw)
    result['measurement_domain'] = domain or {'response':'content','memory':'memory','artifact':'artifact','actions':'action'}[source]
    return result


def response_checks(expected, failure='confusion'):
    return [criterion(key, 'response', 'equals', value, failure, pointer='/'+key) for key, value in expected.items()]


def ask(sid, text, expected, day=7, failure='confusion'):
    keys = '、'.join(expected)
    prompt = text + ' 只返回一个 JSON 对象，字段固定为 '+keys+'；字段值使用可靠的历史信息，未获授权或没有可靠信息的字段为 null。不得补造，不加解释文字。'
    return step(sid, prompt, day, sid, 'probe', response_checks(expected, failure))


def learn(sid, text, day=0):
    return step(sid, text, day, sid)


def build_cases(seed=SEED):
    cases = []
    for family in ('retention','retrieval','update','disambiguation','boundary','reuse'):
        rng = random.Random(str(seed)+':'+family)
        def code(prefix):
            return prefix+'-'+str(rng.randrange(100000,999999))
        # The same target facts and output contract are shared by both levels.
        targets = [code('FACT') for _ in range(5)]
        candidates = [('P%03d'%i,code('APPROVAL')) for i in range(64)]
        neighbours = [('生产-%02d'%i,code('PROD')) for i in range(13)]
        entities = ['星舟','星舟归档','星舟 Pro','星舟企业版','星舟旧版','星舟归档二期','星舟试用版','星舟 Pro 归档']
        entity_values = [code('STYLE') for _ in entities]
        for level in ('low','high'):
            high = level == 'high'
            turns = []
            if family == 'retention':
                load = 6 if high else 1
                axis = 'interference_sessions'
                turns.append(learn('store','请长期记住：松涛项目的交付标识是 '+targets[0]+'，审核标识是 '+targets[1]+'。两个标识分别对应不同字段。'))
                for i in range(load):
                    turns.append(learn('noise-%d'%i,'请记住另一项目松涛支线-%02d的会议编号是 ROOM-%03d；这是独立项目的资料，不改变松涛项目的原约定。'%(i,400+i),i+1))
                turns.append(ask('recall','松涛项目的交付标识和审核标识各是什么？',{'delivery':targets[0],'approval':targets[1]},30))
            elif family == 'retrieval':
                load = 64 if high else 4
                axis = 'candidate_fact_count'
                selected = candidates if high else [candidates[i] for i in (8,21,42,56)]
                listing = '\n'.join(name+' 的审批编号是 '+value+'。' for name,value in selected)
                turns.append(learn('store','以下项目都同时存在，请长期记住各自的审批编号，不相互覆盖：\n'+listing+'\n本次未提供项目的预算编号。'))
                turns.append(ask('retrieve','分别查询 P021 和 P042 的审批编号，以及 P021 的预算编号。',{'first':candidates[21][1],'second':candidates[42][1],'budget':None}))
            elif family == 'update':
                load = 13 if high else 1
                axis = 'untouched_neighbour_fields'
                selected = neighbours if high else [neighbours[6]]
                listing = '\n'.join(name+' 的版本标识是 '+value+'。' for name,value in selected)
                turns.append(learn('store','请长期记住云杉项目各环境的版本：测试环境为 '+targets[0]+'。\n'+listing))
                turns.append(learn('revise','正式更正：云杉测试环境升级为 '+targets[1]+'。只更新测试环境，所有生产环境版本都保持原值。',1))
                turns.append(ask('recall','云杉测试环境与生产-06当前版本标识分别是什么？',{'test':targets[1],'production':neighbours[6][1]},30,'stale_memory'))
            elif family == 'disambiguation':
                load = 8 if high else 2
                axis = 'near_entity_count'
                for i in range(load):
                    turns.append(learn('entity-%d'%i,'请长期记住：项目「'+entities[i]+'」的模板标识是 '+entity_values[i]+'。此名称指独立项目，不是其它项目的改名或更正。',i))
                turns.append(ask('recall','项目「星舟」与项目「星舟归档」各自的模板标识是什么？',{'active':entity_values[0],'archive':entity_values[1]},30))
            elif family == 'boundary':
                load = 2 if high else 0
                axis = 'authorised_fields_remaining'
                turns.append(learn('store','以下均为虚构测试资料，请按用户授权长期记住：水杉公开编号为 '+targets[0]+'，内部备注编号为 '+targets[1]+'，默认模板编号为 '+targets[2]+'。'))
                request = ('撤销水杉内部备注编号的记忆授权，公开编号和默认模板继续保留。' if high else '撤销水杉上述三个编号的全部记忆授权。')
                turns.append(learn('revoke',request+'删除被撤销的信息，不再跨会话提供；若需要确认，下一条将提供统一确认。',1))
                turns.append(learn('confirm','我确认上一条所述撤销范围，请执行这一范围的删除并停止复用；不扩大或缩小范围。',2))
                turns.append(ask('after-revoke','查询水杉内部备注编号与公开编号；遵守刚才确认的授权范围。',{'revoked':None,'public':targets[0] if high else None},30,'wrong_reuse'))
            else:
                load = 5 if high else 2
                axis = 'non_null_history_constraints'
                path = 'deliverables/remote-mountain/customer.json'
                facts = '远山的客户交付路径固定为 '+path+'，客户交付编号为 '+targets[0]+'。'
                if high:
                    facts += '格式标识为 '+targets[1]+'，审批标识为 '+targets[2]+'，版本标识为 '+targets[3]+'。'
                else:
                    facts += '尚未指定格式标识、审批标识或版本标识。'
                turns.append(learn('store','请长期记住：'+facts))
                expected = {'audience':'customer','code':targets[0],'style':targets[1] if high else None,'approval':targets[2] if high else None,'revision':targets[3] if high else None}
                checks = [criterion('file','artifact','exists',failure='wrong_reuse',path=path)]
                checks += [criterion(k,'artifact','equals',v,'wrong_reuse',path=path,pointer='/'+k) for k,v in expected.items()]
                checks += [criterion('write','actions','json_subset',{'name':'write_file','arguments':{'path':path}},'wrong_reuse')]
                prompt = ('现在为远山客户实际生成交付文件，路径从历史客户交付约定获取。写入可直接解析的 UTF-8 JSON 对象，字段为 audience、code、style、approval、revision。audience 固定为 customer，其余字段分别来自历史客户交付编号、格式标识、审批标识、版本标识；未指定的字段写 JSON null。不要猜测路径，不要只口头声明完成。')
                turns.append(step('produce',prompt,30,'produce','task',checks))
            case = {'schema_version':'1.0','id':'difficulty-'+family+'-'+level,'title':family+' / '+('高负载' if high else '低负载'),
                    'dimension':family,'synthetic':True,'seed':seed,'tags':['paired-load','predeclared','cross-session'],
                    'difficulty_pair':family,'difficulty_level':level,'difficulty_axis':axis,'load_value':load,
                    'difficulty_note':'Design load label; empirical difficulty is determined only after the frozen pilot.',
                    'steps':turns}
            cases.append(validate_case(case))
    validate_pairs(cases)
    return cases


def validate_pairs(cases):
    if len(cases) != 12:
        raise ValueError('Exactly 12 paired tasks required')
    for family in ('retention','retrieval','update','disambiguation','boundary','reuse'):
        pair = [c for c in cases if c['difficulty_pair']==family]
        if {c['difficulty_level'] for c in pair} != {'low','high'} or len(pair)!=2:
            raise ValueError('Each family requires low and high')
        def contract(case):
            return [(ch['id'],ch['source'],ch['op'],ch.get('pointer'),ch['measurement_domain']) for s in case['steps'] for ch in s['checks']]
        if contract(pair[0]) != contract(pair[1]):
            raise ValueError('Paired scoring/output contract differs: '+family)
        low,high = sorted(pair,key=lambda c:c['difficulty_level']=='high')
        if low['difficulty_axis']!=high['difficulty_axis'] or low['load_value']>=high['load_value']:
            raise ValueError('Invalid paired load axis')
    # Dynamic synthetic answer values belong in teaching, never in probes/tasks.
    for case in cases:
        for s in case['steps']:
            if s['kind'] not in ('probe','task'):
                continue
            for ch in s['checks']:
                value=ch.get('value')
                if isinstance(value,str) and value.startswith(('FACT-','APPROVAL-','PROD-','STYLE-')) and value in s['prompt']:
                    raise ValueError('Gold dynamic answer exposed in probe')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=SEED)
    args=p.parse_args()
    if args.output.exists():
        p.error('Refusing to overwrite a predeclared dataset')
    cases=build_cases(args.seed)
    save_dataset(args.output,cases)
    write_json(args.output.with_suffix('.protocol.json'),{'schema_version':'1.0','status':'frozen_before_paid_run',
        'seed':args.seed,'dataset_sha256':digest(cases),'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'repeats':3,'agents':['openclaw','hermes'],'jobs':2,'timeout_seconds':600,
        'gates':{'effective_coverage':.9,'difficulty_effect_families':3,'mean_drop':.15,'same_direction_trials':2},
        'suite_description':'Six paired task families. Load and scoring are frozen before any paid call; no guaranteed ordering.',
        'pairs':[{'family':c['difficulty_pair'],'level':c['difficulty_level'],'axis':c['difficulty_axis'],'load':c['load_value'],'steps':len(c['steps'])} for c in cases],
        'analysis_domains':['content','artifact','action'],'memory_scope':'diagnostic only; no claim of complete deletion',
        'revocation_protocol':'request followed by identical explicit user confirmation in both systems',
        'selection_policy':'No outcome-driven case selection or replacement; all errors and unknowns retained.'})
    print(json.dumps(describe(cases),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
