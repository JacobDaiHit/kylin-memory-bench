"""Meaningful gate tests: distinguish nonobservation from a capability failure."""
import copy
import importlib.util
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from kylin_memory_bench.common import BenchError, DIMENSIONS, canonical, digest, write_json
from kylin_memory_bench.generate import save_dataset
from kylin_memory_bench.scoring import score_run

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'analyze_difficulty.py'
spec = importlib.util.spec_from_file_location('difficulty_analysis', SCRIPT)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def design():
    agents = [{'id': 'openclaw', 'kind': 'openclaw'}, {'id': 'hermes', 'kind': 'hermes'}]
    cases = []
    for dimension in DIMENSIONS:
        for level in ('low', 'high'):
            cases.append({'schema_version': '1.0', 'id': dimension + '-' + level,
                          'title': dimension + ' ' + level, 'dimension': dimension,
                          'synthetic': True, 'difficulty_pair': dimension,
                          'difficulty_level': level,
                          'steps': [
                              {'id': 'learn', 'kind': 'message', 'session': 'first', 'day': 0,
                               'prompt': 'Learn the private fixture fact.'},
                              {'id': 'recall', 'kind': 'probe', 'session': 'second', 'day': 1,
                               'prompt': 'Return a structured answer.',
                               'checks': [
                                   {'id': 'answer', 'source': 'response', 'op': 'equals',
                                    'pointer': '/answer', 'value': 'gold', 'failure': 'confusion',
                                    'measurement_domain': 'content'},
                                   {'id': 'diagnostic', 'source': 'memory', 'op': 'contains',
                                    'value': 'gold', 'failure': 'omission',
                                    'measurement_domain': 'memory'}]}]})
    manifest = {'schema_version': '1.0', 'run_id': str(uuid.uuid4()), 'status': 'completed',
                'agents': agents, 'repeats': 3, 'dataset_sha256': digest(cases),
                'evidence_head': None, 'implementation_sha256': 'fixture', 'environment': {}}
    return manifest, cases


def score_fixture(manifest, cases, mutate=None):
    agents = []
    for agent in manifest['agents']:
        rows = []
        for trial in range(3):
            for case in cases:
                checks = [
                    {'step_id': 'recall', 'check_id': 'answer', 'source': 'response',
                     'status': 'pass', 'category': 'correct', 'reason': 'fixture', 'evidence_id': '1'},
                    {'step_id': 'recall', 'check_id': 'diagnostic', 'source': 'memory',
                     'status': 'unknown', 'category': 'insufficient_evidence',
                     'reason': 'partial', 'evidence_id': '1'}]
                if mutate:
                    mutate(agent['id'], trial, case, checks)
                rows.append({'case_id': case['id'], 'trial': trial, 'checks': checks})
        agents.append({**agent, 'cases': rows})
    return {'agents': agents}


def mark_fail(check, category='confusion'):
    check.update(status='fail', category=category)


