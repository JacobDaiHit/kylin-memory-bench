import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.math_memory import memory_v31 as research
from kylin_memory_bench.adapters import External
from kylin_memory_bench.challenges import generate_challenges,generate_revised_challenges
from kylin_memory_bench.common import BenchError
from kylin_memory_bench.dataset import validate_case,load_dataset
from kylin_memory_bench.runner import execute,read_run,verify_run
from kylin_memory_bench.scoring import evaluate,json_equal
from scripts.calibrate_revision import calculate
from scripts.prepare_memory_validation import prepare,analyze,verify_prepared,config_signature

ROOT=Path(__file__).resolve().parents[1]


class RevisionContractTests(unittest.TestCase):
    def test_original_challenge_generator_and_saved_suite_still_match(self):
        self.assertEqual(generate_challenges(),load_dataset(ROOT/'kylin_memory_bench/data/challenges.jsonl'))

    def test_extra_field_is_rejected_by_new_suite_only(self):
        old=next(c for c in generate_challenges() if c['id']=='challenge-conditional-artifact')
        new=next(c for c in generate_revised_challenges() if c['original_case_id']==old['id'])
        text=json.dumps({'audience':'customer','code':'GREEN-90832','extra':'unwanted'})
        event={'event_id':'fixture','response':{'actions':[{'name':'write_file','arguments':{'path':'deliverables/challenge/audience.json'}}]},
               'artifacts':{'deliverables/challenge/audience.json':{'exists':True,'text':text}}}
        self.assertTrue(all(evaluate(c,event)['status']=='pass' for c in old['steps'][-1]['checks']))
        result=evaluate(new['steps'][-1]['checks'][-1],event)
        self.assertEqual((result['status'],result['category']),('fail','invalid_format'))

    def test_json_exact_keeps_nested_scalar_types_distinct(self):
        self.assertFalse(json_equal({'nested':[1]}, {'nested':[True]}))
        self.assertTrue(json_equal({'a':1,'b':2},{'b':2,'a':1}))

    def test_withdrawal_classifies_values_and_prose_leaks(self):
        case=next(c for c in generate_revised_challenges() if c['original_case_id']=='challenge-selective-delete')
        checks=next(s for s in case['steps'] if s['id']=='forgotten')['checks']
        for value,status,category in [(None,'pass','correct'),('KEEP-86959','fail','confusion'),('FORGET-72523','fail','wrong_reuse')]:
            event={'event_id':'fixture','response':{'text':json.dumps({'answer':value})}}
            r=evaluate(checks[0],event);self.assertEqual((r['status'],r['category']),(status,category))
        event={'event_id':'fixture','response':{'text':'FORGET-72523 was deleted; {"answer":null}'}}
        self.assertEqual(evaluate(checks[1],event)['status'],'fail')

    def test_injection_probes_follow_authorized_fact_without_claiming_absence(self):
        case=next(c for c in generate_revised_challenges() if c['original_case_id']=='challenge-quoted-override')
        probes=[s for s in case['steps'] if s['kind']=='probe']
        self.assertEqual([s['day'] for s in probes],[30,31,32])
        self.assertEqual({s['checks'][0]['value'] for s in probes},{'REAL-33613'})
        self.assertIn('absence is not proof',case['storage_claim_limit'])

    def test_sixteen_frozen_fixtures_have_no_false_passes(self):
        r=calculate();self.assertTrue(r['passed']);self.assertEqual(r['summary']['matched'],16)

    def test_invalid_new_check_and_output_controls_are_rejected(self):
        case=copy.deepcopy(generate_revised_challenges()[0]);case['steps'][0]['output_tokens']=True
        with self.assertRaises(BenchError):validate_case(case)
        case=copy.deepcopy(generate_revised_challenges()[0]);case['state_policy']=[]
        with self.assertRaises(BenchError):validate_case(case)
        case=copy.deepcopy(generate_revised_challenges()[0]);c=case['steps'][-1]['checks'][0]
        c['mismatch_values']=[{'value':[],'category':'confusion'}]
        with self.assertRaises(BenchError):validate_case(case)


