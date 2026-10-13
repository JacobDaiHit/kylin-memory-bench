"""Prepare/replay phase two offline. No provider client or paid-model entry point."""
import argparse
import copy
import json
from collections import Counter
from pathlib import Path

from kylin_memory_bench.common import BenchError, canonical, contained, digest, file_digest, read_json, write_json, write_text
from kylin_memory_bench.dataset import validate_case
from kylin_memory_bench.runner import read_run, verify_run
from experiments.memory_stress.calibrate_stress import evidence_match
from experiments.memory_stress.suite import CONDITIONS, presentation
from experiments.memory_stress.world_generator import opaque
from . import CONTRACT
from .calibrate_stress import GRADING_REVISION, action_grade, answer_type, grade, grouped_summary, paired_summary, quality
from .environment import artifact_spec
from .oracle import answers, delivery_spec, evidence, oracle_records, resolve, without_query_history
from .render_history import EXPRESSIONS, RULES, render_event, render_query
from .world_generator import FAMILIES, TIERS, VARIANTS, phase_two_worlds, revised_phase_one_worlds, transform

ROOT = Path(__file__).resolve().parents[3]


def build_case(base, query_id, condition='memory', expression='structured', variant='base'):
    if condition not in CONDITIONS: raise ValueError('Unknown condition')
    world = transform(base,variant); query = next(q for q in world['queries'] if q['id'] == query_id)
    shown_expression = presentation(expression,variant)
    records = without_query_history(world) if condition == 'no_history' else world['events']
    expected = resolve(world,query,records)['value']
    sessions = []
    for i,row in enumerate(records):
        intro = '本会话发生的模拟工具交互如下，请处理这次验收信息。' if world['family'] == 'feedback' else '请按自身机制保存本次档案登记，供后续独立会话使用。'
        prompt = intro+'\n'+render_event(row,shown_expression)
        if i == 0: prompt = RULES+'\n'+prompt
        sessions.append({'id':'l'+str(i).zfill(3),'session':'s'+str(i).zfill(3),'day':i,'kind':'message',
                         'prompt':prompt,'checks':[],'output_tokens':1024})
    final = render_query(query,shown_expression); supplied = []
    if condition in ('open_book','oracle_evidence'):
        supplied = records if condition == 'open_book' else oracle_records(world,query)
        final += '\n以下是按原顺序排列的原始会话材料：\n'+'\n\n'.join(render_event(r,shown_expression) for r in supplied)
    checks = [{'id':'strict-answer','source':'response','op':'json_exact','value':{'answer':expected},'failure':'confusion','measurement_domain':'task_contract'},
              {'id':'answer-fields','source':'response','op':'json_keys','value':['answer'],'failure':'invalid_format','measurement_domain':'format'}]
    spec = delivery_spec(world,query) if expected is not None else None
    candidates = sorted({artifact_spec(query,o)['path'] for o in query['options']}) if query.get('mode') == 'transfer' else []
    if candidates:
        if spec is None:
            checks.extend({'id':'no-file-'+str(i),'source':'artifact','path':path,'op':'absent','failure':'wrong_reuse','measurement_domain':'artifact'} for i,path in enumerate(candidates))
        else:
            checks.extend([
                {'id':'file-exists','source':'artifact','path':spec['path'],'op':'exists','failure':'wrong_reuse','measurement_domain':'artifact'},
                {'id':'file-object','source':'artifact','path':spec['path'],'op':'json_exact','value':spec['content'],'failure':'wrong_reuse','measurement_domain':'artifact'},
                {'id':'file-keys','source':'artifact','path':spec['path'],'op':'json_keys','value':list(spec['content']),'failure':'invalid_format','measurement_domain':'format'},
                {'id':'file-no-cr','source':'artifact','path':spec['path'],'op':'excludes','value':'\r','failure':'invalid_format','measurement_domain':'format'},
                {'id':'write-trace','source':'actions','op':'json_subset','value':{'name':'write_file','arguments':{'path':spec['path']}},'failure':'wrong_reuse','measurement_domain':'actions'}])
    sessions.append({'id':'final','session':'final','day':len(records),'kind':'task' if candidates else 'probe','prompt':final,'checks':checks,'output_tokens':4096})
    contract = world.get('contract', CONTRACT)
    cid = 'stress-'+opaque(contract,world['scenario_id'],query_id,condition,expression,variant)
    dimension = {'multihop':'retrieval','updates':'update','collections':'boundary','feedback':'reuse'}[world['family']]
    case = {'schema_version':'1.0','grading_contract':'1.1','id':cid,'title':cid,'dimension':dimension,'synthetic':True,
            'state_policy':'fresh_each_session' if condition in ('stateless','open_book','oracle_evidence') else 'persistent',
            'score_note':'Supplemental core checks. Primary response content, format, file state and tool visibility are analyzed separately.', 'steps':sessions}
    validate_case(case)
    meta = {k:copy.deepcopy(world[k]) for k in ('scenario_id','split_group','split','family','tier','seed','loads')}
    meta.update(case_id=cid,query_id=query_id,query_role=query['role'],condition=condition,expression=expression,
                rendered_expression=shown_expression,variant=variant,expected=expected,answer_type=answer_type(query),contract=contract,
                proof=evidence(world,query),case_sha256=digest(case),
                history_utf8_bytes=sum(len(s['prompt'].encode('utf-8')) for s in sessions[:-1]),final_utf8_bytes=len(final.encode('utf-8')),
                oracle_raw_record_count=len(supplied),delivery_spec=spec,delivery_candidates=candidates,
                evaluation_track='controlled_transfer' if query.get('mode') == 'transfer' else 'memory_lookup',
                forbidden_files=sorted(set(v for values in query.get('choices',{}).values() for v in values)-set(expected)) if isinstance(expected,list) else [])
    if condition == 'no_history':
        meta['proof'] = {'positive_evidence_observable':False,'sufficient_sets':[],'required_groups':[]}
    return case,meta


