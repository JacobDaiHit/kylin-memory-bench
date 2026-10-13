import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_luna_submission_pilot as pilot
from experiments.memory_stress.v2.oracle import resolve


class SubmissionPilotTests(unittest.TestCase):
    def test_short_histories_preserve_original_answers_and_planned_denominator(self):
        originals=[json.loads(l) for l in (pilot.ROOT/'experiments/memory_stress/v2/development-v2/worlds.evaluator.jsonl').read_text().splitlines()]
        by_seed={w['seed']:w for w in originals}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run'
            with patch.object(pilot,'RUN',root):
                protocol,cases,catalog=pilot.prepare()
            self.assertEqual(len(protocol['tasks']),32)
            self.assertEqual(sum(len(cases[t['case_id']]['steps']) for t in protocol['tasks']),416)
            worlds=json.loads((root/'worlds.json').read_text())
            self.assertEqual(len(worlds),8)
            for w in worlds:
                q=next(q for q in w['queries'] if q['role']=='primary')
                self.assertEqual(len(w['events']),24)
                self.assertEqual(resolve(w,q)['value'],resolve(by_seed[w['seed']],q)['value'])
                self.assertEqual(w['split'],'development')
                for event in w['events']:
                    if event.get('target_id'):
                        self.assertIn(event['target_id'],[r['id'] for r in w['events']])
            self.assertEqual(len(set(t['id'] for t in protocol['tasks'])),32)
            for t in protocol['tasks']:
                self.assertEqual(len(cases[t['case_id']]['steps']),1 if t['condition']=='reader_only' else 25)

    def test_transport_diagnostic_uses_distinct_histories_and_declared_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pilot,'RUN',Path(tmp)/'first'):a,_,_=pilot.prepare()
            with patch.object(pilot,'RUN',Path(tmp)/'second'):b,_,_=pilot.prepare(seed_offset=1,pooled=True)
            self.assertTrue(set(t['case_id'] for t in a['tasks']).isdisjoint(t['case_id'] for t in b['tasks']))
            self.assertEqual(b['deadline_seconds'],6300)
            self.assertFalse(b['case_retry'])

    def test_compact_options_preserve_every_historical_constraint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'compact'
            with patch.object(pilot,'RUN',root):protocol,_,_=pilot.prepare(seed_offset=2,pooled=True,compact_options=True,jobs=6)
            self.assertEqual(protocol['jobs'],6)
            for w in json.loads((root/'worlds.json').read_text()):
                q=next(q for q in w['queries'] if q['role']=='primary')
                if not q.get('options'):continue
                self.assertEqual(len(q['options']),16)
                right=next(o for o in q['options'] if o['id']==resolve(w,q)['value'])
                for key in q['choices']:
                    self.assertEqual(sum(o['values'][key]==right['values'][key] for o in q['options']),8)
                for key in q['required_fields']:
                    self.assertTrue(any(o['values'][key]!=right['values'][key] and all(o['values'][k]==right['values'][k] for k in q['choices'] if k!=key) for o in q['options']))

if __name__=='__main__':unittest.main()
