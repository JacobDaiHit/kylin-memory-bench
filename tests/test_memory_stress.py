import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kylin_memory_bench.common import BenchError, digest, read_json
from kylin_memory_bench.runner import execute, read_run
from experiments.memory_stress import oracle, suite
from experiments.memory_stress.calibrate_stress import evidence_match, grade, grouped_summary, paired_summary, quality
from experiments.memory_stress.reference_adapter import parse_records, parse_question, short_answer, turn
from experiments.memory_stress.render_history import EXPRESSIONS, render_event, parse_event, render_query
from experiments.memory_stress.world_generator import VARIANTS, development_worlds, transform

ROOT=Path(__file__).resolve().parents[1]


def assertion(eid,value,scope='test',status='accepted',checkpoint=None,branch=None):
    row={'id':eid,'kind':'assert','subject':'P','scope':scope,'status':status,'label':'v9','fields':{'d1':value}}
    if branch is not None:row['fields']['branch']=branch
    if checkpoint is not None:row['checkpoint']=checkpoint
    return row


def manual_world():
    # Hand-written expected states, independent of the procedural generator.
    events=[assertion('e1',7,checkpoint='past',branch='A'),assertion('e2',11),
            assertion('prod',101,scope='production'),assertion('e3',19,branch='B'),
            {'id':'undo','kind':'cancel','subject':'P','scope':'test','status':'accepted','label':'v2',
             'target_id':'e3','fields':['d1']},assertion('proposal',23,status='draft')]
    queries=[{'id':'now','subject':'P','path':[{'scope':'test','key':'d1'}]},
             {'id':'branch','subject':'P','path':[{'scope':'test','key':'branch'}]},
             {'id':'past','subject':'P','path':[{'scope':'test','key':'d1'}],'at':'past'},
             {'id':'prod','subject':'P','path':[{'scope':'production','key':'d1'}]}]
    return {'events':events,'queries':queries}


class StressOracleTests(unittest.TestCase):
    def test_selective_cancel_scope_and_historical_state(self):
        world=manual_world();oracle.validate_world(world)
        self.assertEqual(oracle.answers(world),{'now':11,'branch':'B','past':7,'prod':101})
        self.assertEqual(oracle.answers(world,policy='ignore_cancel')['now'],19)
        self.assertEqual(oracle.answers(world,policy='accept_draft')['now'],23)
        self.assertEqual(oracle.answers(world,policy='scope_blind')['now'],101)

    def test_bad_cross_scope_or_forward_cancel_is_rejected(self):
        for index,field,value in ((4,'scope','production'),(4,'target_id','proposal')):
            world=manual_world();world['events'][index][field]=value
            with self.assertRaises(ValueError):oracle.validate_world(world)

    def test_minimal_raw_oracle_keeps_cancel_target_and_branch(self):
        world=manual_world();query=world['queries'][0]
        proof=oracle.evidence(world,query)
        self.assertEqual(proof['required_groups'],[['e2'],['undo']])
        self.assertEqual(set(proof['sufficient_sets'][0]),{'e2','e3','undo'})
        self.assertEqual(oracle.resolve(world,query,oracle.oracle_records(world,query))['value'],11)
        oracle.validate_world({'events':oracle.oracle_records(world,query),'queries':[query]})

    def test_equivalent_evidence_and_group_deletion(self):
        world={'events':[assertion('a',7),assertion('b',7)],'queries':[{'id':'q','subject':'P','path':[{'scope':'test','key':'d1'}]}]}
        proof=oracle.evidence(world,world['queries'][0])
        self.assertEqual(set(map(tuple,proof['sufficient_sets'])),{('a',),('b',)})
        self.assertEqual(proof['required_group_count'],1)
        for eid in ('a','b'):
            self.assertTrue(evidence_match(proof,[eid],True,True)['sufficient'])
            self.assertEqual(oracle.answers(world,[e for e in world['events'] if e['id']!=eid])['q'],7)
        self.assertIsNone(oracle.answers(world,[])['q'])
        self.assertEqual(evidence_match(proof,['a'])['status'],'unknown')


class StressGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds=development_worlds()
        cls.audit=quality(cls.worlds)

    def test_thirty_independent_histories_fixed_loads(self):
        self.assertEqual(len({w['seed'] for w in self.worlds}),30)
        self.assertEqual(self.audit['expression_roundtrips'],5760)
        self.assertEqual(self.audit['paired_relations_checked'],150)
        for family in ('multihop','updates'):
            for tier in ('low','medium','high'):
                selected=[w for w in self.worlds if w['family']==family and w['tier']==tier]
                self.assertEqual(len(selected),5)
                self.assertTrue(all(len(w['events'])==64 and len(w['queries'])==6 for w in selected))
        # Registry distractor capacity must not covary with the update count.
        registries=[sum(e['scope']=='registry' for e in w['events']) for w in self.worlds if w['family']=='updates']
        self.assertEqual(set(registries),{33})

    def test_random_final_values_no_constant_shortcut(self):
        values=[]
        for w in self.worlds:
            if w['family']=='updates':
                q=next(q for q in w['queries'] if q['role']=='current')
                values.append(oracle.resolve(w,q)['value'])
        self.assertNotIn(2,values);self.assertNotIn(3,values)
        self.assertGreater(len(set(values)),12)
        all_dirs=[oracle.resolve(w,next(q for q in w['queries'] if q['role']=='primary'))['value'] for w in self.worlds]
        self.assertEqual(len(set(all_dirs)),30)

    def test_counterfactual_and_invariance_pairs_grouped(self):
        for w in self.worlds:
            primary=next(q for q in w['queries'] if q['role']=='primary')
            base=oracle.answers(w)
            for variant in VARIANTS[1:]:
                edited=transform(w,variant)
                changes=[(a,b) for a,b in zip(w['events'],edited['events']) if a!=b]
                self.assertEqual(edited['split_group'],w['split_group'])
                self.assertEqual(edited['split'],'development')
                if variant=='fact_edit':
                    self.assertEqual(len(changes),1)
                    a,b=changes[0];self.assertEqual(set(k for k in a if a[k]!=b[k]),{'fields'})
                    self.assertEqual(sum(a['fields'][k]!=b['fields'][k] for k in a['fields']),1)
                if variant=='approval_swap':
                    self.assertEqual(len(changes),2)
                    self.assertTrue(all(set(k for k in a if a[k]!=b[k])=={'status'} for a,b in changes))
                if variant in ('fact_edit','approval_swap'):
                    self.assertNotEqual(oracle.answers(edited)[primary['id']],base[primary['id']])
                else:self.assertEqual(oracle.answers(edited),base)

    def test_real_evidence_load_and_ablations(self):
        for w in self.worlds:
            q=next(q for q in w['queries'] if q['role']=='primary')
            proof=oracle.evidence(w,q)
            expected=w['loads']['hop_count'] if w['family']=='multihop' else 5
            self.assertEqual(proof['required_group_count'],expected)
            for group in proof['required_groups']:
                reduced=[r for r in w['events'] if r['id'] not in group]
                self.assertNotEqual(oracle.resolve(w,q,reduced)['value'],proof['answer'])
            for support in proof['sufficient_sets']:
                self.assertEqual(oracle.resolve(w,q,[r for r in w['events'] if r['id'] in support])['value'],proof['answer'])

    def test_all_three_expression_roundtrips_and_independent_question_readback(self):
        for w in self.worlds:
            for expr in EXPRESSIONS:
                rows=[]
                for event in w['events']:
                    text=render_event(event,expr)
                    self.assertEqual(parse_event(text,expr),event)
                    if expr!='structured':self.assertNotIn('EVENT=',text)
                    rows.extend(parse_records(text))
                for q in w['queries']:
                    question=parse_question(render_query(q,expr))
                    self.assertNotIn('path',question)
                    self.assertEqual(short_answer(rows,question),oracle.resolve(w,q)['value'])

    def test_no_history_has_same_sessions_and_all_null(self):
        for w in self.worlds:
            masked=oracle.without_query_history(w)
            self.assertEqual(len(masked),64)
            self.assertEqual(set(oracle.answers(w,masked).values()),{None})

    def test_case_controls_short_gold_and_opaque_ids(self):
        for w in self.worlds:
            q=next(q for q in w['queries'] if q['role']=='primary')
            memory,meta=suite.build_case(w,q['id'])
            self.assertEqual(len(memory['steps']),65)
            self.assertEqual(memory['steps'][-1]['checks'][0]['value'],{'answer':meta['expected']})
            for condition in suite.CONDITIONS:
                case,metadata=suite.build_case(w,q['id'],condition)
                self.assertNotIn(condition,case['id'])
                self.assertNotIn(w['family'],case['id'])
                self.assertEqual(len({s['session'] for s in case['steps']}),65)
                self.assertEqual(case['state_policy'],'fresh_each_session' if condition in ('stateless','open_book','oracle_evidence') else 'persistent')
                if condition!='no_history':
                    self.assertEqual([s['prompt'] for s in case['steps'][:-1]],[s['prompt'] for s in memory['steps'][:-1]])
                    self.assertEqual(metadata['expected'],meta['expected'])
                if condition=='stateless':self.assertEqual(case['steps'][-1]['prompt'],memory['steps'][-1]['prompt'])
                if condition=='oracle_evidence':
                    final_rows=parse_records(case['steps'][-1]['prompt'])
                    self.assertEqual(short_answer(final_rows,parse_question(case['steps'][-1]['prompt'])),meta['expected'])
                    self.assertLess(len(final_rows),12)

    def test_negative_oracle_does_not_signal_null_with_empty_context(self):
        w=self.worlds[0];q=next(q for q in w['queries'] if q['role']=='abstention')
        case,meta=suite.build_case(w,q['id'],'oracle_evidence')
        self.assertEqual(len(parse_records(case['steps'][-1]['prompt'])),64)
        self.assertFalse(meta['proof']['positive_evidence_observable'])


