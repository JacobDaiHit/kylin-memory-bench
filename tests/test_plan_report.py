import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.watch_plan_report import export

class PlanReportTests(unittest.TestCase):
    def test_partial_report_does_not_claim_complete_or_copy_raw_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run';root.mkdir();(root/'shards').mkdir()
            (root/'protocol.json').write_text(json.dumps({'model':'fixture'}))
            (root/'progress.json').write_text(json.dumps({'status':'incomplete'}))
            rows=[]
            for agent in ('openclaw','hermes'):
                for condition in ('memory','reader_only'):
                    rows.append({'task_id':'fixture','scenario_id':'s','agent':agent,'condition':condition,'family':'multihop',
                        'tier':'low','split':'development','phase':'incomplete_evidence','planned_steps':129,'observed_steps':0,
                        'raw_response':'PRIVATE_SENTINEL','grade':{'status':'unknown','observed':False,'content_task_success':False,
                        'strict_task_success':False,'format_status':'unknown'},'action':{'status':'unknown','whole_task_success':False}})
            analysis={'rows':rows,'verification':[]};(root/'analysis.json').write_text(json.dumps(analysis))
            with patch('scripts.watch_plan_report.report',return_value=analysis):
                result=export(root,Path(tmp)/'docs')
            self.assertFalse(result['complete'])
            self.assertNotIn('PRIVATE_SENTINEL',(Path(tmp)/'docs/evidence/luna-full-results.json').read_text())
            self.assertIn('尚不能据此定稿视频',(Path(tmp)/'docs/luna-full-results.md').read_text())
