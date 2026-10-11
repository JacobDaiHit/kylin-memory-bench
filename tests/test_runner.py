import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kylin_memory_bench.adapters import load_config
from kylin_memory_bench.common import BenchError, canonical, read_json, write_json
from kylin_memory_bench.generate import generate
from kylin_memory_bench.runner import execute, read_run, verify_run
from kylin_memory_bench.scoring import score_run

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.tmp.name) / 'run'
        cls.cases = generate(variants=1, noise=1)
        cls.config = load_config(ROOT / 'kylin_memory_bench/data/baselines.json')
        cls.report = execute(cls.cases, cls.config, cls.output, repeats=2)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_end_to_end_baselines_distinguish_capability(self):
        scores = [a['overall']['score'] for a in self.report['agents']]
        self.assertEqual(scores, [1.0, .708333, .291667])
        self.assertTrue(all(a['overall']['coverage'] == 1 for a in self.report['agents']))
        self.assertTrue(all(a['stability']['stddev'] == 0 for a in self.report['agents']))
        self.assertIn('wrong_persistence', self.report['agents'][1]['categories'])
        self.assertIn('confusion', self.report['agents'][1]['categories'])

    def test_evidence_verifies_and_report_outputs_exist(self):
        self.assertTrue(verify_run(self.output)['valid'])
        for name in ('manifest.json', 'scores.json', 'evidence.jsonl', 'report.html', 'radar.svg', 'metrics.csv'):
            self.assertGreater((self.output / name).stat().st_size, 100)

    def test_new_sessions_and_no_cross_case_leak(self):
        _, _, events, _ = read_run(self.output)
        selected = [e for e in events if e['agent_id'] == 'selective' and e['trial'] == 0]
        self.assertNotEqual(selected[0]['session_id'], selected[1]['session_id'])
        # First step of the second case cannot see the first case's memory state.
        second = next(e for e in selected if e['case_id'].startswith('retrieval-'))
        self.assertNotIn('会议室', second['response']['memory']['text'])

    def test_never_overwrite_a_run(self):
        with self.assertRaises(BenchError):
            execute(self.cases, self.config, self.output)

    def test_no_gold_is_sent_to_adapter(self):
        seen = []
        class Spy:
            def turn(self, request):
                seen.append(request)
                return {'text': '{"answer":null}'}
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.runner.create_adapter', return_value=Spy()):
            execute(self.cases[:1], {'agents': self.config['agents'][:1]}, Path(tmp) / 'run')
        self.assertTrue(seen)
        for request in seen:
            self.assertEqual(set(request), {'protocol_version', 'session_id', 'day', 'prompt', 'workspace'})

    def test_adapter_error_stops_case_and_preserves_other_cases(self):
        class Broken:
            calls = 0
            def turn(self, request):
                Broken.calls += 1
                raise BenchError('timeout')
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.runner.create_adapter', return_value=Broken()):
            report = execute(self.cases[:2], {'agents': self.config['agents'][:1]}, Path(tmp) / 'run')
            self.assertEqual(report['run_status'], 'completed_with_errors')
            self.assertEqual(Broken.calls, 2)
            self.assertEqual(report['agents'][0]['overall']['coverage'], 0)
            self.assertTrue(verify_run(Path(tmp) / 'run')['valid'])

    def test_tampered_evidence_and_scores_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'copy'
            shutil.copytree(self.output, target)
            scores = read_json(target / 'scores.json')
            scores['agents'][0]['overall']['score'] = .5
            write_json(target / 'scores.json', scores)
            with self.assertRaisesRegex(BenchError, 'independent replay'):
                verify_run(target)
            text = (target / 'evidence.jsonl').read_text(encoding='utf-8')
            (target / 'evidence.jsonl').write_text(text.replace('青色', '红色') if '青色' in text else text.replace('Markdown', 'TEXT'), encoding='utf-8')
            with self.assertRaisesRegex(BenchError, 'hash chain|does not match dataset'):
                read_run(target)

    def test_duplicate_steps_rejected(self):
        manifest, cases, events, _ = read_run(self.output)
        with self.assertRaisesRegex(BenchError, 'Duplicate'):
            score_run(manifest, cases, events + events[:1])

    def test_html_escapes_untrusted_labels(self):
        from kylin_memory_bench.report import render_report
        report = copy.deepcopy(self.report)
        report['agents'][0]['label'] = '<script>alert(1)</script>'
        with tempfile.TemporaryDirectory() as tmp:
            render_report(report, tmp)
            html = (Path(tmp) / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertIn('&lt;script&gt;', html)


if __name__ == '__main__':
    unittest.main()