class Research31Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.cases,cls.gold=research.build()

    def test_matched_pairs_keep_gold_slots_and_input_bytes(self):
        for family in ('binding','updates','scope'):
            low=next(c for c in self.cases if c['family']==family and c['level']=='low' and c['condition']=='memory')
            high=next(c for c in self.cases if c['family']==family and c['level']=='high' and c['condition']=='memory')
            self.assertEqual(self.gold[low['id']],self.gold[high['id']])
            self.assertEqual(len(low['sessions']),len(high['sessions']))
            self.assertEqual(research.history_bytes(research.records_of(low)),research.history_bytes(research.records_of(high)))
            self.assertEqual(low['sessions'][-1]['prompt'],high['sessions'][-1]['prompt'])

    def test_stateless_has_identical_history_and_gold(self):
        for memory in (c for c in self.cases if c['condition']=='memory'):
            other=next(c for c in self.cases if c['family']==memory['family'] and c['level']==memory['level'] and c['condition']=='stateless')
            self.assertEqual(memory['sessions'],other['sessions'])
            self.assertEqual(self.gold[memory['id']],self.gold[other['id']])
            self.assertEqual(other['state_policy'],'fresh_each_session')

    def test_clarified_revision_preserves_existing_value(self):
        case=next(c for c in self.cases if c['id']=='research-v31-combined-high-memory')
        self.assertIn('未提供revision的补丁保留已有标签',case['sessions'][-1]['prompt'])
        self.assertEqual(self.gold[case['id']]['q16'],'v6')

    def test_ambiguous_or_duplicate_json_is_not_chosen(self):
        case=next(c for c in self.cases if c['condition']=='memory');gold=self.gold[case['id']]
        duplicate='{"q01":"3","q01":"3"}'
        self.assertEqual(research.grade(case,gold,duplicate)['observed_count'],0)
        block='```json\n'+json.dumps(gold)+'\n```'
        result=research.grade(case,gold,'Explanation\n'+block)
        self.assertEqual(result['correct_count'],18);self.assertEqual(result['format_status'],'fail')
        self.assertEqual(research.grade(case,gold,block+'\n'+block)['observed_count'],0)
        self.assertEqual(research.grade(case,gold,block.replace('```json','```JSON'))['format_status'],'pass')

    def test_scope_has_three_independent_literal_bound_queries(self):
        low=next(c for c in self.cases if c['id']=='research-v31-scope-low-memory')
        high=next(c for c in self.cases if c['id']=='research-v31-scope-high-memory')
        self.assertEqual(len(high['target_projects']),3)
        self.assertEqual(sum(q['kind']=='lemma' for q in high['query_plan']),3)
        correct=research.grade(low,self.gold[low['id']],json.dumps(research.reference(low,'edition_blind')))
        wrong=research.grade(high,self.gold[high['id']],json.dumps(research.reference(high,'edition_blind')))
        self.assertEqual((correct['correct_count'],wrong['correct_count']),(18,15))

    def test_native_dataset_has_phase_caps_without_answer_leak(self):
        data=research.native_dataset(self.cases,self.gold)
        for c in data:
            validate_case(c)
            for s in c['steps']:
                self.assertEqual(s['output_tokens'],4096 if s['id']=='final' else 1024)
                self.assertNotIn('gold.json',s['prompt'])

    def test_prepared_materials_reject_tampering_and_count_slots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for stage,slots in [('health',8),('pilot',12),('formal',108)]:
                p=root/stage;r=prepare(p,stage)
                self.assertEqual(r['scheduled_final_slots'],slots);verify_prepared(p)
            (root/'pilot/gold.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'changed'):verify_prepared(root/'pilot')


class StateControlTests(unittest.TestCase):
    def test_fresh_sessions_keep_in_session_state_and_hide_cross_session_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);program=root/'adapter.py'
            program.write_text('import json,sys,os\nfrom pathlib import Path\nr=json.load(sys.stdin);p=Path(r["workspace"])/"state.txt"\nif r["prompt"].startswith("STORE="):p.write_text(r["prompt"][6:])\nvalue=p.read_text() if p.exists() else None\nprint(json.dumps({"text":json.dumps({"answer":value}),"provenance":"fixture-pid="+str(os.getpid())}))\n')
            base={'schema_version':'1.0','id':'persistent','dimension':'retention','title':'fixture','synthetic':True,
                  'steps':[{'id':'learn','kind':'message','session':'same','day':0,'prompt':'STORE=alpha','checks':[]},
                           {'id':'same','kind':'probe','session':'same','day':1,'prompt':'QUERY','checks':[{'id':'same','source':'response','op':'equals','pointer':'/answer','value':'alpha','failure':'omission'}]},
                           {'id':'new','kind':'probe','session':'new','day':2,'prompt':'QUERY','checks':[{'id':'new','source':'response','op':'equals','pointer':'/answer','value':'alpha','failure':'omission'}]}]}
            other=copy.deepcopy(base);other.update(id='fresh',state_policy='fresh_each_session')
            config={'schema_version':'1.0','agents':[{'id':'fixture','kind':'command','command':[sys.executable,str(program)]}]}
            run=root/'run';execute([base,other],config,run)
            _,_,events,_=read_run(run);verify_run(run)
            lookup={(e['case_id'],e['step_id']):json.loads(e['response']['text'])['answer'] for e in events}
            self.assertEqual(lookup['persistent','new'],'alpha')
            self.assertEqual(lookup['fresh','same'],'alpha')
            self.assertIsNone(lookup['fresh','new'])
            self.assertEqual(len({e['response']['provenance'] for e in events}),6)

    def test_unisolated_native_stateless_case_never_calls_adapter(self):
        cases,_=research.build();case=next(c for c in cases if c['condition']=='stateless')
        data=research.native_dataset([case],{case['id']:{q['qid']:None for q in case['query_plan']}})
        with tempfile.TemporaryDirectory() as d,patch('kylin_memory_bench.runner.create_adapter') as create:
            execute(data,{'schema_version':'1.0','agents':[{'id':'openclaw','kind':'openclaw'}]},Path(d)/'run')
            create.assert_not_called()

    def test_per_turn_caps_are_written_without_changing_base_config(self):
        config=json.loads((ROOT/'configs/deepseek-research-v31.example.json').read_text())['agents'][0]
        config['native_config']['models']['providers']['kmb-deepseek']['baseUrl']='http://127.0.0.1:9876/v1'
        original=copy.deepcopy(config)
        with tempfile.TemporaryDirectory() as d,patch('kylin_memory_bench.adapters.process',return_value='{"result":{"final":"{\\"ok\\":true}"}}'):
            adapter=External(config,Path(d))
            initial=json.loads((Path(d)/'.openclaw/openclaw.json').read_text())
            for cap in (1024,4096,1024):
                adapter.turn({'session_id':'fixture','day':0,'prompt':'confirm','output_tokens':cap})
                native=json.loads((Path(d)/'.openclaw/openclaw.json').read_text())
                self.assertEqual(native['models']['providers']['kmb-deepseek']['baseUrl'],f'http://127.0.0.1:9876/v1/cap/{cap}')
                self.assertEqual(native['agents']['defaults']['model'],config['model'])
                self.assertEqual(native['agents']['defaults']['workspace'],str(adapter.workspace))
                self.assertEqual(native['agents'],initial['agents'])
                expected=copy.deepcopy(initial)
                provider=expected['models']['providers']['kmb-deepseek']
                provider['baseUrl']=f'http://127.0.0.1:9876/v1/cap/{cap}'
                for model in provider.get('models',[]):model['maxTokens']=cap
                self.assertEqual(native,expected)
                self.assertEqual(config,original)
            self.assertEqual(config['native_config']['models']['providers']['kmb-deepseek']['baseUrl'],'http://127.0.0.1:9876/v1')

    def test_offline_reference_health_cannot_authorize_native_paid_stage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);prepare(root/'prepared','health')
            config={'schema_version':'1.0','agents':[{'id':name,'kind':'command','command':[sys.executable,'-m','experiments.math_memory.reference_health_adapter']} for name in ('openclaw','hermes')]}
            # Module subprocesses run from their own workspace, so give an absolute script path.
            for a in config['agents']:a['command']=[sys.executable,str(ROOT/'experiments/math_memory/reference_health_adapter.py')]
            execute(load_dataset(root/'prepared/dataset.evaluator.jsonl'),config,root/'run',repeats=2)
            r=analyze(root/'prepared',root/'run',root/'analysis')
            self.assertTrue(r['content_gate_pass'])
            self.assertFalse(r['eligible_for_next_paid_stage'])
            self.assertEqual(r['scheduled_checks'],24)

    def test_config_signature_retains_model_and_tools_but_ignores_loopback_port(self):
        config=json.loads((ROOT/'configs/deepseek-research-v31.example.json').read_text())
        other=copy.deepcopy(config)
        other['agents'][0]['executable']='/new/bin/openclaw-isolated'
        other['agents'][0]['native_config']['models']['providers']['kmb-deepseek']['baseUrl']='http://127.0.0.1:2345/v1'
        self.assertEqual(config_signature(config),config_signature(other))
        other['agents'][0]['model']='another-model'
        self.assertNotEqual(config_signature(config),config_signature(other))
        other=copy.deepcopy(config);other['agents'][0]['native_config']['tools']['allow']=[]
        self.assertNotEqual(config_signature(config),config_signature(other))


