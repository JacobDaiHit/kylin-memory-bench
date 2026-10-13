"""Offline checks of frozen scheduling and reader separation; no model calls."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import run_plan_full as full
from scripts.plan_native_config import full_configurations

class FullPlanTests(unittest.TestCase):
    def test_full_manifest_and_reader_are_separate_without_changing_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'run'
            with patch.object(full,'verify_prepared'),patch.object(full.shutil,'copytree'):
                full.prepare(root,'http://127.0.0.1:18789/v1',4)
            p=json.loads((root/'protocol.json').read_text());cases=json.loads((root/'frozen/cases.json').read_text())
            self.assertEqual(len(p['tasks']),640);self.assertEqual(p['memory_agent_turns'],41280)
            self.assertEqual(p['reader_agent_turns'],320)
            self.assertEqual(len({t['scenario_id'] for t in p['tasks']}),160)
            self.assertIsNone(p['cumulative_request_cap'])
            frozen=[]
            for file in full.DATA.glob('native-*.jsonl'):frozen.extend(json.loads(line) for line in file.read_text().splitlines())
            for case in frozen:self.assertEqual(cases[case['id']],case)
            for task in p['tasks']:
                if task['condition']=='reader_only':
                    c=cases[task['case_id']];self.assertEqual(len(c['steps']),1)
                    self.assertEqual(c['state_policy'],'fresh_each_session')
            self.assertIn('scripts/isolated_native_plan.sh',p['source_sha256'])
            self.assertIn('configs/deepseek-research-v31.example.json',p['source_sha256'])

    def test_embeddings_explicit_without_silent_fallback_or_native_memory_replacement(self):
        rows=full_configurations('/test/bin','http://127.0.0.1:1/v1','http://127.0.0.1:2/v1')
        search=rows[0]['native_config']['memory']['search']
        self.assertEqual(search['provider'],'openai-compatible')
        self.assertEqual(search['model'],'BAAI/bge-small-zh-v1.5')
        self.assertTrue(rows[1]['native_config']['memory']['memory_enabled'])
        self.assertFalse(rows[0]['per_turn_proxy_limits'])

    def test_windows_paths_are_substituted_after_json_parsing(self):
        from scripts import run_plan_health as health
        from pathlib import PureWindowsPath
        runtime=PureWindowsPath('C:/Users/example/kmb-live')
        bins=r'C:\Users\example\bin'
        with patch.object(health,'RUNTIME',runtime):
            rows=health.configurations(bins,'http://127.0.0.1:1/v1')
        serialized=json.dumps(rows)
        self.assertEqual(json.loads(serialized),rows)
        self.assertEqual(rows[0]['executable'],bins+'/openclaw-isolated')
        self.assertEqual(rows[1]['dependency_home'],str(runtime/'hermes-home'))

    def test_health_gate_requires_both_agents_and_semantic_search(self):
        m={'results':[{}, {'output':json.dumps([{'embeddingProbe':{'ok':True},'status':{'vector':{'semanticAvailable':True},'model':'BAAI/bge-small-zh-v1.5'}}])}, {'output':'{"results":[{"path":"MEMORY.md"}]}'}]}
        h={'results':[{'agent':a,'stage':s,'status':'completed','exact_content_match':True} for a in ('openclaw','hermes') for s in ('learn','recall','isolation')]}
        self.assertTrue(full.validate_preflight(m,h))
        h['results'][-1]['exact_content_match']=False
        with self.assertRaises(ValueError):full.validate_preflight(m,h)

    def test_single_turn_reader_replay_and_tamper_rejection(self):
        from kylin_memory_bench.runner import execute,verify_run
        from scripts.plan_reader_replay import verify_reader
        class Fake:
            def turn(self,request):
                return {'text':'{"answer":"x"}','actions':[],'memory':{'text':'','complete':True}}
        case={'schema_version':'1.0','id':'reader-fixture','title':'reader fixture','dimension':'retrieval','synthetic':True,
              'state_policy':'fresh_each_session','steps':[{'id':'final','session':'final','day':1,'kind':'probe','prompt':'Return x',
              'checks':[{'id':'a','source':'response','op':'json_exact','value':{'answer':'x'},'failure':'confusion'}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'run'
            with patch('kylin_memory_bench.runner.create_adapter',return_value=Fake()):
                execute([case],{'schema_version':'1.0','agents':[{'id':'fixture','kind':'baseline','policy':'selective'}]},output)
            with self.assertRaisesRegex(Exception,'two sessions'):verify_run(output)
            self.assertTrue(verify_reader(output,case)['valid'])
            score=output/'scores.json';saved=score.read_text();score.write_text('{}')
            with self.assertRaisesRegex(Exception,'score differs'):verify_reader(output,case)
            score.write_text(saved)
            events=output/'evidence.jsonl';record=json.loads(events.read_text());record['prompt']='changed';events.write_text(json.dumps(record)+'\n')
            with self.assertRaisesRegex(Exception,'evidence chain'):verify_reader(output,case)