class DifficultyAnalysisTests(unittest.TestCase):
    def test_memory_unknowns_do_not_reduce_behavior_observation_and_ceiling_is_failed_gate(self):
        manifest, cases = design()
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases))
        self.assertEqual(result['overall_ability']['effective_observation_rate'], 1)
        self.assertEqual(result['by_domain']['memory']['unknown_count'], 72)
        self.assertEqual(result['status'], 'failed_gate')
        self.assertEqual(result['case_composition']['counts']['all_pass'], 12)
        self.assertEqual(result['execution_composition']['counts']['all_pass'], 72)

    def test_three_repeatable_family_effects_pass_but_do_not_create_general_ranking(self):
        manifest, cases = design()
        target = set(list(DIMENSIONS)[:3])
        def mutate(agent, trial, case, checks):
            if case['dimension'] in target and case['difficulty_level'] == 'high':
                mark_fail(checks[0])
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases, mutate))
        self.assertEqual(result['status'], 'passed_gate')
        self.assertEqual(result['summary']['difficulty_effect_family_count'], 3)
        self.assertTrue(all(not f['stable_observed_difference'] for f in result['families']))
        self.assertEqual(result['case_composition']['counts']['all_fail'], 3)

    def test_format_failures_are_nonobservation_not_content_errors(self):
        manifest, cases = design()
        def mutate(agent, trial, case, checks):
            if case['difficulty_level'] == 'high':
                mark_fail(checks[0], 'invalid_response')
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases, mutate))
        self.assertEqual(result['overall_ability']['effective_observation_rate'], .5)
        self.assertEqual(result['overall_ability']['effective_correct_rate'], 1)
        self.assertEqual(result['overall_ability']['format_invalid_count'], 36)
        self.assertEqual(result['case_composition']['counts']['indeterminate'], 6)
        self.assertTrue(all(f['mean_drop'] is None for f in result['families']))
        invalid = next(c for c in result['checks'] if c['category'] == 'invalid_response')
        self.assertEqual(invalid['failure_origin'], 'format')
        self.assertFalse(invalid['effectively_observed'])

    def test_execution_errors_unknown_and_mixed_status_never_count_all_pass(self):
        manifest, cases = design()
        def mutate(agent, trial, case, checks):
            if case['id'] == 'retention-high' and trial == 0:
                checks[0].update(status='error', category='execution_error')
            if case['id'] == 'retrieval-high' and trial == 0:
                checks[0].update(status='unknown', category='insufficient_evidence')
            if case['id'] == 'update-high' and agent == 'openclaw':
                mark_fail(checks[0])
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases, mutate))
        self.assertEqual(result['case_composition']['counts'],
                         {'all_pass': 9, 'all_fail': 0, 'disagreement': 1, 'indeterminate': 2})
        self.assertEqual(result['overall_ability']['execution_error_count'], 2)
        self.assertEqual(result['overall_ability']['unknown_count'], 2)

    def test_one_round_large_drop_does_not_satisfy_two_round_direction_gate(self):
        manifest, cases = design()
        def mutate(agent, trial, case, checks):
            if trial == 0 and case['difficulty_level'] == 'high':
                mark_fail(checks[0])
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases, mutate))
        self.assertAlmostEqual(result['families'][0]['mean_drop'], 1 / 3)
        self.assertEqual(result['families'][0]['strict_positive_drop_trials'], 1)
        self.assertFalse(result['families'][0]['difficulty_effect'])
        self.assertEqual(result['status'], 'failed_gate')

    def test_observation_gate_is_independent_of_the_three_family_effect_gate(self):
        manifest, cases = design()
        target = set(list(DIMENSIONS)[:3])
        def fixture(unknown_count):
            unseen = [0]
            def mutate(agent, trial, case, checks):
                if case['dimension'] in target and case['difficulty_level'] == 'high':
                    mark_fail(checks[0])
                elif case['dimension'] not in target and unseen[0] < unknown_count:
                    checks[0].update(status='unknown', category='insufficient_evidence')
                    unseen[0] += 1
            return score_fixture(manifest, cases, mutate)
        above = analysis.summarize(manifest, cases, fixture(7))
        below = analysis.summarize(manifest, cases, fixture(8))
        self.assertEqual(above['summary']['difficulty_effect_family_count'], 3)
        self.assertEqual(below['summary']['difficulty_effect_family_count'], 3)
        self.assertEqual(above['status'], 'passed_gate')
        self.assertEqual(below['status'], 'failed_gate')
        self.assertGreater(above['overall_ability']['effective_observation_rate'], .9)
        self.assertLess(below['overall_ability']['effective_observation_rate'], .9)

    def test_stable_agent_difference_requires_same_direction_two_rounds(self):
        manifest, cases = design()
        def mutate(agent, trial, case, checks):
            if case['dimension'] == 'retention' and agent == 'openclaw' and trial < 2:
                mark_fail(checks[0])
            if case['dimension'] == 'retrieval' and trial == 0 and agent == 'openclaw':
                mark_fail(checks[0])
            if case['dimension'] == 'retrieval' and trial == 1 and agent == 'hermes':
                mark_fail(checks[0])
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases, mutate))
        families = {f['dimension']: f for f in result['families']}
        self.assertEqual(families['retention']['favored_agent'], 'hermes')
        self.assertTrue(families['retention']['stable_observed_difference'])
        self.assertIsNone(families['retrieval']['favored_agent'])

    def test_rejects_incomplete_unpaired_non_native_and_changed_denominators(self):
        manifest, cases = design()
        variants = []
        bad = copy.deepcopy(manifest); bad['repeats'] = 2; variants.append((bad, cases))
        bad = copy.deepcopy(manifest); bad['status'] = 'interrupted'; variants.append((bad, cases))
        bad = copy.deepcopy(manifest); bad['agents'][0]['kind'] = 'baseline'; variants.append((bad, cases))
        variants.append((manifest, cases[:-1]))
        bad_cases = copy.deepcopy(cases); bad_cases[0].pop('difficulty_pair'); variants.append((manifest, bad_cases))
        bad_cases = copy.deepcopy(cases); bad_cases[0]['steps'][-1]['checks'][0].pop('measurement_domain'); variants.append((manifest, bad_cases))
        bad_cases = copy.deepcopy(cases); bad_cases[0]['steps'][-1]['checks'][1]['measurement_domain'] = 'content'; variants.append((manifest, bad_cases))
        bad_cases = copy.deepcopy(cases)
        bad_cases[0]['steps'][-1]['checks'].append({**bad_cases[0]['steps'][-1]['checks'][0], 'id': 'extra'})
        variants.append((manifest, bad_cases))
        for m, c in variants:
            with self.subTest(repeats=m['repeats'], cases=len(c)):
                with self.assertRaises(BenchError):
                    analysis.summarize(m, c, score_fixture(m, c))
        scores = score_fixture(manifest, cases)
        scores['agents'][0]['cases'].pop()
        with self.assertRaises(BenchError):
            analysis.summarize(manifest, cases, scores)

    def test_safe_html_has_event_anchors_and_escapes_native_text(self):
        manifest, cases = design()
        scores = score_fixture(manifest, cases)
        scores['agents'][0]['cases'][0]['checks'][0]['reason'] = '</td><script>alert(1)</script>'
        result = analysis.summarize(manifest, cases, scores)
        rendered = analysis.render_html(result, '../run/evidence.html')
        self.assertIn('../run/evidence.html#event-1', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>alert(1)</script>', rendered)

    def test_publish_refuses_any_existing_destination_and_check_is_read_only(self):
        manifest, cases = design()
        result = analysis.summarize(manifest, cases, score_fixture(manifest, cases))
        result['source']['file_sha256'] = {'evidence.jsonl': 'fixture'}
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent.parent) as tmp:
            run, output = Path(tmp) / 'run', Path(tmp) / 'analysis'
            run.mkdir()
            analysis.publish(result, run, output)
            original = (output / 'difficulty-summary.json').read_bytes()
            with self.assertRaises(BenchError):
                analysis.publish(result, run, run / 'analysis')
            self.assertFalse((run / 'analysis').exists())
            with self.assertRaises(BenchError):
                analysis.publish(result, run, output)
            with mock.patch.object(analysis, 'calculate', return_value=result):
                self.assertEqual(analysis.main(['--run', str(run), '--output', str(output), '--check']), 3)
            self.assertEqual((output / 'difficulty-summary.json').read_bytes(), original)
            changed = copy.deepcopy(result); changed['summary']['difficulty_effect_family_count'] = 6
            write_json(output / 'difficulty-summary.json', changed)
            with mock.patch.object(analysis, 'calculate', return_value=result):
                self.assertEqual(analysis.main(['--run', str(run), '--output', str(output), '--check']), 2)

    def test_real_integrity_replay_preserves_source_and_rejects_evidence_tamper(self):
        manifest, cases = design()
        config = {'agents': manifest['agents']}
        manifest['config_sha256'] = digest(config)
        events, previous = [], None
        for trial in range(3):
            for case in cases:
                for agent in manifest['agents']:
                    for step in case['steps']:
                        event = {'schema_version': '1.0', 'event_id': str(len(events) + 1),
                                 'previous_hash': previous, 'agent_id': agent['id'], 'trial': trial,
                                 'case_id': case['id'], 'step_id': step['id'], 'kind': step['kind'],
                                 'day': step['day'], 'prompt': step['prompt'],
                                 'session_id': str(uuid.uuid5(uuid.UUID(manifest['run_id']),
                                     f"{agent['id']}/{trial}/{case['id']}/{step['session']}")),
                                 'response': {'protocol_version': '1.0', 'text': '{"answer":"gold"}'},
                                 'error': None, 'artifacts': {}, 'duration_ms': 1}
                        event['hash'] = digest(event)
                        previous = event['hash']; events.append(event)
        manifest.update(event_count=len(events), evidence_head=previous, execution_errors=0)
        with tempfile.TemporaryDirectory(dir=SCRIPT.parent.parent) as tmp:
            run = Path(tmp) / 'run'; run.mkdir()
            write_json(run / 'manifest.json', manifest)
            write_json(run / 'config.json', config)
            save_dataset(run / 'dataset.jsonl', cases)
            evidence = ''.join(canonical(e) + '\n' for e in events)
            (run / 'evidence.jsonl').write_text(evidence, encoding='utf-8')
            write_json(run / 'scores.json', score_run(manifest, cases, events))
            before = {p.name: p.read_bytes() for p in run.iterdir()}
            result = analysis.calculate(run)
            self.assertEqual(result['status'], 'failed_gate')
            self.assertEqual(result['source']['event_count'], 144)
            self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})
            (run / 'evidence.jsonl').write_text(evidence.replace('gold', 'evil', 1), encoding='utf-8')
            with self.assertRaises(BenchError):
                analysis.calculate(run)


if __name__ == '__main__':
    unittest.main()
