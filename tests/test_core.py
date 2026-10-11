import copy
import json
import tempfile
import unittest
from pathlib import Path

from kylin_memory_bench.common import BenchError, contained, digest, strict_json, write_text
from kylin_memory_bench.dataset import describe, load_dataset, validate_case
from kylin_memory_bench.generate import check, generate, save_dataset
from kylin_memory_bench.scoring import aggregate, evaluate, metric


class DatasetTests(unittest.TestCase):
    def test_generator_is_reproducible_and_seed_sensitive(self):
        self.assertEqual(digest(generate(1)), digest(generate(1)))
        self.assertNotEqual(digest(generate(1)), digest(generate(2)))

    def test_six_dimensions_and_four_evidence_sources(self):
        data = describe(generate())
        self.assertEqual(data['cases'], 36)
        self.assertTrue(all(n == 6 for n in data['dimensions'].values()))
        self.assertTrue(all(n > 0 for n in data['sources'].values()))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.jsonl'
            save_dataset(path, generate(variants=1))
            self.assertEqual(load_dataset(path), generate(variants=1))

    def test_rejects_invalid_cases(self):
        mutations = [lambda c: c.update(schema_version='9'), lambda c: c.update(id='../escape'),
                     lambda c: c.update(synthetic=False), lambda c: c['steps'][0].update(day=-1),
                     lambda c: c['steps'][-1].update(id=c['steps'][0]['id']),
                     lambda c: c['steps'][0]['checks'][0].update(weight=-1),
                     lambda c: c['steps'][0]['checks'][0].update(weight=True),
                     lambda c: c['steps'][0]['checks'][0].update(source='prompt'),
                     lambda c: c['steps'][0]['checks'][0].update(value='')]
        for mutate in mutations:
            case = generate(variants=1)[0]
            mutate(case)
            with self.subTest(case=case):
                with self.assertRaises(BenchError):
                    validate_case(case)

    def test_duplicate_case_id_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'data.jsonl'
            case = generate(variants=1)[0]
            save_dataset(path, [case, case])
            with self.assertRaises(BenchError):
                load_dataset(path)
        for value in ('{"x":1,"x":2}', '{"x":NaN}', '{'):
            with self.assertRaises(BenchError):
                strict_json(value)

    def test_single_session_is_not_long_term(self):
        case = generate(variants=1)[0]
        for step in case['steps']:
            step['session'] = 'one'
        with self.assertRaises(BenchError):
            validate_case(case)

    def test_path_containment(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('../secret', '/etc/passwd', 'C:/secret', 'a/../../b', 'a\\b', 'a//b', 'a/./b', 'a:ads', 'NUL', 'a/CON.txt', 'a/.. ', 'a.'):
                with self.subTest(path=path), self.assertRaises(BenchError):
                    contained(tmp, path)
            self.assertEqual(contained(tmp, 'a/中文.txt'), Path(tmp).resolve() / 'a/中文.txt')

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'real').mkdir()
            try:
                (root / 'link').symlink_to(root / 'real', target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation not permitted on this host')
            with self.assertRaises(BenchError):
                contained(root, 'link/file')


class AtomicWriteTests(unittest.TestCase):
    def test_transient_windows_replace_is_retried_without_losing_data(self):
        import os
        from unittest.mock import patch
        original = os.replace
        failure = PermissionError('sharing violation')
        failure.winerror = 32
        calls = []
        def replace(source, destination):
            calls.append(destination)
            if len(calls) < 3:
                raise failure
            original(source, destination)
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.common.os.replace', side_effect=replace), patch('kylin_memory_bench.common.time.sleep'):
            path = Path(tmp)/'memory.json'
            write_text(path, 'new content')
            self.assertEqual(path.read_text(), 'new content')
            self.assertEqual(len(calls), 3)

    def test_persistent_permission_error_is_bounded_and_original_survives(self):
        from unittest.mock import patch
        failure = PermissionError('denied')
        failure.winerror = 5
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'memory.json'
            path.write_text('old content')
            with patch('kylin_memory_bench.common.os.replace', side_effect=failure) as replace, patch('kylin_memory_bench.common.time.sleep'):
                with self.assertRaises(PermissionError):
                    write_text(path, 'new content')
                self.assertEqual(replace.call_count, 7)
            self.assertEqual(path.read_text(), 'old content')
            self.assertEqual(list(Path(tmp).glob('.kmb-*')), [])


class ScoringTests(unittest.TestCase):
    def event(self, text='{"answer":"青色"}', memory=None, actions=None, artifacts=None):
        return {'event_id': '1', 'response': {'text': text, 'memory': memory, 'actions': actions},
                'artifacts': artifacts or {}}

    def test_structured_equality_prevents_negated_keyword_false_positive(self):
        rule = check('a', 'response', 'equals', '青色', pointer='/answer')
        for text in ('我不喜欢青色', '{"answer":"不喜欢青色"}', '{"answer":"青色，也可以红色"}'):
            self.assertEqual(evaluate(rule, self.event(text))['status'], 'fail')
        self.assertEqual(evaluate(rule, self.event())['status'], 'pass')

    def test_fenced_json_allowed_but_commentary_not(self):
        rule = check('a', 'response', 'equals', '青色', pointer='/answer')
        self.assertEqual(evaluate(rule, self.event('```json\n{"answer":"青色"}\n```'))['status'], 'pass')
        self.assertEqual(evaluate(rule, self.event('答案是 {"answer":"青色"}'))['category'], 'invalid_response')

    def test_unknown_is_not_failure_or_success(self):
        rule = check('a', 'memory', 'excludes', 'SYNTHETIC', 'wrong_persistence')
        self.assertEqual(evaluate(rule, None)['status'], 'unknown')
        self.assertEqual(evaluate(rule, self.event())['status'], 'unknown')
        partial = self.event(memory={'text': '', 'complete': False})
        self.assertEqual(evaluate(rule, partial)['status'], 'unknown')
        full = self.event(memory={'text': '', 'complete': True})
        self.assertEqual(evaluate(rule, full)['status'], 'pass')
        seen = self.event(memory={'text': 'SYNTHETIC', 'complete': False})
        self.assertEqual(evaluate(rule, seen)['status'], 'fail')

    def test_positive_partial_memory(self):
        rule = check('a', 'memory', 'contains', 'blue')
        self.assertEqual(evaluate(rule, self.event(memory={'text': 'blue', 'complete': False}))['status'], 'pass')
        self.assertEqual(evaluate(rule, self.event(memory={'text': 'red', 'complete': False}))['status'], 'unknown')

    def test_runtime_error_is_not_memory_failure(self):
        result = evaluate(check('a', 'response', 'equals', 'x'), {'event_id': '2', 'error': 'timeout'})
        self.assertEqual((result['status'], result['category']), ('error', 'execution_error'))

    def test_artifact_must_exist(self):
        rule = check('a', 'artifact', 'equals', 'ok', path='out.txt', failure='wrong_reuse')
        self.assertEqual(evaluate(rule, self.event('已写入'))['status'], 'unknown')
        self.assertEqual(evaluate(rule, self.event(artifacts={'out.txt': {'exists': False}}))['status'], 'fail')
        self.assertEqual(evaluate(rule, self.event(artifacts={'out.txt': {'exists': True, 'text': 'ok'}}))['status'], 'pass')

    def test_actions_require_actual_trace(self):
        rule = check('a', 'actions', 'json_subset', {'name': 'write_file', 'arguments': {'path': 'a'}})
        self.assertEqual(evaluate(rule, self.event())['status'], 'unknown')
        self.assertEqual(evaluate(rule, self.event(actions=[]))['status'], 'fail')
        self.assertEqual(evaluate(rule, self.event(actions=[{'name': 'write_file', 'arguments': {'path': 'a', 'text': 'ok'}}]))['status'], 'pass')

    def test_bounds_keep_unknowns_in_denominator(self):
        m = metric([{'weight': 1, 'status': 'pass'}, {'weight': 1, 'status': 'fail'}, {'weight': 2, 'status': 'unknown'}])
        self.assertEqual((m['score'], m['coverage'], m['lower_bound'], m['upper_bound']), (.5, .5, .25, .75))
        self.assertIsNone(metric([{'weight': 1, 'status': 'error'}])['score'])

    def test_type_strictness_and_omission(self):
        rule = check('a', 'response', 'equals', 1, pointer='/answer')
        self.assertEqual(evaluate(rule, self.event('{"answer":true}'))['status'], 'fail')
        self.assertEqual(evaluate(rule, self.event('{"answer":null}'))['category'], 'omission')
        null_rule = check('a', 'response', 'equals', None, pointer='/answer')
        self.assertEqual(evaluate(null_rule, self.event('{"answer":null}'))['status'], 'pass')
        self.assertEqual(evaluate(null_rule, self.event('{}'))['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
