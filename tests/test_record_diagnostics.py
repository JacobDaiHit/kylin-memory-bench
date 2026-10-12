import json
import tempfile
import unittest
from pathlib import Path

from experiments.math_memory.memory_only import build,grade
from scripts.report_record_pilot import content_diagnostic,retrieval_diagnostic


class RecordEnvelopeTests(unittest.TestCase):
    def setUp(self):
        cases,gold=build()
        self.case=next(c for c in cases if c['id']=='research-v3-combined-high-memory')
        self.gold=gold[self.case['id']]

    def row(self,text,error=None):
        result=grade(self.case,self.gold,text,error)
        result.update(agent='fixture',event_id='1',response_text=text)
        return result

    def test_single_explicit_block_is_diagnostic_without_changing_primary(self):
        text='Explanation\n```json\n'+json.dumps(self.gold)+'\n```\nNote'
        original=self.row(text)
        self.assertEqual(original['observed_count'],0)
        diagnostic=content_diagnostic(self.case,self.gold,original)
        self.assertEqual(diagnostic['grade']['correct_count'],18)
        self.assertEqual(original['observed_count'],0)
        self.assertFalse(diagnostic['eligible_for_predeclared_gate'])
        self.assertTrue(diagnostic['primary_unchanged'])

    def test_multiple_candidates_or_execution_error_remain_unobserved(self):
        block='```json\n'+json.dumps(self.gold)+'\n```'
        self.assertIsNone(content_diagnostic(self.case,self.gold,self.row(block+'\n'+block))['grade'])
        self.assertIsNone(content_diagnostic(self.case,self.gold,self.row(block,error='timeout'))['grade'])

    def test_unread_record_can_still_be_persisted(self):
        records=[{'id':'r0','project':'target','kind':'patch'},
                 {'id':'r1','project':'target','kind':'lemma'}]
        content=json.dumps(records[0])
        case={'id':'fixture','sessions':[{'prompt':'RECORD='+json.dumps(r)} for r in records]+[{'prompt':'query'}]}
        event={'agent_id':'openclaw','case_id':'fixture'}
        events=[dict(event,event_id='1',step_id='note0',response={'actions':[
            {'name':'write_file','arguments':{'path':'early.json','content':content}}]}),
            dict(event,event_id='2',step_id='final',response={'text':'Reply truncated at the model\'s output token limit',
            'actions':[{'name':'read_file','arguments':{'path':'MEMORY.md'},
                        'result':[{'text':'RECORD='+json.dumps(records[1])}]}]})]
        with tempfile.TemporaryDirectory() as directory:
            workspace=Path(directory)
            (workspace/'early.json').write_text(content)
            diagnostic=retrieval_diagnostic(case,events,workspace)
        self.assertEqual(diagnostic['historical_record_count'],2)
        self.assertEqual(diagnostic['explicitly_read_record_count'],1)
        missing=diagnostic['not_in_explicit_final_reads']
        self.assertEqual(missing[0]['record_id'],'r0')
        self.assertTrue(missing[0]['writes'][0]['current_file_matches_write'])
        self.assertTrue(diagnostic['native_output_limit_marker'])
        self.assertFalse(diagnostic['eligible_for_predeclared_gate'])


if __name__=='__main__':unittest.main()
