"""Prepare/replay the thirty-history development suite; never call a model."""
import argparse
import copy
import json
from pathlib import Path

from kylin_memory_bench.common import BenchError, canonical, digest, file_digest, read_json, strict_json, write_json, write_text
from kylin_memory_bench.dataset import validate_case
from kylin_memory_bench.runner import read_run, verify_run
from .calibrate_stress import evidence_match, grade, grouped_summary, paired_summary, quality
from .oracle import answers, evidence, oracle_records, resolve, without_query_history
from .render_history import EXPRESSIONS, RULES, render_event, render_query
from .world_generator import VARIANTS, development_worlds, opaque, transform

CONDITIONS = ('memory', 'stateless', 'open_book', 'oracle_evidence', 'no_history')
ROOT = Path(__file__).resolve().parents[2]
CONTRACT = 'memory-stress-0.1'


def presentation(expression, variant):
    if expression not in EXPRESSIONS:
        raise ValueError('Unknown expression')
    return EXPRESSIONS[(EXPRESSIONS.index(expression)+1)%3] if variant=='paraphrase' else expression


def build_case(base_world, query_id, condition='memory', expression='structured', variant='base'):
    if condition not in CONDITIONS:
        raise ValueError('Unknown condition')
    world = transform(base_world, variant)
    query = next(q for q in world['queries'] if q['id']==query_id)
    actual_expression = presentation(expression, variant)
    records = without_query_history(world) if condition=='no_history' else world['events']
    expected = resolve(world, query, records)['value']
    prompts = []
    for i, row in enumerate(records):
        text = '请按自身机制保存这条档案登记，供后续独立会话使用。\n'+render_event(row, actual_expression)
        if i==0:
            text = RULES+'\n'+text
        prompts.append(text)
    final = render_query(query, actual_expression)
    supplied = []
    if condition in ('open_book','oracle_evidence'):
        supplied = records if condition=='open_book' else oracle_records(world,query)
        final += '\n以下是按原顺序排列的原始档案登记：\n'+'\n\n'.join(render_event(r,actual_expression) for r in supplied)
    # Only opaque IDs reach the workspace path. Condition/answerability labels stay in evaluator metadata.
    cid = 'stress-'+opaque(world['scenario_id'], query_id, condition, expression, variant)
    steps = [{'id':'l'+str(i).zfill(3),'kind':'message','session':'s'+str(i).zfill(3),
              'day':i,'prompt':text,'checks':[],'output_tokens':1024} for i,text in enumerate(prompts)]
    steps.append({'id':'final','kind':'probe','session':'final','day':len(records),'prompt':final,
                  'output_tokens':4096,'checks':[
                      {'id':'strict-answer','source':'response','op':'json_exact','value':{'answer':expected},
                       'failure':'confusion','measurement_domain':'task_contract'},
                      {'id':'answer-fields','source':'response','op':'json_keys','value':['answer'],
                       'failure':'invalid_format','measurement_domain':'format'}]})
    case = {'schema_version':'1.0','grading_contract':'1.1','id':cid,'title':cid,
            'dimension':'retrieval' if world['family']=='multihop' else 'update','synthetic':True,
            'score_note':'Core exact task contract and field shape are supplemental. Use stress analyze for independent content, format and planned-slot metrics.',
            'state_policy':'fresh_each_session' if condition in ('stateless','open_book','oracle_evidence') else 'persistent',
            'steps':steps}
    validate_case(case)
    metadata = {k:copy.deepcopy(world[k]) for k in ('scenario_id','split_group','split','family','tier','seed','loads')}
    metadata.update(case_id=cid,query_id=query_id,query_role=query['role'],condition=condition,
                    expression=expression,rendered_expression=actual_expression,variant=variant,
                    expected=expected,proof=evidence(world,query),case_sha256=digest(case),
                    history_utf8_bytes=sum(len(p.encode('utf-8')) for p in prompts),
                    final_utf8_bytes=len(final.encode('utf-8')),oracle_raw_record_count=len(supplied))
    if condition=='no_history':
        metadata['proof'] = {'positive_evidence_observable':False,'sufficient_sets':[], 'required_groups':[],
                             'negative_policy':'Target evidence replaced by neutral records; same 64 input sessions.'}
    return case, metadata