def build(worlds,conditions=('memory',),expression='structured',variants=('base',),queries='primary'):
    if queries not in ('primary','all') or len(set(conditions)) != len(conditions) or len(set(variants)) != len(variants): raise ValueError('Duplicate or invalid selection')
    datasets,catalog = {},{}
    for condition in conditions:
        rows = []
        for world in worlds:
            for query in world['queries']:
                if queries == 'primary' and query['role'] != 'primary': continue
                for variant in variants:
                    case,meta = build_case(world,query['id'],condition,expression,variant)
                    if case['id'] in catalog: raise ValueError('Duplicate case identity')
                    rows.append(case); catalog[case['id']] = meta
        datasets[condition] = rows
    return datasets,catalog


def source_fingerprints():
    paths = list(Path(__file__).parent.glob('*.py'))+[Path(__file__).parent/'viewer.html']
    paths.extend(Path(__file__).parent.parent.glob('*.py'))
    paths.extend((ROOT/'kylin_memory_bench').glob('*.py'))
    paths.extend(ROOT/'experiments/math_memory'/name for name in ('memory_v31.py','memory_only.py'))
    return {p.relative_to(ROOT).as_posix():file_digest(p) for p in sorted(set(paths)) if p.is_file()}


def viewer(output,worlds,audit):
    directory = output/'scenes'; directory.mkdir()
    for world in worlds:
        entry = {k:world[k] for k in ('scenario_id','family','tier','split','seed','loads','queries','events')}
        entry['expressions'] = {e:[render_event(r,e) for r in world['events']] for e in EXPRESSIONS}
        entry['questions'] = {e:{q['id']:render_query(q,e) for q in world['queries']} for e in EXPRESSIONS}
        entry['proofs'] = audit['proofs'][world['scenario_id']]
        entry['pairs'] = []
        for variant in VARIANTS[1:]:
            edited = transform(world,variant)
            entry['pairs'].append({'variant':variant,'answers':answers(edited),
                'changes':[{'id':a['id'],'base':a,'edited':b} for a,b in zip(world['events'],edited['events']) if a != b]})
        entry['strategies'] = [r for r in audit['strategies'] if r['scenario_id'] == world['scenario_id']]
        payload = canonical(entry).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        write_text(directory/(world['scenario_id']+'.js'),'window.receiveScene('+payload+');\n')
    catalog = [{k:w[k] for k in ('scenario_id','family','tier','seed','split')} for w in worlds]
    template = (Path(__file__).parent/'viewer.html').read_text(encoding='utf-8')
    revised = worlds[0].get('contract') == 'memory-stress-0.1.1'
    replacements = {'__CATALOG__':canonical(catalog), '__TITLE__':'Memory Stress 0.1.1：30 条修订历史' if revised else 'Memory Stress V2：160 条离线历史',
        '__INTRO__':'两题族 × 三档 × 五条开发历史。修订原有 30 条，并非新增独立样本；没有付费模型成绩。' if revised else '四题族 × 四档负载 × 十条独立历史。128 条开发历史、32 条留出预留历史；没有付费模型成绩。',
        '__DETAIL__':'更新题最后一次有效修改统一放在第 50 条。初始状态、临时补丁、撤销和草稿位置保持不变。每条历史仍为 64 个输入会话。' if revised else '多跳与更新延续原设计，新增集合授权和验收反馈复用。每条历史固定 128 个输入会话；主问题返回一个短目录或方案 ID，反馈题还必须实际生成文件。各档输入字节数仍可能不同。',
        '__FOOTER__':'原件 0.1 保留。修订改变时序与评分契约，不能与旧分数静默合并；小试清单与 reader_only 协议已经预选冻结，尚未执行模型。' if revised else '留出预留采用分组独立种子，与开发部分使用相同题型和模板；公开可复核，不是盲测或未见图结构泛化验证。首次受控迁移来自脚本生成的真实模拟验收反馈；完整行动链由另一条离线控制器验收，成绩分别报告。'}
    for marker,value in replacements.items(): template = template.replace(marker,value)
    write_text(output/'index.html',template)