class StressContractTests(unittest.TestCase):
    def test_supplemental_score_does_not_call_wrong_content_a_format_failure(self):
        from kylin_memory_bench.scoring import evaluate
        w=development_worlds()[0];q=next(q for q in w['queries'] if q['role']=='primary')
        case,_=suite.build_case(w,q['id'])
        contract,shape=case['steps'][-1]['checks']
        event={'event_id':'1','response':{'text':'{"answer":"incorrect-directory"}'}}
        self.assertEqual(evaluate(contract,event)['category'],'confusion')
        self.assertEqual(evaluate(shape,event)['status'],'pass')
        event['response']['text']='{"answer":"incorrect-directory","extra":1}'
        self.assertEqual(evaluate(shape,event)['category'],'invalid_format')

    def test_content_and_format_frozen_negative_cases(self):
        fixtures=[(11,'{"answer":11}','pass','pass'),(11,'{"answer":"11"}','pass','fail'),
                  (11,'{"answer":"011"}','fail','fail'),(11,'{"answer":19}','fail','pass'),
                  (11,'{"answer":true}','unknown','fail'),(11,'{"answer":11.0}','unknown','fail'),
                  (None,'{"answer":null}','pass','pass'),(None,'{"answer":"null"}','fail','fail'),
                  ('x','说明\n```json\n{"answer":"x"}\n```','pass','fail'),
                  ('x','{"answer":"x","extra":1}','pass','fail'),
                  ('x','{"answer":"bad","answer":"x"}','unknown','fail'),
                  ('x','```json\n{"answer":"x"}\n```\n```json\n{"answer":"bad"}\n```','unknown','fail'),
                  ('x',None,'unknown','fail')]
        for expected,text,content,format_state in fixtures:
            with self.subTest(text=text):
                result=grade(expected,text)
                self.assertEqual(result['status'],content)
                self.assertEqual(result['format_status'],format_state)
        result=grade('x','{"answer":"x"}',error='timeout')
        self.assertEqual(result['status'],'error');self.assertFalse(result['observed'])

    def test_group_statistics_do_not_treat_queries_as_independent_histories(self):
        rows=[]
        for scene,results in (('one',[True]*6),('two',[False]*6)):
            for i,passed in enumerate(results):
                rows.append({'agent':'a','condition':'memory','expression':'structured','variant':'base',
                             'family':'updates','tier':'low','scenario_id':scene,'query_role':'current',
                             'grade':grade(11,'{"answer":11}' if passed else '{"answer":7}')})
        stats=grouped_summary(rows)[0]
        self.assertEqual(stats['history_count'],2);self.assertEqual(stats['scheduled_final_slots'],12)
        self.assertEqual(stats['content_success_history_macro'],.5)
        self.assertEqual(stats['cluster_bootstrap_interval'],[0.0,1.0])
        rows[0]['query_role']='primary'
        self.assertEqual(len(grouped_summary(rows)),2)

    def test_pair_requires_both_members_and_keeps_unknown(self):
        base={'agent':'a','trial':0,'condition':'memory','expression':'structured','family':'multihop',
              'tier':'low','scenario_id':'one','query_id':'q','query_role':'primary','variant':'base','grade':grade('x','{"answer":"x"}')}
        edited=dict(base,variant='fact_edit',grade=grade('y',None))
        stats=paired_summary([base,edited])[0]
        self.assertEqual(stats['scheduled_pairs'],1);self.assertEqual(stats['pair_content_success_rate'],0)
        self.assertEqual(stats['unobserved_or_error_pairs'],1)

    def test_incomplete_and_error_runs_keep_all_planned_final_slots(self):
        worlds=development_worlds()[:2];data,catalog=suite.build(worlds,('memory',));cases=data['memory']
        manifest={'agents':[{'id':'a'}],'repeats':2}
        events=[{'agent_id':'a','trial':0,'case_id':cases[0]['id'],'step_id':'l000','error':'timeout'}]
        rows=suite.collect_slots(manifest,cases,events,catalog)
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['grade']['status'],'error')
        self.assertTrue(all(r['grade']['status']=='unknown' for r in rows[1:]))
        stats=grouped_summary(rows)[0]
        self.assertEqual(stats['scheduled_final_slots'],4)
        self.assertEqual(stats['effective_observation_rate'],0)
        self.assertEqual(stats['content_success_history_macro'],0)
        changed=copy.deepcopy(cases);changed[0]['steps'][0]['prompt']='tampered'
        with self.assertRaises(BenchError):suite.collect_slots(manifest,changed,events,catalog)