class Utf8IOTests(unittest.TestCase):
    def run_cli_without_utf8_defaults(self, command):
        env=dict(os.environ,LC_ALL='C',PYTHONCOERCECLOCALE='0',PYTHONUTF8='0',PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable,'-X','utf8=0',*command],cwd=ROOT,env=env,
                              capture_output=True,encoding='utf-8',check=True)

    def test_revision_calibration_reads_utf8_without_locale_defaults(self):
        result=self.run_cli_without_utf8_defaults(['scripts/calibrate_revision.py','--check',
                                                  '--output','docs/evidence/scoring-revision'])
        self.assertEqual(json.loads(result.stdout),{'count':16,'matched':16,'false_passes':0})

    def test_current_research_generation_and_preparation_without_utf8_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=self.run_cli_without_utf8_defaults(['-m','experiments.math_memory.memory_v31',
                                                       '--output',str(root/'viewer')])
            self.assertEqual(json.loads(result.stdout)['cases'],48)
            self.assertIn('研究档案记忆 V3.1',(root/'viewer/index.html').read_text(encoding='utf-8'))
            result=self.run_cli_without_utf8_defaults(['scripts/prepare_memory_validation.py','prepare',
                                                       '--stage','pilot','--output',str(root/'pilot')])
            self.assertEqual(json.loads(result.stdout)['scheduled_final_slots'],12)
            verify_prepared(root/'pilot')


if __name__=='__main__':unittest.main()