def prepare(output,seed=None,conditions=('memory',),expression='structured',variants=('base',),queries='primary',cohort='phase2'):
    output = Path(output)
    if output.exists(): raise BenchError('Refuse to overwrite phase-two data')
    if cohort not in ('phase2','revision-v1'): raise ValueError('Unknown cohort')
    revised = cohort == 'revision-v1'; seed = seed if seed is not None else 20261013 if revised else 20261100
    worlds = revised_phase_one_worlds(seed) if revised else phase_two_worlds(seed); audit = quality(worlds)
    datasets,catalog = build(worlds,conditions,expression,variants,queries)
    output.mkdir(parents=True)
    write_text(output/'worlds.evaluator.jsonl',''.join(canonical(w)+'\n' for w in worlds))
    write_json(output/'gold.evaluator.json',{w['scenario_id']:answers(w) for w in worlds})
    write_json(output/'case-catalog.evaluator.json',catalog); write_json(output/'quality.evaluator.json',audit)
    for condition,rows in datasets.items():
        for split in ('development','reserved'):
            selected = [c for c in rows if catalog[c['id']]['split'] == split]
            if not selected: continue
            stem = condition+'-'+split
            write_text(output/('native-'+stem+'.evaluator.jsonl'),''.join(canonical(c)+'\n' for c in selected))
            write_text(output/('learner-'+stem+'.jsonl'),''.join(canonical({'id':c['id'],'state_policy':c['state_policy'],
                        'sessions':[{k:s[k] for k in ('session','day','prompt','output_tokens')} for s in c['steps']]})+'\n' for c in selected))
    viewer(output,worlds,audit)
    if revised: prepare_pilot(output/'pilot',worlds)
    protocol = {'contract':'memory-stress-0.1.1' if revised else CONTRACT,'scoring_revision':GRADING_REVISION,
                'cohort':cohort,'status':'offline_prepared_no_paid_trials','paid_calls':0,'seed':seed,
                'histories':len(worlds),'families':list(FAMILIES[:2] if revised else FAMILIES),'tiers':list(TIERS[:3] if revised else TIERS),
                'histories_per_family_tier':5 if revised else 10,'split_counts':audit['split_counts'],
                'split_scope':'Group-reserved seeds, same task templates; public/reviewable, not blinded or unseen graph-family generalization.',
                'history_sessions':64 if revised else 128,'steps_per_case':65 if revised else 129,'available_queries_per_history':6,'query_selection':queries,
                'conditions_prepared':list(conditions),'conditions_available':list(CONDITIONS),'variants':list(variants),'expression':expression,
                'native_case_counts':{k:len(v) for k,v in datasets.items()},'native_dataset_digests':{k:digest(v) for k,v in datasets.items()},
                'burden_axes':{'multihop':[1,2,4],'updates':[1,3,6]} if revised else {'multihop':[1,2,4,6],'updates':[1,3,6,10],'collections':[2,4,6,8],'feedback':[1,2,4,6]},
                'necessary_groups':{'multihop':[1,2,4],'updates':[5,5,5]} if revised else {'multihop':[1,2,4,6],'updates':[5,5,5,5],'collections':[3,5,7,9],'feedback':[1,2,4,6]},
                'answer_schema':'Question-declared string/integer/string-set, always nullable; format independent of gold value.',
                'action_visibility':'Visible action counts are partial observations; total is null if any planned trace is unavailable.',
                'recency_control':{'last_effective_update_position':50 if revised else 94,'inputs_after_effective_update':14 if revised else 34},
                'isolation':'One final query per independent case; rebuild learning history; no mutable snapshot sharing.',
                'reader_controls':'open_book/oracle_evidence fresh final state with raw records, same historical gold; native isolation still needs verification.',
                'feedback_track':'Controlled transfer from scripted validator experiences; full live chain is a separate offline controller check.',
                'grading':'Response content, format, set precision/recall/forbidden members, real file state, tool visibility and scheduled errors separate.',
                'negative_oracle':'Full raw history for negative probes; unavailable retrieval and tokens remain unknown.',
                'claim_limit':'No native LLM trial, memory ranking, real difficulty effect, human review, time ageing, equal token budgets or final release verified.',
                'source_sha256':source_fingerprints(),
                'data_sha256':{p.relative_to(output).as_posix():file_digest(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    write_json(output/'protocol.json',protocol)
    return protocol


def verify_prepared(directory):
    directory = Path(directory); protocol = read_json(directory/'protocol.json')
    if protocol.get('contract') not in (CONTRACT,'memory-stress-0.1.1'): raise BenchError('Unknown stress contract')
    for name,expected in protocol['data_sha256'].items():
        if file_digest(contained(directory,name)) != expected: raise BenchError('Prepared fingerprint mismatch: '+name)
    if protocol['source_sha256'] != source_fingerprints(): raise BenchError('Phase-two source fingerprint mismatch')
    return protocol


def prepare_pilot(output,worlds):
    """Freeze a selection before any model output; preparation makes no paid calls."""
    selected = [min((w for w in worlds if w['family'] == family and w['tier'] == tier),key=lambda w:w['seed'])
                for family in FAMILIES[:2] for tier in TIERS[:3]]
    datasets,catalog = build(selected,conditions=('memory','oracle_evidence'))
    cases = [c for rows in datasets.values() for c in rows]
    output.mkdir()
    write_text(output/'native.evaluator.jsonl',''.join(canonical(c)+'\n' for c in cases))
    write_text(output/'learner.jsonl',''.join(canonical({'id':c['id'],'state_policy':c['state_policy'],
               'sessions':[{k:s[k] for k in ('session','day','prompt','output_tokens')} for s in c['steps']]})+'\n' for c in cases))
    write_json(output/'case-catalog.evaluator.json',catalog)
    reader,reader_gold = [],{}
    for world in selected:
        query = next(q for q in world['queries'] if q['role'] == 'primary')
        case,meta = build_case(world,query['id'],'oracle_evidence')
        rid = 'reader-'+opaque('reader-only-0.1',world['scenario_id'],query['id'])
        row = {'id':rid,'messages':[{'role':'user','content':case['steps'][-1]['prompt']}], 'output_tokens':4096}
        reader.append(row)
        reader_gold[rid] = {'scenario_id':world['scenario_id'],'split_group':world['split_group'],
                           'answer_type':meta['answer_type'],'expected':meta['expected'],'prompt_sha256':digest(row)}
    write_text(output/'reader-only.learner.jsonl',''.join(canonical(r)+'\n' for r in reader))
    write_json(output/'reader-only.gold.evaluator.json',reader_gold)
    write_json(output/'reader-only.protocol.json',{'contract':'memory-stress-reader-only-0.1','status':'prepared_not_executed',
        'kind':'fixed_reader_raw_oracle_evidence','histories':6,'reader_requests_per_model':6,'historical_agent_turns':0,
        'tools_enabled':False,'reader_model':None,'source_sha256':source_fingerprints(),
        'input_sha256':file_digest(output/'reader-only.learner.jsonl'), 'gold_sha256':file_digest(output/'reader-only.gold.evaluator.json'),
        'claim_limit':'Separate one-shot readability protocol, not a replacement for the five-condition Agent experiment.'})
    protocol = {'contract':'memory-stress-0.1.1','scoring_revision':GRADING_REVISION,'status':'prepared_not_executed','paid_calls':0,
        'kind':'preselected_six_history_native_pilot','selection_rule':'Lowest seed in each family/tier cell, chosen before model outputs',
        'selected_histories':[{k:w[k] for k in ('scenario_id','family','tier','seed','split_group')} for w in selected],
        'agents_planned':['openclaw','hermes'],'agent_configs':None,'model_config':None,'repeats':1,
        'conditions':['memory','oracle_evidence'],'native_cases':12,'planned_final_slots':24,'planned_agent_turns':1560,
        'preflight_pending':['Freeze both native adapter configs and shared model service','Verify native memory health and workspace isolation',
                             'Check cumulative ledger, prices and authorized paid budget'],
        'no_automatic_reruns':True,'claim_limit':'Pilot for readability and failure diagnosis; one history per cell, no ranking or significance.',
        'source_sha256':source_fingerprints(),
        'data_sha256':{p.name:file_digest(p) for p in sorted(output.iterdir()) if p.is_file()}}
    write_json(output/'protocol.json',protocol)


def action_visibility(events):
    """Missing/null traces stay unknown; an empty visible trace is exactly zero."""
    traces = [(e.get('response') or {}).get('actions') if e else None for e in events]
    visible = [trace for trace in traces if isinstance(trace,list)]
    count = sum(len(trace) for trace in visible)
    return {'action_count_visible':count,'action_trace_observed_steps':len(visible),
            'action_trace_unknown_steps':len(events)-len(visible),'action_trace_visibility_rate':len(visible)/len(events) if events else None,
            'total_action_count':count if len(visible) == len(events) else None}


def collect_slots(manifest,cases,events,catalog):
    for case in cases:
        if case['id'] not in catalog or catalog[case['id']]['case_sha256'] != digest(case): raise BenchError('Case outside frozen phase-two catalog')
    index = {}
    for e in events:
        key = (e['agent_id'],e['trial'],e['case_id'],e['step_id'])
        if key in index: raise BenchError('Duplicate evidence slot')
        index[key] = e
    rows = []
    for agent in manifest['agents']:
        for trial in range(manifest['repeats']):
            for case in cases:
                meta = catalog[case['id']]
                current = [index.get((agent['id'],trial,case['id'],s['id'])) for s in case['steps']]
                errors = [e['error'] for e in current if e and e.get('error')]
                incomplete = any(e is None for e in current); final = current[-1]
                text = (final.get('response') or {}).get('text') if final else None
                assessment = grade(meta['expected'],None if incomplete else text,errors[0] if errors else None,meta['forbidden_files'],meta['answer_type'])
                action = action_grade(meta,final,assessment)
                if incomplete or errors: action['whole_task_success'] = False
                rows.append({**copy.deepcopy(meta),'agent':agent['id'],'trial':trial,'grade':assessment,'action':action,
                             'phase':'execution_error' if errors else 'incomplete_evidence' if incomplete else 'final_answer',
                             'final_event_id':final.get('event_id') if final else None,'planned_steps':len(current),'observed_steps':sum(e is not None for e in current),
                             'duration_ms_observed':sum(e.get('duration_ms',0) for e in current if e),
                             **action_visibility(current),
                             'tokens_observed':None,'retrieved_evidence':evidence_match(meta['proof'])})
    return rows


def analyze(prepared,runs,output):
    protocol = verify_prepared(prepared); output = Path(output)
    if output.exists(): raise BenchError('Refuse to overwrite phase-two analysis')
    catalog = read_json(Path(prepared)/'case-catalog.evaluator.json'); rows,sources,fingerprints = [],[],{}
    for run in runs:
        validity = verify_run(run); manifest,cases,events,_ = read_run(run)
        if any(s['run_id'] == manifest['run_id'] for s in sources): raise BenchError('Duplicate run')
        for agent in manifest['agents']:
            value = digest(agent)
            if agent['id'] in fingerprints and fingerprints[agent['id']] != value: raise BenchError('Changed agent configuration; analyze separately')
            fingerprints[agent['id']] = value
        sources.append({'run_id':manifest['run_id'],'status':manifest['status'],'dataset_sha256':manifest['dataset_sha256'],'integrity':validity})
        batch = collect_slots(manifest,cases,events,catalog)
        for row in batch: row['run_id'] = manifest['run_id']
        rows.extend(batch)
    pair_rows = copy.deepcopy(rows)
    for r in pair_rows: r['trial'] = str(r['run_id'])+'/'+str(r['trial'])
    result = {'contract':protocol['contract'],'scoring_revision':GRADING_REVISION,'grader_source_sha256':source_fingerprints(),
              'kind':'stress_run_replay','sources':sources,'prepared_protocol_sha256':file_digest(Path(prepared)/'protocol.json'),
              'rows':rows,'summary':grouped_summary(rows),'paired_summary':paired_summary(pair_rows),'planned_final_slots':len(rows),
              'prepared_native_cases':len(catalog),'distinct_cases_scheduled':len({r['case_id'] for r in rows}),
              'prepared_cases_not_scheduled':len(set(catalog)-{r['case_id'] for r in rows}),
              'claim_limit':'Separate development/reserved and controlled-transfer tracks. No invisible retrieval, input token equality or internal mechanism inferred.'}
    output.mkdir(parents=True); write_json(output/'results.json',result)
    return {'planned_final_slots':len(rows),'runs':len(sources)}


def smoke(output):
    import sys
    from kylin_memory_bench.runner import execute
    output = Path(output)
    if output.exists(): raise BenchError('Refuse to overwrite smoke')
    # Freeze all five controls, but run one development history per family only.
    prepare(output/'prepared',conditions=CONDITIONS)
    worlds = phase_two_worlds(); selected = [next(w for w in worlds if w['family'] == f and w['tier'] == 'extreme' and w['split'] == 'development') for f in FAMILIES]
    datasets,_ = build(selected,conditions=CONDITIONS); cases = [c for values in datasets.values() for c in values]
    config = {'schema_version':'1.0','agents':[{'id':'grammar-replay-v2','label':'Offline software adapter, not an LLM',
              'kind':'command','command':[sys.executable,'-X','utf8',str(Path(__file__).parent/'reference_adapter.py')],'timeout':30}]}
    execute(cases,config,output/'run',jobs=4); analyze(output/'prepared',[output/'run'],output/'analysis')
    result = read_json(output/'analysis/results.json')
    observed = {condition:sum(r['action']['whole_task_success'] for r in result['rows'] if r['condition'] == condition) for condition in CONDITIONS}
    expected = {condition:0 if condition == 'stateless' else 4 for condition in CONDITIONS}
    if observed != expected: raise BenchError('Unexpected software workspace/file control behavior')
    value = {'kind':'offline_grammar_workspace_and_real_file_smoke','passed':True,'paid_calls':0,'histories':4,'cases':20,'events':2580,
             'whole_task_passes_by_condition':observed,'claim_limit':'Programmed grammar adapter; no real LLM/native health, difficulty or ranking.'}
    write_json(output/'smoke.json',value); return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('prepare'); p.add_argument('--output',type=Path,required=True); p.add_argument('--seed',type=int); p.add_argument('--cohort',choices=('phase2','revision-v1'),default='phase2')
    p.add_argument('--conditions',nargs='+',choices=CONDITIONS,default=['memory']); p.add_argument('--expression',choices=EXPRESSIONS,default='structured')
    p.add_argument('--variants',nargs='+',choices=VARIANTS,default=['base']); p.add_argument('--queries',choices=['primary','all'],default='primary')
    p = sub.add_parser('verify-prepared'); p.add_argument('prepared',type=Path)
    p = sub.add_parser('analyze'); p.add_argument('--prepared',type=Path,required=True); p.add_argument('--runs',type=Path,nargs='+',required=True); p.add_argument('--output',type=Path,required=True)
    p = sub.add_parser('smoke'); p.add_argument('--output',type=Path,required=True)
    p = sub.add_parser('chain-smoke'); p.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare(args.output,args.seed,args.conditions,args.expression,args.variants,args.queries,args.cohort)
            result = {k:result[k] for k in ('status','paid_calls','histories','split_counts','native_case_counts')}
        elif args.command == 'verify-prepared': verify_prepared(args.prepared); result = {'valid':True}
        elif args.command == 'analyze': result = analyze(args.prepared,args.runs,args.output)
        elif args.command == 'smoke': result = smoke(args.output)
        else:
            from .chain import smoke as chain_smoke
            result = chain_smoke(args.output)
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (ValueError,OSError) as exc: print(str(exc)); return 2


if __name__ == '__main__': raise SystemExit(main())
