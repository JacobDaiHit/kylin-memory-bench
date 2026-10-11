import json
import tempfile
import unittest
from pathlib import Path
from kylin_memory_bench.challenges import generate_challenges
from kylin_memory_bench.dataset import describe,load_dataset,validate_case
from kylin_memory_bench.generate import save_dataset
from kylin_memory_bench.common import BenchError,digest
from kylin_memory_bench.scoring import evaluate
from kylin_memory_bench.evidence_view import render_evidence

class SubmissionTests(unittest.TestCase):
    def test_explicit_project_aliases_reject_wrong_and_malformed_answers(self):
        case=generate_challenges()[0]
        rule=case['steps'][-1]['checks'][0]
        for answer in ('松柏','松柏项目'):
            event={'event_id':'1','response':{'text':json.dumps({'answer':answer})}}
            self.assertEqual(evaluate(rule,event)['status'],'pass')
        for text in ('{"answer":"纸鸢项目"}','{"answer":"松柏项目可能是纸鸢"}',
                     '{"answer":null}','{"answer":["松柏"]}','先解释一下：{"answer":"松柏"}'):
            self.assertEqual(evaluate(rule,{'event_id':'1','response':{'text':text}})['status'],'fail')
        rule={**rule,'value':[1]}
        self.assertEqual(evaluate(rule,{'event_id':'1','response':{'text':'{"answer":true}'}})['status'],'fail')

    def test_alias_contract_rejects_unbounded_and_non_scalar_sets(self):
        for value in ([],list(range(33)),{},'松柏',[{'name':'松柏'}],[['松柏']]):
            case=generate_challenges()[0]
            case['steps'][-1]['checks'][0]['value']=value
            with self.assertRaises(BenchError):validate_case(case)

    def test_challenge_generation_is_reproducible_and_seed_changes_facts(self):
        cases=generate_challenges(7331)
        self.assertEqual(cases,generate_challenges(7331))
        self.assertNotEqual(digest(cases),digest(generate_challenges(7332)))
        self.assertEqual(set(describe(cases)['dimensions'].values()),{2})
        self.assertTrue(all(len({s['session'] for s in c['steps']})>=2 for c in cases))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'challenge.jsonl';save_dataset(path,cases)
            self.assertEqual(load_dataset(path),cases)

    def test_evidence_inspector_cannot_break_out_of_embedded_json(self):
        attack='</script><script>alert("attack")</script>'
        cases=generate_challenges()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);save_dataset(root/'dataset.jsonl',cases)
            event={'event_id':'1','case_id':cases[0]['id'],'step_id':'intro','prompt':attack,'response':{'text':attack}}
            (root/'evidence.jsonl').write_text(json.dumps(event),encoding='utf-8')
            render_evidence(root)
            html=(root/'evidence.html').read_text(encoding='utf-8')
            self.assertNotIn(attack,html)
            self.assertIn('\\u003c/script\\u003e',html)
            self.assertNotIn('.innerHTML',html)
            embedded=html.split('<script id="data" type="application/json">')[1].split('</script>')[0]
            self.assertEqual(json.loads(embedded)[0]['prompt'],attack)

if __name__=='__main__':unittest.main()
