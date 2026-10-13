import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kylin_memory_bench.common import BenchError, canonical, read_json
from kylin_memory_bench.runner import execute, read_run
from experiments.memory_stress.suite import verify_prepared as verify_v1
from experiments.memory_stress.v2 import chain, environment, oracle, suite
from experiments.memory_stress.v2.calibrate_stress import action_grade, grade, grouped_summary, quality
from experiments.memory_stress.v2.reference_adapter import parse_question, short_answer, turn
from experiments.memory_stress.v2.render_history import EXPRESSIONS, parse_event, parse_records, render_event, render_query
from experiments.memory_stress.v2.world_generator import FAMILIES, TIERS, VARIANTS, phase_two_worlds, revised_phase_one_worlds, transform

ROOT = Path(__file__).resolve().parents[1]


def row(eid,fields,scope='client',status='accepted'):
    return {'id':eid,'kind':'assert','subject':'P','scope':scope,'status':status,'label':'v10','fields':fields}


class PhaseTwoOracleTests(unittest.TestCase):
    def test_handwritten_global_selection_revoke_and_scope(self):
        events = [row('base',{'pair0':'a','pair1':'c'}),row('replace',{'pair0':'b'}),row('temporary',{'pair1':'d'}),
                  {'id':'undo','kind':'cancel','subject':'P','scope':'client','status':'accepted','target_id':'temporary','fields':['pair1']},
                  row('draft',{'pair0':'a'},status='draft'),row('production',{'pair0':'a','pair1':'d'},scope='production')]
        options = [{'id':'alpha','values':{'pair0':'a','pair1':'c'}},{'id':'beta','values':{'pair0':'b','pair1':'c'}},
                   {'id':'gamma','values':{'pair0':'b','pair1':'d'}}]
        query = {'id':'q','subject':'P','path':[{'scope':'client','key':'pair0'}],'mode':'selection','goal':'plan',
                 'required_fields':['pair0','pair1'],'provided':{},'choices':{'pair0':['a','b'],'pair1':['c','d']},'options':options}
        world = {'events':events,'queries':[query]}; oracle.validate_world(world)
        self.assertEqual(oracle.resolve(world,query)['value'],'beta')
        self.assertEqual(oracle.resolve(world,dict(query,goal='files'))['value'],['b','c'])
        self.assertEqual(oracle.resolve(world,query,policy='ignore_cancel')['value'],'gamma')
        self.assertEqual(oracle.resolve(world,query,policy='accept_draft')['value'],'alpha')
        proof = oracle.evidence(world,query)
        self.assertIn(['undo'],proof['required_groups'])
        self.assertEqual(oracle.resolve(world,query,oracle.oracle_records(world,query))['value'],'beta')

    def test_current_constraints_reduce_historical_requirement_without_guessing(self):
        query = {'subject':'P','path':[{'scope':'client','key':'pair0'}],'mode':'selection','goal':'plan',
                 'required_fields':['pair0'],'provided':{'pair1':'c'},'choices':{'pair0':['a','b'],'pair1':['c','d']},
                 'options':[{'id':'a','values':{'pair0':'a','pair1':'c'}},{'id':'b','values':{'pair0':'b','pair1':'c'}}]}
        world = {'events':[row('one',{'pair0':'b'})],'queries':[dict(query,id='q')]}
        self.assertEqual(oracle.resolve(world,query)['value'],'b')
        self.assertIsNone(oracle.resolve(world,query,[])['value'])

    def test_feedback_authority_is_distinct_from_accepting_the_submission(self):
        first = row('approved',{'directory':'delivery/a'},scope='experience')
        first.update(kind='feedback',interaction={'tool':'simulated_delivery_validator','component':'directory','submitted':'delivery/wrong','result':'rejected'})
        draft = copy.deepcopy(first); draft.update(id='draft',status='draft',fields={'directory':'delivery/b'})
        query = {'id':'q','subject':'P','path':[{'scope':'experience','key':'directory'}],'goal':'directory','mode':'lookup'}
        world = {'events':[first,draft],'queries':[query]}; oracle.validate_world(world)
        self.assertEqual(oracle.answers(world),{'q':'delivery/a'})
        self.assertEqual(oracle.answers(world,policy='accept_draft'),{'q':'delivery/b'})
        invalid = copy.deepcopy(world); invalid['events'][0]['interaction']['result'] = 'accepted'
        with self.assertRaises(ValueError): oracle.validate_world(invalid)


class PhaseTwoGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = phase_two_worlds(); cls.audit = quality(cls.worlds)

    def test_160_histories_split_counts_and_distinct_seeds(self):
        self.assertEqual(len(self.worlds),160); self.assertEqual(len({w['seed'] for w in self.worlds}),160)
        self.assertEqual(self.audit['split_counts'],{'development':128,'reserved':32})
        self.assertEqual(self.audit['expression_roundtrips'],61440)
        self.assertEqual(self.audit['paired_relations_checked'],800)
        for f in FAMILIES:
            for t in TIERS:
                cell = [w for w in self.worlds if w['family'] == f and w['tier'] == t]
                self.assertEqual(len(cell),10); self.assertEqual(sum(w['split'] == 'reserved' for w in cell),2)
                self.assertTrue(all(len(w['events']) == 128 and len(w['queries']) == 6 for w in cell))
        old = [json.loads(s)['scenario_id'] for s in (ROOT/'experiments/memory_stress/development-v1/worlds.evaluator.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertFalse(set(old) & {w['scenario_id'] for w in self.worlds})

    def test_actual_required_evidence_loads_and_fixed_update_registry(self):
        expected = {'multihop':[1,2,4,6],'updates':[5,5,5,5],'collections':[3,5,7,9],'feedback':[1,2,4,6]}
        for world in self.worlds:
            q = next(q for q in world['queries'] if q['role'] == 'primary')
            proof = self.audit['proofs'][world['scenario_id']][q['id']]
            self.assertEqual(proof['required_group_count'],expected[world['family']][TIERS.index(world['tier'])])
            for group in proof['required_groups']:
                self.assertNotEqual(oracle.resolve(world,q,[r for r in world['events'] if r['id'] not in group])['value'],proof['answer'])
        self.assertEqual({w['loads']['registry_keys'] for w in self.worlds if w['family'] == 'updates'},{15})
        for w in self.worlds:
            if w['family'] != 'collections': continue
            values = oracle.answers(w)
            a = next(q for q in w['queries'] if q['role'] == 'current')
            b = next(q for q in w['queries'] if q['role'] == 'other_scope')
            self.assertNotEqual(values[a['id']], values[b['id']])

    def test_candidate_order_and_size_do_not_reveal_the_winner(self):
        for family,count in (('collections',256),('feedback',64)):
            positions = set()
            for w in self.worlds:
                if w['family'] != family: continue
                q = next(q for q in w['queries'] if q['role'] == 'primary')
                value = oracle.resolve(w,q)['value']; positions.add(next(i for i,o in enumerate(q['options']) if o['id'] == value))
                self.assertEqual(len(q['options']),count)
                self.assertEqual(len({len(o['values']) for o in q['options']}),1)
                if family == 'collections': self.assertTrue(all(len(set(o['values'].values())) == 8 for o in q['options']))
                for key,choices in q['choices'].items():
                    self.assertEqual({sum(o['values'][key] == value for o in q['options']) for value in choices},{count//2})
                # Every option has the same number of one-field neighbours: no special centre.
                selected = q['options'][0]
                neighbours = sum(sum(o['values'][k] != selected['values'][k] for k in q['choices']) == 1 for o in q['options'])
                self.assertEqual(neighbours,len(q['choices']))
            self.assertGreater(len(positions),15)

    def test_all_expression_readback_and_public_queries_match(self):
        for w in self.worlds:
            for e in EXPRESSIONS:
                records = []
                for r in w['events']:
                    text = render_event(r,e); self.assertEqual(parse_event(text,e),r); records.extend(parse_records(text))
                    if e != 'structured': self.assertNotIn('EVENT=',text)
                for q in w['queries']:
                    payload = parse_question(render_query(q,e))
                    self.assertNotIn('path',payload); self.assertNotIn('role',payload)
                    self.assertEqual(short_answer(records,payload),oracle.resolve(w,q)['value'])

    def test_pairs_keep_related_versions_in_one_split_and_change_one_fact(self):
        for w in self.worlds[::10]:
            base = oracle.answers(w); primary = next(q for q in w['queries'] if q['role'] == 'primary')
            for variant in VARIANTS[1:]:
                edited = transform(w,variant); self.assertEqual((edited['split'],edited['split_group']),(w['split'],w['split_group']))
                changes = [(a,b) for a,b in zip(w['events'],edited['events']) if a != b]
                if variant == 'fact_edit':
                    self.assertEqual(len(changes),1); self.assertEqual([k for k in changes[0][0] if changes[0][0][k] != changes[0][1][k]],['fields'])
                if variant == 'approval_swap': self.assertEqual(len(changes),2)
                actual = oracle.answers(edited)
                if variant in ('fact_edit','approval_swap'): self.assertNotEqual(actual[primary['id']],base[primary['id']])
                else: self.assertEqual(actual,base)

    def test_all_no_history_conditions_preserve_128_sessions_and_return_null(self):
        for w in self.worlds:
            masked = oracle.without_query_history(w)
            self.assertEqual(len(masked),128); self.assertEqual(set(oracle.answers(w,masked).values()),{None})


class PhaseTwoGradingTests(unittest.TestCase):
    def test_competing_answers_are_unknown_without_selecting_the_correct_candidate(self):
        right = chr(96)*3+'json\n{"answer":"RIGHT"}\n'+chr(96)*3
        cases = ('{"answer":"WRONG"}\n'+right,right+'\n{"answer":"WRONG"}',
                 right+'\n最终修正：{"answer":"WRO',right+'\n{"answer"',
                 right+'\n{"\\u0061nswer":"WRONG"}',right+'\n{"answer":"RIGHT"}')
        for text in cases:
            with self.subTest(text=text):
                result = grade('RIGHT',text,output_type='string')
                self.assertEqual(result['status'],'unknown')
                self.assertEqual(result['parse_error_code'],'ambiguous_answer')
                self.assertFalse(result['content_task_success']); self.assertFalse(result['strict_task_success'])

    def test_unique_answer_with_ordinary_prose_still_has_observable_content(self):
        answer = chr(96)*3+'json\n{"answer":"RIGHT"}\n'+chr(96)*3
        for text in ('说明：这是登记中的目录。\n'+answer,answer+'\n以上是查询结果。'):
            result = grade('RIGHT',text,output_type='string')
            self.assertTrue(result['content_task_success']); self.assertEqual(result['format_status'],'fail')
        self.assertTrue(grade('RIGHT','{"answer":"RIGHT"}',output_type='string')['strict_task_success'])

    def test_ambiguous_answer_keeps_the_scheduled_denominator(self):
        world = revised_phase_one_worlds()[0]; q = next(q for q in world['queries'] if q['role'] == 'primary')
        case,meta = suite.build_case(world,q['id'])
        text = chr(96)*3+'json\n'+json.dumps({'answer':meta['expected']})+'\n'+chr(96)*3+'\n{"answer":"another"}'
        events = [{'agent_id':'a','trial':0,'case_id':case['id'],'step_id':s['id'],
                   'response':{'text':text,'actions':[]}} for s in case['steps']]
        rows = suite.collect_slots({'agents':[{'id':'a'}],'repeats':1},[case],events,{case['id']:meta})
        summary = grouped_summary(rows)[0]
        self.assertEqual(summary['scheduled_final_slots'],1); self.assertEqual(summary['status_counts'],{'unknown':1})
        self.assertEqual(summary['content_success_history_macro'],0)

    def test_nullable_format_schema_is_independent_of_gold(self):
        for output_type,known,output in (('string','exports/a','exports/b'),('integer',11,17),('string_set',['a'],['b'])):
            for expected in (known,None):
                abstain = grade(expected,'{"answer":null}',output_type=output_type)
                answer = grade(expected,json.dumps({'answer':output}),output_type=output_type)
                self.assertEqual(abstain['format_status'],'pass')
                self.assertEqual(answer['format_status'],'pass')
                self.assertEqual(abstain['status'],'pass' if expected is None else 'fail')
                self.assertEqual(answer['status'],'fail')
        result = grade(11,'{"answer":"11"}',output_type='integer')
        self.assertTrue(result['content_task_success']); self.assertEqual(result['format_status'],'fail')
        self.assertEqual(grade(None,'{"answer":true}',output_type='integer')['status'],'unknown')
        self.assertEqual(grade('dir','{"answer":11}',output_type='string')['format_status'],'fail')

    def test_unavailable_action_traces_are_unknown_and_empty_traces_are_zero(self):
        visible = suite.action_visibility([{'response':{'actions':[]}}])
        self.assertEqual(visible['total_action_count'],0); self.assertEqual(visible['action_trace_visibility_rate'],1)
        for response in ({'actions':None},{},None):
            result = suite.action_visibility([{'response':response}])
            self.assertIsNone(result['total_action_count']); self.assertEqual(result['action_trace_unknown_steps'],1)
        result = suite.action_visibility([{'response':{'actions':[{},{}]}},{'response':{'actions':[]}},None,{'response':{}}])
        self.assertEqual(result['action_count_visible'],2); self.assertEqual(result['action_trace_visibility_rate'],.5)
        self.assertIsNone(result['total_action_count'])

    def test_collect_slots_handles_protocol_null_and_missing_traces(self):
        w = revised_phase_one_worlds()[0]; q = next(q for q in w['queries'] if q['role'] == 'primary')
        case,meta = suite.build_case(w,q['id']); manifest = {'agents':[{'id':'a'}],'repeats':1}
        for response,observed in (({'actions':None},0),({},0),({'actions':[]},65)):
            events = [{'agent_id':'a','trial':0,'case_id':case['id'],'step_id':s['id'],
                       'response':dict(response,text=json.dumps({'answer':meta['expected']}))} for s in case['steps']]
            row = suite.collect_slots(manifest,[case],events,{case['id']:meta})[0]
            self.assertTrue(row['grade']['strict_task_success'])
            self.assertEqual(row['action_trace_observed_steps'],observed)
            self.assertEqual(row['total_action_count'],0 if observed else None)
            self.assertEqual(grouped_summary([row])[0]['action_trace_visibility_rate'],observed/65)

    def test_sets_precision_recall_and_forbidden_items(self):
        result = grade(['a','c'],'{"answer":["a","b"]}',forbidden=['b'])
        self.assertEqual(result['status'],'fail'); self.assertEqual(result['set_precision'],.5); self.assertEqual(result['set_recall'],.5)
        self.assertEqual(result['forbidden_items'],['b'])
        self.assertEqual(grade(['a','c'],'{"answer":[]}')['set_recall'],0)

    def test_list_order_and_duplicates_are_format_separate(self):
        for text in ('{"answer":["c","a"]}','{"answer":["a","c","c"]}'):
            result = grade(['a','c'],text)
            self.assertTrue(result['content_task_success']); self.assertEqual(result['format_status'],'fail'); self.assertFalse(result['strict_task_success'])
        self.assertEqual(grade(['a'],'{"answer":[1]}')['status'],'unknown')
        self.assertEqual(grade(['a'],None,error='timeout')['status'],'error')

    def test_real_file_missing_malformed_extra_keys_lf_and_types(self):
        query = {'project':'new'}; values = {k:'delivery/d' if k == 'directory' else k+'-code' for k in environment.COMPONENTS}
        spec = environment.artifact_spec(query,{'values':values})
        self.assertFalse(environment.grade_delivery({'exists':False},spec)['content_observed'])
        self.assertFalse(environment.grade_delivery({'exists':True,'text':'not json'},spec)['file_success'])
        result = environment.grade_delivery({'exists':True,'text':canonical(dict(spec['content'],extra=1))+'\n'},spec)
        self.assertTrue(result['content_correct']); self.assertFalse(result['format_correct'])
        self.assertFalse(environment.grade_delivery({'exists':True,'text':canonical(spec['content'])},spec)['file_success'])
        self.assertFalse(environment.grade_delivery({'exists':True,'text':spec['text']+'\n'},spec)['file_success'])
        self.assertTrue(environment.grade_delivery({'exists':True,'text':json.dumps(spec['content'],indent=2)+'\n'},spec)['file_success'])
        with tempfile.TemporaryDirectory() as tmp:
            environment.write_delivery(tmp,spec); observed = environment.inspect_delivery(tmp,spec)
            self.assertTrue(environment.grade_delivery(observed,spec)['file_success'])
            with self.assertRaises(BenchError): environment.artifact_spec(query,{'values':dict(values,directory='../escape')})

    def test_correct_memory_answer_with_missing_file_is_action_failure(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        q = next(q for q in w['queries'] if q['role'] == 'primary'); _,meta = suite.build_case(w,q['id'])
        assessment = grade(meta['expected'],json.dumps({'answer':meta['expected']}))
        action = action_grade(meta,{'response':{'text':'irrelevant'},'artifacts':{meta['delivery_spec']['path']:{'exists':False}}},assessment)
        self.assertTrue(assessment['content_task_success']); self.assertFalse(action['whole_task_success']); self.assertFalse(action['content_observed'])

    def test_unseen_tool_trace_does_not_imply_no_write(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        q = next(q for q in w['queries'] if q['role'] == 'primary'); _,meta = suite.build_case(w,q['id'])
        spec = meta['delivery_spec']; assessment = grade(meta['expected'],json.dumps({'answer':meta['expected']}))
        final = {'response':{'text':'x'},'artifacts':{spec['path']:{'exists':True,'text':spec['text']}}}
        action = action_grade(meta,final,assessment)
        self.assertEqual(action['tool_trace'],'unknown'); self.assertIsNone(action['write_action']); self.assertTrue(action['whole_task_success'])

    def test_missing_slots_and_splits_are_not_dropped_or_pooled(self):
        worlds = phase_two_worlds()[7:10]; datasets,catalog = suite.build(worlds); cases = datasets['memory']
        rows = suite.collect_slots({'agents':[{'id':'a'}],'repeats':2},cases,[],catalog)
        self.assertEqual(len(rows),6); self.assertTrue(all(r['grade']['status'] == 'unknown' for r in rows))
        summaries = grouped_summary(rows)
        self.assertEqual({s['split'] for s in summaries},{'development','reserved'})
        self.assertEqual(sum(s['scheduled_final_slots'] for s in summaries),6)


class PhaseTwoPipelineTests(unittest.TestCase):
    def test_revised_phase_one_preserves_gold_and_controls_update_recency(self):
        from experiments.memory_stress.world_generator import development_worlds
        originals = development_worlds(); revised = revised_phase_one_worlds()
        for old,new in zip(originals,revised):
            self.assertEqual((old['scenario_id'],old['split_group']),(new['scenario_id'],new['split_group']))
            self.assertEqual(oracle.answers(old),oracle.answers(new))
            self.assertEqual(len(new['events']),64)
            if new['family'] == 'updates':
                self.assertEqual(next(i for i,r in enumerate(new['events'],1) if r['id'] == new['edit_plan']['effective_id']),50)
                self.assertEqual(new['loads']['inputs_after_effective_update'],14)
                for position in (36,37,52,54,56,60): self.assertEqual(old['events'][position],new['events'][position])
            else: self.assertEqual(old['events'],new['events'])
        for world in phase_two_worlds():
            if world['family'] == 'updates':
                self.assertEqual(next(i for i,r in enumerate(world['events'],1) if r['id'] == world['edit_plan']['effective_id']),94)
                self.assertEqual(world['loads']['inputs_after_effective_update'],34)

    def test_revised_pilot_selection_and_reader_inputs_are_frozen_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'prepared'; protocol = suite.prepare(path,cohort='revision-v1')
            self.assertEqual((protocol['contract'],protocol['histories'],protocol['history_sessions']),('memory-stress-0.1.1',30,64))
            self.assertEqual(protocol['native_case_counts'],{'memory':30})
            self.assertEqual(suite.verify_prepared(path/'pilot')['planned_agent_turns'],1560)
            pilot = read_json(path/'pilot/protocol.json')
            self.assertEqual((len(pilot['selected_histories']),pilot['native_cases'],pilot['planned_final_slots']),(6,12,24))
            self.assertEqual(pilot['paid_calls'],0); self.assertIsNone(pilot['agent_configs'])
            learners = [json.loads(s) for s in (path/'pilot/reader-only.learner.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(learners),6)
            gold = read_json(path/'pilot/reader-only.gold.evaluator.json')
            for row in learners:
                self.assertEqual(set(row),{'id','messages','output_tokens'}); self.assertEqual(len(row['messages']),1)
                self.assertEqual(short_answer(parse_records(row['messages'][0]['content']),parse_question(row['messages'][0]['content'])),gold[row['id']]['expected'])
                self.assertNotIn('required_groups',row['messages'][0]['content'])
            suite.verify_prepared(path)

    def test_runner_controls_files_and_no_gold_in_requests(self):
        worlds = [next(w for w in phase_two_worlds() if w['family'] == f and w['tier'] == 'extreme') for f in ('collections','feedback')]
        datasets,catalog = suite.build(worlds,conditions=suite.CONDITIONS); cases = [c for rows in datasets.values() for c in rows]
        seen = []
        class Replay:
            def turn(self,request): seen.append(copy.deepcopy(request)); return turn(request)
        config = {'schema_version':'1.0','agents':[{'id':'fake','kind':'command','command':['unused']}]}
        with tempfile.TemporaryDirectory() as tmp,patch('kylin_memory_bench.runner.create_adapter',side_effect=lambda *_:Replay()):
            execute(cases,config,Path(tmp)/'run'); manifest,data,events,_ = read_run(Path(tmp)/'run')
            rows = suite.collect_slots(manifest,data,events,catalog)
        self.assertEqual(len(seen),1290)
        self.assertTrue(all(set(r) == {'protocol_version','session_id','day','prompt','workspace','output_tokens'} for r in seen))
        self.assertTrue(all('gold' not in r['prompt'] and 'required_groups' not in r['prompt'] for r in seen))
        self.assertTrue(all(r['action']['whole_task_success'] == (r['condition'] != 'stateless') for r in rows))
        self.assertTrue(all(r['retrieved_evidence']['status'] == 'unknown' for r in rows))

    def test_case_query_workspaces_are_independent_and_ids_opaque(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        data,catalog = suite.build([w],queries='all',variants=('base','fact_edit'))
        self.assertEqual(len(data['memory']),12); self.assertEqual(len(catalog),12)
        self.assertEqual(len({c['id'] for c in data['memory']}),12)
        for c in data['memory']:
            self.assertEqual(len([s for s in c['steps'] if s['id'] == 'final']),1)
            self.assertNotIn('feedback',c['id']); self.assertNotIn('reserved',c['id'])

    def test_phase_one_source_fingerprints_remain_valid(self):
        verify_v1(ROOT/'experiments/memory_stress/development-v1')

    def test_prepare_freezes_every_scene_and_preserves_split_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'prepared'; protocol = suite.prepare(path)
            suite.verify_prepared(path)
            self.assertEqual(len(list((path/'scenes').glob('*.js'))),160)
            self.assertEqual(len((path/'native-memory-development.evaluator.jsonl').read_text(encoding='utf-8').splitlines()),128)
            self.assertEqual(len((path/'native-memory-reserved.evaluator.jsonl').read_text(encoding='utf-8').splitlines()),32)
            first = json.loads((path/'learner-memory-development.jsonl').read_text(encoding='utf-8').splitlines()[0])
            self.assertEqual(set(first),{'id','state_policy','sessions'})
            with self.assertRaises(BenchError): suite.prepare(path)
            scene = next((path/'scenes').glob('*.js')); scene.write_text('tampered',encoding='utf-8')
            with self.assertRaisesRegex(BenchError,'fingerprint'): suite.verify_prepared(path)


class PhaseTwoChainTests(unittest.TestCase):
    def test_actual_file_failure_reaches_the_next_request_and_enables_repair(self):
        world = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        primary = next(q for q in world['queries'] if q['role'] == 'primary')
        answer = oracle.resolve(world,primary)['value']
        for fault,reason in (('missing','missing_file'),('invalid_json','invalid_json_file'),
                             ('no_lf','format_mismatch'),('wrong_content','content_mismatch')):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)/'chain'; receipts = []
                class Repair:
                    def turn(self,request):
                        if not receipts:
                            query = parse_question(request['prompt'])
                            spec = environment.artifact_spec(query,next(o for o in query['options'] if o['id'] == answer))
                            if fault != 'missing':
                                path = Path(request['workspace'])/spec['path']; path.parent.mkdir(parents=True,exist_ok=True)
                                text = ('{invalid}\n' if fault == 'invalid_json' else spec['text'].rstrip('\n') if fault == 'no_lf'
                                        else canonical(dict(spec['content'],profile='WRONG-PROFILE'))+'\n')
                                path.write_bytes(text.encode('utf-8'))
                            receipts.append(request)
                            return {'text':json.dumps({'answer':answer}),'actions':[]}
                        if len(receipts) == 1:
                            saved = [json.loads(line) for line in (out/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
                            self_test.assertEqual(len(saved),1)
                            self_test.assertFalse(read_json(out/'results.json')['chain_success'])
                            raw = next(line.split('=',1)[1] for line in request['prompt'].splitlines() if line.startswith('DELIVERY_FEEDBACK='))
                            receipt = json.loads(raw)
                            self_test.assertEqual(receipt['delivery_verdict']['result'],'rejected')
                            self_test.assertEqual(receipt['delivery_verdict']['reason'],reason)
                            self_test.assertTrue(all(r['interaction']['result'] == 'accepted' for r in parse_records(request['prompt'])))
                            self_test.assertEqual(receipt['submitted_artifact']['exists'],fault != 'missing')
                        receipts.append(request)
                        return turn(request)
                self_test = self
                result = chain.run_chain(world,out,adapter=Repair())
                self.assertTrue(result['chain_success'])
                self.assertEqual([r['status'] for r in result['stages'][0]['attempts']],['fail','pass'])
                self.assertEqual(chain.verify_chain(out)['status'],'completed')

    def test_interrupt_preserves_completed_event_inflight_request_and_unknown_stages(self):
        world = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        for interruption in (KeyboardInterrupt,SystemExit):
            with self.subTest(interruption=interruption.__name__), tempfile.TemporaryDirectory() as tmp:
                class Interrupted:
                    def __init__(self): self.calls = 0
                    def turn(self,request):
                        self.calls += 1
                        if self.calls == 2: raise interruption()
                        return {'text':'{"answer":null}','actions':[]}
                adapter = Interrupted(); out = Path(tmp)/'chain'
                with self.assertRaises(interruption): chain.run_chain(world,out,adapter=adapter)
                result = read_json(out/'results.json')
                self.assertEqual((result['status'],result['event_count']),('interrupted',1))
                self.assertEqual(result['in_flight']['attempt'],1)
                self.assertEqual(result['in_flight']['request']['day'],2)
                self.assertFalse(result['chain_success']); self.assertEqual(result['planned_stages'],3)
                self.assertEqual(result['stages'][1]['attempts'][0]['status'],'unknown')
                check = chain.verify_chain(out)
                self.assertTrue(check['valid']); self.assertFalse(check['complete']); self.assertEqual(adapter.calls,2)

    def test_interrupted_feedback_ack_does_not_complete_the_stage(self):
        world = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        primary = next(q for q in world['queries'] if q['role'] == 'primary'); answer = oracle.resolve(world,primary)['value']
        class InterruptedAck:
            def __init__(self): self.calls = 0
            def turn(self,request):
                self.calls += 1
                if self.calls == 2: raise KeyboardInterrupt()
                query = parse_question(request['prompt'])
                spec = environment.artifact_spec(query,next(o for o in query['options'] if o['id'] == answer))
                return {'text':json.dumps({'answer':answer}),'actions':[environment.write_delivery(request['workspace'],spec)]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'
            with self.assertRaises(KeyboardInterrupt): chain.run_chain(world,out,adapter=InterruptedAck())
            result = read_json(out/'results.json')
            self.assertEqual(result['in_flight']['kind'],'feedback_delivery')
            self.assertTrue(result['stages'][0]['first_attempt_success']); self.assertFalse(result['stages'][0]['stage_success'])
            self.assertFalse(chain.verify_chain(out)['complete'])

    def test_force_exit_keeps_fsynced_events_without_relying_on_finally(self):
        code = (
            "import os,sys\n"
            "from experiments.memory_stress.v2.chain import run_chain\n"
            "from experiments.memory_stress.v2.world_generator import phase_two_worlds\n"
            "class Killed:\n"
            " def __init__(self): self.calls=0\n"
            " def turn(self,request):\n"
            "  self.calls+=1\n"
            "  if self.calls==2: os._exit(73)\n"
            "  return {'text':'{\"answer\":null}','actions':[]}\n"
            "world=next(w for w in phase_two_worlds() if w['family']=='feedback')\n"
            "run_chain(world,sys.argv[1],adapter=Killed())\n")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'
            done = subprocess.run([sys.executable,'-X','utf8','-c',code,str(out)],cwd=ROOT,capture_output=True,timeout=30)
            self.assertEqual(done.returncode,73)
            result = read_json(out/'results.json')
            self.assertEqual((result['status'],result['event_count']),('running',1)); self.assertFalse(result['chain_success'])
            self.assertEqual(result['in_flight']['attempt'],1)
            check = chain.verify_chain(out); self.assertEqual(check['events'],1); self.assertFalse(check['complete'])

    def test_progress_checkpoint_and_partial_tail_remain_incomplete(self):
        world = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        class Replay:
            def turn(self,request): return turn(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'; chain.run_chain(world,out,adapter=Replay())
            result = read_json(out/'results.json')
            rows = [json.loads(line) for line in (out/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
            result.update(status='running',event_count=1,evidence_head=rows[0]['hash'],chain_success=False,
                          stages=chain.stage_summaries(rows[:1],incomplete=True),transfer_first_attempt_success=False)
            from kylin_memory_bench.common import write_json
            write_json(out/'results.json',result)
            check = chain.verify_chain(out)
            self.assertEqual(check['uncheckpointed_events'],len(rows)-1); self.assertFalse(check['complete'])
            with (out/'evidence.jsonl').open('a',encoding='utf-8') as stream: stream.write('{"unfinished":')
            before = (out/'evidence.jsonl').read_bytes()
            self.assertTrue(chain.verify_chain(out)['truncated_tail'])
            self.assertEqual((out/'evidence.jsonl').read_bytes(),before)
            result['status'] = 'completed'; write_json(out/'results.json',result)
            with self.assertRaises(BenchError): chain.verify_chain(out)

    def test_rehashed_wrong_forwarded_diagnosis_is_rejected(self):
        from kylin_memory_bench.common import digest,write_json,write_text
        world = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        class Replay:
            def turn(self,request): return turn(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'; chain.run_chain(world,out,adapter=Replay())
            rows = [json.loads(line) for line in (out/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
            receipt = chain.forwarded_delivery(rows[1]['request']['prompt'])
            original = canonical(receipt); receipt['delivery_verdict']['reason'] = 'invented_diagnosis'
            rows[1]['request']['prompt'] = rows[1]['request']['prompt'].replace(original,canonical(receipt))
            previous = None
            for row in rows:
                row['previous_hash'] = previous; row['hash'] = digest({k:v for k,v in row.items() if k != 'hash'}); previous = row['hash']
            write_text(out/'evidence.jsonl',''.join(canonical(row)+'\n' for row in rows))
            result = read_json(out/'results.json'); result['evidence_head'] = previous; write_json(out/'results.json',result)
            with self.assertRaisesRegex(BenchError,'forwarded feedback'): chain.verify_chain(out)

    def test_actual_feedback_correction_and_transfer_are_separate_from_controlled_suite(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback' and w['tier'] == 'extreme')
        class Replay:
            def turn(self,request): return turn(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'; result = chain.run_chain(w,out,adapter=Replay())
            self.assertTrue(result['chain_success']); self.assertTrue(result['transfer_first_attempt_success'])
            self.assertEqual([r['status'] for r in result['stages'][0]['attempts']],['fail','pass'])
            self.assertEqual(result['stages'][0]['attempt_limit'],2); self.assertEqual(result['stages'][-1]['attempt_limit'],1)
            chain.verify_chain(out)
            raw = [json.loads(s) for s in (out/'evidence.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(raw[0]['tool_feedback']['result'],'rejected'); self.assertEqual(raw[1]['tool_feedback']['result'],'accepted')
            for e in raw: self.assertNotIn('expected',e['request'])
            saved = read_json(out/'results.json'); saved['chain_success'] = False
            (out/'results.json').write_text(json.dumps(saved),encoding='utf-8')
            with self.assertRaisesRegex(BenchError,'summary'): chain.verify_chain(out)

    def test_stateless_chain_keeps_learning_correction_but_fails_transfer(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback' and w['tier'] == 'extreme')
        class Replay:
            def turn(self,request): return turn(request)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'; result = chain.run_chain(w,out,'fresh_each_session',Replay())
            self.assertTrue(result['stages'][0]['stage_success']); self.assertFalse(result['transfer_first_attempt_success']); self.assertFalse(result['chain_success'])
            chain.verify_chain(out)

    def test_chain_error_keeps_all_three_planned_stages_and_no_retry(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        class Broken:
            def turn(self,request): raise BenchError('fixture error')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'chain'; result = chain.run_chain(w,out,adapter=Broken())
            self.assertEqual(len(result['stages']),3); self.assertFalse(result['chain_success']); self.assertEqual(result['event_count'],1)
            self.assertEqual(result['stages'][1]['attempts'][0]['status'],'unknown')
            chain.verify_chain(out)

    def test_reference_real_subprocess_writes_a_real_file(self):
        w = next(w for w in phase_two_worlds() if w['family'] == 'feedback')
        q = next(q for q in w['queries'] if q['role'] == 'primary')
        records = oracle.oracle_records(w,q)
        prompt = render_query(q)+'\n'+'\n'.join(render_event(r) for r in records)
        with tempfile.TemporaryDirectory() as tmp:
            request = {'workspace':tmp,'prompt':prompt,'session_id':'fake'}
            done = subprocess.run([sys.executable,'-X','utf8',str(ROOT/'experiments/memory_stress/v2/reference_adapter.py')],cwd=tmp,
                                  input=json.dumps(request),capture_output=True,encoding='utf-8',check=True)
            response = json.loads(done.stdout); spec = oracle.delivery_spec(w,q)
            self.assertEqual(json.loads(response['text'])['answer'],oracle.resolve(w,q)['value'])
            self.assertTrue(environment.grade_delivery(environment.inspect_delivery(tmp,spec),spec)['file_success'])
            self.assertEqual(response['actions'][0]['arguments']['path'],spec['path'])


if __name__ == '__main__': unittest.main()