def build(worlds, conditions=CONDITIONS, expression='structured', variants=('base',), queries='primary'):
    if queries not in ('primary','all') or len(set(conditions))!=len(conditions) or len(set(variants))!=len(variants):
        raise ValueError('Invalid or duplicate selection')
    datasets, catalog = {}, {}
    for condition in conditions:
        selected = []
        for world in worlds:
            for query in world['queries']:
                if queries=='primary' and query['role']!='primary':
                    continue
                for variant in variants:
                    case, meta = build_case(world,query['id'],condition,expression,variant)
                    selected.append(case);catalog[case['id']]=meta
        datasets[condition] = selected
    return datasets, catalog


def source_fingerprints():
    paths = list(Path(__file__).parent.glob('*.py'))
    paths.append(Path(__file__).parent/'viewer.html')
    paths.extend(ROOT/'kylin_memory_bench'/name for name in ('common.py','dataset.py','runner.py','scoring.py','adapters.py','native_trace.py'))
    paths.extend(ROOT/'experiments/math_memory'/name for name in ('memory_v31.py','memory_only.py'))
    return {p.relative_to(ROOT).as_posix():file_digest(p) for p in sorted(paths) if p.is_file()}


def write_viewer(output, worlds, audit):
    data = []
    for world in worlds:
        entry = {k:world[k] for k in ('scenario_id','family','tier','seed','loads','queries','events')}
        entry['expressions'] = {expr:[render_event(r,expr) for r in world['events']] for expr in EXPRESSIONS}
        entry['questions'] = {expr:{q['id']:render_query(q,expr) for q in world['queries']} for expr in EXPRESSIONS}
        entry['proofs'] = audit['proofs'][world['scenario_id']]
        entry['pairs'] = []
        for variant in VARIANTS[1:]:
            edited = transform(world,variant)
            changes = [{'id':a['id'],'base':a,'edited':b} for a,b in zip(world['events'],edited['events']) if a!=b]
            entry['pairs'].append({'variant':variant,'answers':answers(edited),'changes':changes})
        data.append(entry)
    payload = canonical({'worlds':data,'strategies':audit['strategies']}).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template = (Path(__file__).parent/'viewer.html').read_text(encoding='utf-8')
    write_text(output/'index.html',template.replace('__STRESS_DATA__',payload))


def prepare(output, seed=20261013, conditions=CONDITIONS, expression='structured', variants=('base',), queries='primary'):
    output=Path(output)
    if output.exists():
        raise BenchError('Refuse to overwrite prepared data')
    worlds=development_worlds(seed)
    audit=quality(worlds)
    datasets,catalog=build(worlds,conditions,expression,variants,queries)
    output.mkdir(parents=True)
    write_text(output/'worlds.evaluator.jsonl',''.join(canonical(w)+'\n' for w in worlds))
    write_json(output/'gold.evaluator.json',{w['scenario_id']:answers(w) for w in worlds})
    write_json(output/'quality.evaluator.json',audit)
    write_json(output/'case-catalog.evaluator.json',catalog)
    for condition,cases in datasets.items():
        write_text(output/('native-'+condition+'.evaluator.jsonl'),''.join(canonical(c)+'\n' for c in cases))
        # Prompt-only copies are reviewable, and do not contain gold or checks.
        write_text(output/('learner-'+condition+'.jsonl'),''.join(canonical({'id':c['id'],'state_policy':c['state_policy'],
                   'sessions':[{k:s[k] for k in ('session','day','prompt','output_tokens')} for s in c['steps']]})+'\n' for c in cases))
    write_viewer(output,worlds,audit)
    protocol={'contract':CONTRACT,'status':'offline_development_only_no_paid_runs','paid_calls':0,'seed':seed,
              'independent_histories':len(worlds),'histories_per_family_tier':5,'history_sessions':64,
              'queries_per_history_available':6,'query_selection':queries,'conditions':list(conditions),
              'expression':expression,'variants':list(variants),'case_count_by_condition':{k:len(v) for k,v in datasets.items()},
              'planned_steps_per_case':65,'native_dataset_digests':{k:digest(v) for k,v in datasets.items()},
              'gold_policy':'Same historical-fact gold for memory/stateless/open_book/oracle_evidence; no_history=null.',
              'grading':'One short answer; content / format / errors / unknown separate; no missing scheduled slot dropped.',
              'isolation':'Rebuild history in each independent query case. No shared writable snapshot or preceding query.',
              'controls':'open_book/oracle_evidence use a fresh final workspace and raw records, not computed answers. Native fresh state needs verified namespace isolation.',
              'split':'All expressions, edits and questions share a development split_group; no held-out evaluation.',
              'difficulty_axes':{'multihop':[1,2,4],'updates':[1,3,6],
                                 'note':'Update registry size fixed (11 keys); update necessary answer-changing groups remain 5, not 1/3/6.'},
              'negative_oracle':'Negative probes use full raw history, with evidence recall unknown.',
              'claim_limit':'No native memory ability, model difficulty, ranking, token budget equality, genuine elapsed time, human review or release readiness verified.',
              'source_sha256':source_fingerprints(),
              'data_sha256':{p.name:file_digest(p) for p in sorted(output.iterdir()) if p.is_file()}}
    write_json(output/'protocol.json',protocol)
    return protocol


