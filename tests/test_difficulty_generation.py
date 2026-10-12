import importlib.util
import unittest
from pathlib import Path
from kylin_memory_bench.common import digest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('generate_difficulty',ROOT/'scripts/generate_difficulty.py')
generator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class DifficultyGenerationTests(unittest.TestCase):
    def test_predeclared_pairs_and_seed(self):
        first=generator.build_cases()
        self.assertEqual(first,generator.build_cases())
        self.assertNotEqual(digest(first),digest(generator.build_cases(20261012)))
        generator.validate_pairs(first)
        self.assertEqual(len(first),12)
        self.assertEqual(len({c['difficulty_pair'] for c in first}),6)

    def test_answer_and_contract_isolation(self):
        for case in generator.build_cases():
            for turn in case['steps']:
                for check in turn['checks']:
                    self.assertIn(check['measurement_domain'],('content','artifact','action','memory'))
                    if check['source']=='response':
                        self.assertIn(check['op'],('equals','one_of'))
                        self.assertTrue(check.get('pointer'))
            self.assertGreaterEqual(len({s['session'] for s in case['steps']}),2)

    def test_confirmation_and_artifact_conditions(self):
        cases=generator.build_cases()
        for c in cases:
            if c['dimension']=='boundary':
                self.assertEqual([s['id'] for s in c['steps']],['store','revoke','confirm','after-revoke'])
            if c['dimension']=='reuse':
                self.assertEqual(len(c['steps'][-1]['checks']),7)


if __name__=='__main__':unittest.main()
