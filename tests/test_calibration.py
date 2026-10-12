import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('calibrate_scoring', ROOT / 'scripts/calibrate_scoring.py')
CALIBRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALIBRATION)


class CalibrationTests(unittest.TestCase):
    def command(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/calibrate_scoring.py'), *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, encoding='utf-8')

    def write_dataset(self, path, rows):
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')

    def test_frozen_contract_labels_and_four_hand_calculated_metric_groups(self):
        report = CALIBRATION.calculate()
        self.assertTrue(report['passed'])
        self.assertEqual(report['summary']['matched'], 30)
        self.assertEqual(report['summary']['groups'], {'response': 12, 'memory': 8, 'tool_file': 10})
        self.assertEqual(report['summary']['aggregate_matched'], 4)
        self.assertEqual(report['summary']['false_passes'], 0)
        self.assertEqual([row['expected']['lower_bound'] for row in report['aggregate_checks']],
                         [0.666667, 0.25, 0.1, 0.125])
        self.assertIn('no independent human review', report['label_policy'])

    def test_cli_creates_all_formats_and_readonly_recomputation_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'new-output'
            result = self.command('--output', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = {name: (output / name).read_bytes() for name in CALIBRATION.FILENAMES}
            result = self.command('--check', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(saved, {name: (output / name).read_bytes() for name in saved})
            self.assertEqual(len((output / 'results.csv').read_text(encoding='utf-8').splitlines()), 35)
            self.assertIn('未进行独立人工标注复核', (output / 'report.html').read_text(encoding='utf-8'))

    def test_output_refuses_existing_directory_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            marker = output / 'keep.txt'
            marker.write_text('original', encoding='utf-8')
            result = self.command('--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(marker.read_text(encoding='utf-8'), 'original')
            self.assertFalse((output / 'results.json').exists())

    def test_each_saved_format_is_checked_not_only_json_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            report = CALIBRATION.calculate()
            CALIBRATION.write_results(output, report)
            for name in CALIBRATION.FILENAMES:
                path = output / name
                original = path.read_bytes()
                path.write_bytes(original + b' tampered')
                with self.subTest(name=name):
                    result = self.command('--check', output)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(name, result.stderr)
                    self.assertEqual(path.read_bytes(), original + b' tampered')
                path.write_bytes(original)

    def test_gold_mismatch_is_reported_and_not_replaced_with_scorer_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset, output = root / 'changed.jsonl', root / 'output'
            rows = copy.deepcopy(CALIBRATION.load_fixtures(CALIBRATION.DEFAULT_DATASET))
            rows[0]['expected'] = {'status': 'fail', 'category': 'confusion'}
            self.write_dataset(dataset, rows)
            original = dataset.read_bytes()
            result = self.command('--dataset', dataset, '--output', output)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads((output / 'results.json').read_text(encoding='utf-8'))
            self.assertFalse(report['passed'])
            self.assertEqual(report['summary']['matched'], 29)
            self.assertEqual(report['summary']['false_passes'], 1)
            self.assertEqual(report['fixtures'][0]['expected'], {'status': 'fail', 'category': 'confusion'})
            self.assertEqual(dataset.read_bytes(), original)
            result = self.command('--dataset', dataset, '--check', output)
            self.assertEqual(result.returncode, 1)

    def test_newline_styles_do_not_change_logical_fixture_fingerprint(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'crlf.jsonl'
            original = CALIBRATION.DEFAULT_DATASET.read_text(encoding='utf-8')
            path.write_bytes(original.replace('\n', '\r\n').encode('utf-8'))
            self.assertEqual(CALIBRATION.calculate(path), CALIBRATION.calculate())

    def test_html_escapes_constructed_evidence_and_has_no_external_dependencies(self):
        report = CALIBRATION.calculate()
        attack = '</pre><script>alert("fixture")</script>'
        report['fixtures'][0]['title'] = attack
        report['fixtures'][0]['event']['response']['text'] = attack
        page = CALIBRATION.html_text(report)
        self.assertNotIn(attack, page)
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<script', page)
        self.assertNotIn('src=', page)
        self.assertNotIn('href=', page)

    def test_missing_or_duplicate_fixtures_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'invalid.jsonl'
            rows = CALIBRATION.load_fixtures(CALIBRATION.DEFAULT_DATASET)
            for mutated in (rows[:-1], [{**rows[0], 'id': rows[1]['id']}, *rows[1:]]):
                self.write_dataset(path, mutated)
                with self.subTest(count=len(mutated)), self.assertRaises(ValueError):
                    CALIBRATION.load_fixtures(path)


if __name__ == '__main__':
    unittest.main()
