import copy
import unittest

from experiments.math_memory.math_core import (make_inputs, solve, rational_equal,
                                              determinant_series)
from experiments.math_memory.prototype import build, recall, grade


class MathMemoryTests(unittest.TestCase):
    def test_hand_derived_example_and_counterfeit_certificate(self):
        inputs = make_inputs([[1, 1], [1, -1]], [2, 3])
        result = solve(inputs)
        self.assertEqual(result['c4'], '-13/36')
        self.assertEqual(result['c6'], '-37/972')
        self.assertEqual(result['certificate']['residual'], ['0', '0', '0'])
        self.assertNotEqual(determinant_series(inputs, ['1', '-13/36', '0'])[2], 0)

    def test_rotated_branches_and_negative_spectrum(self):
        for u in ((1, 2), (2, -3), (0, 1)):
            for k in (-3, 1, 4):
                inputs = make_inputs([[2, -1, 3], [-2, 3, 1]], [-2, 5, 7], u, k, 9)
                self.assertEqual(solve(inputs)['certificate']['residual'], ['0']*3)

    def test_semantic_rationals_reject_booleans_and_approximation(self):
        self.assertTrue(rational_equal('1/2', '0.5'))
        self.assertTrue(rational_equal('1/2', '2/4'))
        self.assertFalse(rational_equal('1', True))
        self.assertFalse(rational_equal('1/3', '0.333333'))

    def test_controls_and_specific_failure_localization(self):
        cases, gold = build()
        self.assertEqual(len(cases), 24)
        for case in cases:
            answer = {'inputs': recall(case), 'result': solve(recall(case), case['order'])}
            observed = grade(case, gold[case['id']], answer)
            self.assertTrue(observed['inputs'], case['id'])
            self.assertTrue(observed['math'], case['id'])
        case = next(c for c in cases if c['id'] == 'revisions-high--memory')
        inputs = recall(case, 'stale')
        stale = grade(case, gold[case['id']], {'inputs': inputs, 'result': solve(inputs, 6)})
        self.assertFalse(stale['inputs'])
        self.assertTrue(stale['consistent_with_reported_inputs'])
        self.assertIsNone(stale['math_given_correct_inputs'])
        wrong = copy.deepcopy(gold[case['id']])
        wrong['result']['c6'] = '100'
        observed = grade(case, gold[case['id']], wrong)
        self.assertTrue(observed['inputs'])
        self.assertFalse(observed['math'])
        self.assertFalse(observed['algebra_residual'])
        self.assertFalse(observed['math_given_correct_inputs'])
        missing_file = grade(case, gold[case['id']], gold[case['id']], '/nonexistent/research-certificate.json')
        self.assertTrue(missing_file['format'])
        self.assertTrue(missing_file['math'])
        self.assertFalse(missing_file['artifact'])

    def test_gold_not_in_input_and_matched_controls(self):
        import json
        cases, gold = build()
        for case in cases:
            self.assertNotIn('"residual": [', json.dumps(case))
            self.assertNotIn('"c4": "'+str(gold[case['id']]['result']['c4'])+'"', json.dumps(case))
        for family in {c['profile'] for c in cases}:
            arms = [c for c in cases if c['profile'] == family]
            self.assertEqual(gold[arms[0]['id']], gold[arms[1]['id']])
            self.assertEqual(gold[arms[2]['id']]['result']['status'], 'insufficient')
        regular = next(c for c in cases if c['id'] == 'applicability-regular--memory')
        singular = next(c for c in cases if c['id'] == 'applicability-singular--memory')
        self.assertEqual(gold[regular['id']]['result']['status'], 'ok')
        self.assertEqual(gold[singular['id']]['result']['status'], 'method_invalid')

    def test_native_pilot_protocol_and_formula_support(self):
        import json
        import tempfile
        from pathlib import Path
        from experiments.math_memory.native_pilot import prepare, SELECTED
        from kylin_memory_bench.dataset import load_dataset
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)/'frozen'
            prepare(root)
            cases = load_dataset(root/'dataset.jsonl')
            self.assertEqual(tuple(c['id'] for c in cases), SELECTED)
            for case in cases:
                self.assertGreaterEqual(len(case['steps']), 2)
                self.assertIn('统一数学支持', case['steps'][-1]['prompt'])
                self.assertEqual(case['steps'][-1]['checks'][1]['source'], 'artifact')
                for step in case['steps']:
                    self.assertNotIn('"result": {"status": "ok"', step['prompt'])

    def test_revised_protocol_oracle_and_supersession(self):
        import json
        import tempfile
        from pathlib import Path
        from experiments.math_memory.revised_pilot import prepare
        with tempfile.TemporaryDirectory() as parent:
            root=Path(parent)/'v2'
            prepare(root)
            cases=json.loads((root/'learner-cases.json').read_text())
            gold=json.loads((root/'gold.json').read_text())
            self.assertEqual(len(cases),6)
            for case in cases:
                inputs=recall(case)
                observed=grade(case,gold[case['id']],{'inputs':inputs,'result':solve(inputs,case['order'])})
                self.assertTrue(observed['inputs'],case['id'])
                self.assertTrue(observed['math'],case['id'])
                self.assertIn('后来到达的accepted snapshot明确替代',case['sessions'][-1]['prompt'])


if __name__ == '__main__':
    unittest.main()
