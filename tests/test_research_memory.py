import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.math_memory.memory_only import build, grade, reference, recover, answer_trace, QUESTIONS


class ResearchMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases,cls.gold=build()
        cls.by_id={c['id']:c for c in cls.cases}

    def case(self,family='combined',level='high',condition='memory'):
        return self.by_id['research-v3-'+family+'-'+level+'-'+condition]

    def checked(self,case,policy):
        return grade(case,self.gold[case['id']],json.dumps(reference(case,policy)))

    def test_matched_gold_complete_records_and_missing_controls(self):
        self.assertEqual(len(self.cases),36)
        for family in {c['family'] for c in self.cases}:
            expected=self.gold[self.case(family,'low')['id']]
            self.assertEqual(expected,self.gold[self.case(family,'high')['id']])
            for level in ('low','high'):
                memory=self.case(family,level)
                book=self.case(family,level,'open_book')
                self.assertEqual(memory['sessions'][:-1],book['sessions'][:-1])
                self.assertEqual(self.gold[memory['id']],self.gold[book['id']])
                missing=self.case(family,level,'no_history')
                self.assertTrue(all(v is None for v in self.gold[missing['id']].values()))
        for c in self.cases:
            self.assertEqual(self.checked(c,'ledger')['correct_count'],18,c['id'])

    def test_generation_and_scoring_do_not_call_math_solver(self):
        with patch('experiments.math_memory.math_core.solve',side_effect=AssertionError('Math computation forbidden')):
            cases,gold=build(20261015)
            for c in cases:
                self.assertEqual(grade(c,gold[c['id']],json.dumps(reference(c)))['correct_count'],18)

    def test_independent_handwritten_record_replay_and_later_changes(self):
        project='manual'
        def r(id,kind,payload,**extra):
            return dict(id=id,project=project,kind=kind,status='accepted',payload=payload,**extra)
        records=[r('base','patch',{'d1':'7','branch':'old','adoption':{'lemma_id':'L','edition':'e2','regime':'finite'}},checkpoint='C0',revision='v0'),
                 r('first','patch',{'d1':'19','branch':'new'},revision='v8'),
                 r('later','patch',{'d1':'2'},revision='v3'),
                 r('cancel','cancel',{'target_id':'first','fields':['d1']},revision='v6'),
                 r('proper','lemma',{'lemma_id':'L','edition':'e2','regime':'finite','bound':'1/3'}),
                 r('wrong-edition','lemma',{'lemma_id':'L','edition':'e9','regime':'finite','bound':'8'}),
                 r('wrong-scope','lemma',{'lemma_id':'L','edition':'e2','regime':'infinite','bound':'9'})]
        answers=recover(records,project)
        self.assertEqual(answers['q04'],'2')  # cancelling first must not undo a later accepted D1
        self.assertEqual(answers['q07'],'new')
        self.assertEqual(answers['q08'],'v6')
        self.assertEqual(answers['q12'],'1/3')
        self.assertEqual(answers['q15'],'7')
        self.assertEqual(answers['q16'],'old')

    def test_every_nonempty_answer_has_literal_record_support(self):
        for c in self.cases:
            traces=answer_trace(c,self.gold[c['id']])
            for qid,value in self.gold[c['id']].items():
                if value is not None:
                    self.assertTrue(traces[qid]['supporting_literal_records'],(c['id'],qid))

    def test_isolate_field_updates_and_preserve_old_checkpoint(self):
        c=self.case('updates')
        result=self.checked(c,'stale')
        checks={r['qid']:r['status'] for r in result['checks']}
        self.assertEqual(checks['q04'],'fail')
        self.assertEqual(checks['q15'],'pass')
        self.assertEqual(checks['q06'],'pass')
        self.assertEqual(self.checked(c,'accept_draft')['checks'][3]['status'],'fail')

    def test_scoped_lemma_and_project_bindings(self):
        self.assertEqual(self.checked(self.case('scope','low'),'edition_blind')['correct_count'],18)
        high=self.checked(self.case('scope'),'edition_blind')
        self.assertEqual(high['checks'][11]['status'],'fail')
        self.assertEqual(high['checks'][9]['status'],'pass')
        blind=self.checked(self.case('binding'),'project_blind')
        self.assertEqual(blind['checks'][3]['status'],'fail')
        self.assertEqual(blind['checks'][11]['status'],'fail')

    def test_selective_cancel_and_withdrawal_preserve_other_facts(self):
        c=self.case('cancel')
        wrong=self.checked(c,'ignore_cancel')
        self.assertEqual(wrong['checks'][3]['status'],'fail')
        self.assertEqual(wrong['checks'][6]['status'],'pass')
        withdrawn=self.checked(c,'ignore_withdrawal')
        self.assertEqual(withdrawn['checks'][16]['status'],'fail')
        self.assertEqual(withdrawn['checks'][11]['status'],'pass')
        self.assertEqual(self.checked(c,'guess_missing')['checks'][17]['status'],'fail')

    def test_stateless_book_control_is_not_memory_performance(self):
        self.assertLess(self.checked(self.case(),'stateless')['correct_count'],18)
        result=self.checked(self.case(condition='open_book'),'stateless')
        self.assertEqual(result['correct_count'],18)
        self.assertFalse(result['primary_memory_eligible'])
        self.assertEqual(self.checked(self.case(condition='no_history'),'stateless')['correct_count'],18)

    def test_json_and_table_formats_are_semantically_identical(self):
        c=self.case('binding')
        expected=self.gold[c['id']]
        table='\n'.join(k+' = '+('null' if v is None else v) for k,v in expected.items())
        result=grade(c,expected,table)
        self.assertEqual(result['format'],'key_value')
        self.assertEqual(result['correct_count'],18)
        aliases=dict(expected,q13='unit_norm',q14='已批准')
        # Equivalent unreduced fraction is accepted, independent of numeric formatting.
        from fractions import Fraction
        n=Fraction(aliases['q01']);aliases['q01']=str(n.numerator*2)+'/'+str(n.denominator*2)
        self.assertEqual(grade(c,expected,json.dumps(aliases))['correct_count'],18)

    def test_unknowns_do_not_remove_denominator_or_become_capability_errors(self):
        c=self.case();expected=self.gold[c['id']]
        partial=dict(expected);partial.pop('q01')
        result=grade(c,expected,json.dumps(partial))
        self.assertEqual(result['check_count'],18)
        self.assertEqual(result['observed_count'],17)
        self.assertEqual(result['checks'][0]['status'],'unknown')
        partial=dict(expected,q01=True)
        self.assertEqual(grade(c,expected,json.dumps(partial))['checks'][0]['reason'],'invalid_field_type')
        self.assertEqual(grade(c,expected,'q01 = 1\nq01 = 2')['observed_count'],0)
        self.assertEqual(grade(c,expected,'{"q01":"1","q01":"2"}')['observed_count'],0)
        self.assertEqual(grade(c,expected,None,error='timeout')['checks'][0]['status'],'error')
        self.assertEqual(grade(c,expected,None,error='timeout')['observed_count'],0)

    def test_gold_not_in_learner_case_and_missing_case_has_no_target_records(self):
        for c in self.cases:
            self.assertNotIn('answers',c)
            self.assertNotIn('checks',c)
            if c['condition']=='memory':
                final=c['sessions'][-1]['prompt']
                self.assertNotIn('RECORD=',final)
                self.assertNotIn(self.gold[c['id']]['q06'],final)
                self.assertNotIn(self.gold[c['id']]['q12'],final)
            if c['condition']=='no_history':
                for s in c['sessions']:
                    for line in s['prompt'].splitlines():
                        if line.startswith('RECORD='):
                            self.assertNotIn(json.loads(line[7:])['project'],c['target_projects'])

    def test_combined_retrieves_three_projects_without_cross_binding(self):
        c=self.case()
        self.assertEqual(len(c['target_projects']),3)
        self.assertEqual(len(c['sessions'])-1,78)
        expected=self.gold[c['id']]
        self.assertEqual([expected[q] for q in ('q01','q03','q05')],['2','3','4'])
        self.assertEqual([expected[q] for q in ('q07','q08','q09')],['e2','e3','e4'])
        self.assertGreater(len({expected[q] for q in ('q10','q11','q12')}),1)
        self.assertEqual(self.checked(c,'ledger')['correct_count'],18)
        self.assertLess(self.checked(c,'project_blind')['correct_count'],18)

    def test_cli_frozen_data_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'v3'
            # Preserve the historical source while reproducing its UTF-8 environment.
            command=[sys.executable,'-X','utf8','-m','experiments.math_memory.memory_only','--output',str(root)]
            subprocess.run(command,check=True,capture_output=True)
            c=self.case();answer=Path(temp)/'answer.json'
            answer.write_text(json.dumps(self.gold[c['id']]),encoding='utf-8')
            checked=subprocess.run(command+['--grade-case',c['id'],'--answer',str(answer)],check=True,capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(json.loads(checked.stdout)['correct_count'],18)
            with (root/'inputs.jsonl').open('a',encoding='utf-8') as stream:stream.write('\n')
            failed=subprocess.run(command+['--grade-case',c['id'],'--answer',str(answer)],capture_output=True,text=True,encoding='utf-8')
            self.assertNotEqual(failed.returncode,0)
            self.assertIn('Frozen data changed',failed.stderr)

    def test_native_pilot_replay_keeps_controls_and_frozen_selection(self):
        from experiments.math_memory.record_pilot import prepare,analyze,verify_frozen
        from experiments.math_memory.memory_only import planned_answers
        from kylin_memory_bench.runner import execute
        from kylin_memory_bench.dataset import load_dataset
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);frozen=base/'frozen'
            prepare(frozen)
            cases={c['id']:c for c in json.loads((frozen/'learner-cases.json').read_text())}
            class RecordedAdapter:
                def __init__(self,case):self.case=case;self.records={}
                def turn(self,request):
                    for line in request['prompt'].splitlines():
                        if line.startswith('RECORD='):
                            record=json.loads(line[7:]);self.records.setdefault(record['id'],record)
                    answers=planned_answers(list(self.records.values()),self.case['target_projects'],self.case['query_plan'])
                    return {'text':json.dumps(answers),'actions':[]}
            with patch('kylin_memory_bench.runner.create_adapter',side_effect=lambda a,w:RecordedAdapter(cases[w.name])):
                execute(load_dataset(frozen/'dataset.evaluator.jsonl'),
                        json.loads((frozen/'config.template.json').read_text()),base/'run')
            analyze(frozen,base/'run',base/'analysis')
            result=json.loads((base/'analysis'/'results.json').read_text())
            self.assertEqual(len(result['rows']),6)
            self.assertEqual(sum(r['check_count'] for r in result['rows']),108)
            self.assertTrue(all(r['correct_count']==18 for r in result['rows']))
            self.assertEqual(sum(r['primary_memory_eligible'] for r in result['rows']),2)
            self.assertTrue(all(s['open_book_reading_gate_pass'] for s in result['summary'].values()))
            with (frozen/'gold.json').open('a') as stream:stream.write('\n')
            with self.assertRaisesRegex(ValueError,'Frozen pilot material changed'):
                verify_frozen(frozen)


if __name__=='__main__':unittest.main()