class StressIntegrationTests(unittest.TestCase):
    def test_prepare_is_deterministic_gold_separated_and_tamper_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a',Path(tmp)/'b'
            pa=suite.prepare(a,conditions=('memory',));pb=suite.prepare(b,conditions=('memory',))
            self.assertEqual(pa,pb);suite.verify_prepared(a)
            learner=[json.loads(s) for s in (a/'learner-memory.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(learner),30)
            self.assertTrue(all(set(c)=={'id','state_policy','sessions'} for c in learner))
            for case in learner:
                for s in case['sessions']:
                    self.assertEqual(set(s),{'session','day','prompt','output_tokens'})
                    self.assertNotIn('expected',s['prompt']);self.assertNotIn('required_groups',s['prompt'])
            with self.assertRaises(BenchError):suite.prepare(a)
            (a/'gold.evaluator.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(BenchError,'fingerprint'):suite.verify_prepared(a)

    def test_actual_runner_uses_only_requests_and_isolates_each_final(self):
        worlds=[next(w for w in development_worlds() if w['family']=='updates' and w['tier']=='high')]
        datasets,catalog=suite.build(worlds)
        cases=[c for v in datasets.values() for c in v]
        requests=[]
        class Replay:
            def turn(self,request):
                requests.append(copy.deepcopy(request));return turn(request)
        config={'schema_version':'1.0','agents':[{'id':'fake','kind':'command','command':['unused']}]}
        with tempfile.TemporaryDirectory() as tmp,patch('kylin_memory_bench.runner.create_adapter',side_effect=lambda *_:Replay()):
            execute(cases,config,Path(tmp)/'run')
            manifest,ran,events,_=read_run(Path(tmp)/'run')
            rows=suite.collect_slots(manifest,ran,events,catalog)
        self.assertEqual(len(requests),325)
        self.assertTrue(all(set(r)=={'protocol_version','session_id','day','prompt','workspace','output_tokens'} for r in requests))
        self.assertEqual({r['condition']:r['grade']['content_task_success'] for r in rows},
                         {'memory':True,'stateless':False,'open_book':True,'oracle_evidence':True,'no_history':True})
        self.assertEqual(len({r['workspace'] for r in requests if '查询：' in r['prompt']}),5)

    def test_real_subprocess_state_retention_and_fresh_workspace(self):
        adapter=ROOT/'experiments/memory_stress/reference_adapter.py'
        command=[sys.executable,'-X','utf8',str(adapter)]
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a',Path(tmp)/'b';a.mkdir();b.mkdir()
            def call(workspace,prompt):
                request={'workspace':str(workspace),'prompt':prompt,'session_id':'s'}
                done=subprocess.run(command,cwd=workspace,input=json.dumps(request),capture_output=True,encoding='utf-8',check=True)
                return json.loads(done.stdout)['text']
            row=assertion('a',143)
            query={'subject':'P','path':[{'scope':'test','key':'d1'}],'goal':'d1'}
            call(a,render_event(row,'dialogue'))
            self.assertEqual(json.loads(call(a,render_query(query,'statement'))),{'answer':143})
            self.assertEqual(json.loads(call(b,render_query(query,'dialogue'))),{'answer':None})

    def test_source_package_includes_suite_and_excludes_mutable_state(self):
        from scripts.build_release import files
        names={name for name,_ in files()}
        self.assertIn('experiments/memory_stress/suite.py',names)
        self.assertIn('experiments/memory_stress/viewer.html',names)
        self.assertFalse(any('/workspaces/' in n or n.endswith('.local.json') for n in names))


if __name__=='__main__':unittest.main()