def verify_prepared(directory):
    directory=Path(directory)
    protocol=read_json(directory/'protocol.json')
    if protocol.get('contract')!=CONTRACT:
        raise BenchError('Unknown stress protocol')
    for name,expected in protocol['data_sha256'].items():
        if Path(name).name!=name or file_digest(directory/name)!=expected:
            raise BenchError('Prepared data fingerprint mismatch: '+name)
    if protocol['source_sha256']!=source_fingerprints():
        raise BenchError('Stress source fingerprint mismatch; replay with the frozen source revision')
    return protocol


def collect_slots(manifest, cases, events, catalog):
    """Keep every planned final slot, even when a process aborts before the probe."""
    for case in cases:
        meta=catalog.get(case['id'])
        if meta is None or meta['case_sha256']!=digest(case):
            raise BenchError('Run contains a case outside the frozen stress catalog')
    by_slot={}
    for event in events:
        key=(event['agent_id'],event['trial'],event['case_id'],event['step_id'])
        if key in by_slot:
            raise BenchError('Duplicate event slot')
        by_slot[key]=event
    rows=[]
    for agent in manifest['agents']:
        for trial in range(manifest['repeats']):
            for case in cases:
                meta=catalog[case['id']]
                current=[by_slot.get((agent['id'],trial,case['id'],s['id'])) for s in case['steps']]
                final=current[-1]
                errors=[e['error'] for e in current if e and e.get('error')]
                incomplete=any(e is None for e in current)
                failure=errors[0] if errors else None
                text=(final.get('response') or {}).get('text') if final else None
                assessment=grade(meta['expected'],text,failure)
                if incomplete and not failure:
                    assessment=grade(meta['expected'],None)
                rows.append({**copy.deepcopy(meta),'agent':agent['id'],'trial':trial,'grade':assessment,
                             'phase':'execution_error' if failure else 'incomplete_evidence' if incomplete else 'final_answer',
                             'final_event_id':final.get('event_id') if final else None,
                             'observed_steps':sum(e is not None for e in current),'planned_steps':len(current),
                             'duration_ms_observed':sum(e.get('duration_ms',0) for e in current if e),
                             'action_count_observed':sum(len((e.get('response') or {}).get('actions',[])) for e in current if e),
                             'tokens_observed':None,'retrieved_evidence':evidence_match(meta['proof'])})
    return rows


def analyze(prepared, runs, output):
    protocol=verify_prepared(prepared)
    output=Path(output)
    if output.exists():
        raise BenchError('Refuse to overwrite analysis')
    catalog=read_json(Path(prepared)/'case-catalog.evaluator.json')
    rows=[];sources=[];agent_fingerprints={}
    for run in runs:
        valid=verify_run(run)
        manifest,cases,events,_=read_run(run)
        if any(s['run_id']==manifest['run_id'] for s in sources):
            raise BenchError('Same run supplied twice')
        for agent in manifest['agents']:
            fingerprint=digest(agent)
            if agent['id'] in agent_fingerprints and agent_fingerprints[agent['id']]!=fingerprint:
                raise BenchError('Agent configuration changed across runs; analyze separately')
            agent_fingerprints[agent['id']]=fingerprint
        sources.append({'run_id':manifest['run_id'],'dataset_sha256':manifest['dataset_sha256'],
                        'status':manifest['status'],'integrity':valid})
        batch=collect_slots(manifest,cases,events,catalog)
        for row in batch:row['run_id']=manifest['run_id']
        rows.extend(batch)
    # Repeats from distinct runs are separate planned slots, never deduplicated as extra fields.
    pairing_rows=copy.deepcopy(rows)
    for row in pairing_rows:row['trial']=str(row['run_id'])+'/'+str(row['trial'])
    report={'contract':CONTRACT,'kind':'stress_native_run_replay','sources':sources,
            'prepared_protocol_sha256':file_digest(Path(prepared)/'protocol.json'),'rows':rows,
            'summary':grouped_summary(rows),'paired_summary':paired_summary(pairing_rows),
            'planned_final_slots':len(rows),'source_status':protocol['status'],
            'prepared_native_cases':len(catalog),
            'distinct_cases_scheduled':len({r['case_id'] for r in rows}),
            'prepared_cases_not_scheduled':len(set(catalog)-{r['case_id'] for r in rows}),
            'claim_limit':'Development results; no global ranking or proof of a specific internal memory mechanism. Unseen retrieval and token input remain unknown.'}
    output.mkdir(parents=True)
    write_json(output/'results.json',report)
    return {'planned_final_slots':len(rows),'run_count':len(sources),'output':str(output)}


def smoke(output):
    """A small real subprocess test of the record grammar and workspace controls."""
    import sys
    from kylin_memory_bench.runner import execute
    output=Path(output)
    if output.exists():raise BenchError('Refuse to overwrite offline smoke')
    prepare(output/'prepared')
    worlds=development_worlds()
    selected=[next(w for w in worlds if w['family']==f and w['tier']=='high') for f in ('multihop','updates')]
    datasets,catalog=build(selected)
    cases=[c for v in datasets.values() for c in v]
    config={'schema_version':'1.0','agents':[{'id':'grammar-replay','label':'Offline grammar/replay software adapter (not an LLM)',
             'kind':'command','command':[sys.executable,'-X','utf8',str(Path(__file__).parent/'reference_adapter.py')],
             'timeout':30}]}
    execute(cases,config,output/'run',jobs=2)
    analyze(output/'prepared',[output/'run'],output/'analysis')
    report=read_json(output/'analysis/results.json')
    expected={condition:0 if condition=='stateless' else 2 for condition in CONDITIONS}
    observed={condition:sum(r['grade']['content_task_success'] for r in report['rows'] if r['condition']==condition) for condition in CONDITIONS}
    if observed!=expected:
        raise BenchError('Offline grammar/workspace smoke does not match declared control behavior')
    result={'kind':'offline_subprocess_and_state_control_check','passed':True,'paid_calls':0,
            'independent_histories':2,'cases':10,'events':650,'content_passes_by_condition':observed,
            'claim_limit':'Synthetic grammar adapter only; no native health, LLM capability or snapshot-fork validation.'}
    write_json(output/'smoke.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prepare_parser=sub.add_parser('prepare')
    prepare_parser.add_argument('--output',type=Path,required=True)
    prepare_parser.add_argument('--seed',type=int,default=20261013)
    prepare_parser.add_argument('--conditions',nargs='+',choices=CONDITIONS,default=list(CONDITIONS))
    prepare_parser.add_argument('--expression',choices=EXPRESSIONS,default='structured')
    prepare_parser.add_argument('--variants',nargs='+',choices=VARIANTS,default=['base'])
    prepare_parser.add_argument('--queries',choices=['primary','all'],default='primary')
    check_parser=sub.add_parser('verify-prepared')
    check_parser.add_argument('prepared',type=Path)
    analyze_parser=sub.add_parser('analyze')
    analyze_parser.add_argument('--prepared',type=Path,required=True)
    analyze_parser.add_argument('--runs',type=Path,nargs='+',required=True)
    analyze_parser.add_argument('--output',type=Path,required=True)
    smoke_parser=sub.add_parser('smoke')
    smoke_parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='prepare':
            protocol=prepare(args.output,args.seed,args.conditions,args.expression,args.variants,args.queries)
            result={k:protocol[k] for k in ('status','paid_calls','independent_histories','case_count_by_condition')}
        elif args.command=='verify-prepared':
            verify_prepared(args.prepared);result={'valid':True,'scope':'Frozen input and source byte fingerprints; not scientific validity.'}
        elif args.command=='smoke':
            result=smoke(args.output)
        else:
            result=analyze(args.prepared,args.runs,args.output)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,OSError) as exc:
        print(str(exc));return 2


if __name__=='__main__':
    raise SystemExit(main())
