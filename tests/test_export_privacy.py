import importlib.util
from pathlib import Path
import unittest
import json
import subprocess
import sys
import tempfile
from unittest.mock import patch
from kylin_memory_bench.generate import generate
from kylin_memory_bench.runner import execute, verify_run

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/export_run.py'
spec = importlib.util.spec_from_file_location('export_run', SCRIPT)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class ExportPrivacyTests(unittest.TestCase):
    def test_public_audit_removes_private_values_and_freeform_errors(self):
        rows = [{'at': '2026-10-11', 'event': 'completion', 'model': 'deepseek-flash',
                 'balance_before_cny': 'private-balance', 'floor_cny': 'private-floor',
                 'reason': 'private-auth', 'unexpected_account': {'secret': 'private'},
                 'usage': {'total_tokens': 42}, 'request_sha256': 'abc'}]
        clean = export.public_audit(rows)[0]
        self.assertEqual(clean['usage'], {'total_tokens': 42})
        self.assertEqual(clean['request_sha256'], 'abc')
        self.assertNotIn('reason', clean)
        self.assertNotIn('balance_before_cny', clean)
        self.assertNotIn('unexpected_account', clean)
        self.assertEqual(clean['private_fields_removed'],
                         ['balance_before_cny', 'floor_cny', 'reason', 'unexpected_account'])
        self.assertEqual(rows[0]['balance_before_cny'], 'private-balance')

    def test_interrupted_export_requires_explicit_flag_and_preserves_source(self):
        class InterruptedAdapter:
            count = 0
            def turn(self, request):
                self.count += 1
                if self.count == 2:
                    raise KeyboardInterrupt()
                return {'text': '{}'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / 'source', root / 'export'
            with patch('kylin_memory_bench.runner.create_adapter', return_value=InterruptedAdapter()):
                with self.assertRaises(KeyboardInterrupt):
                    execute(generate(variants=1)[:1], {'agents': [{'id': 'a', 'kind': 'baseline', 'policy': 'selective'}]}, source)
            originals = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
            refused = subprocess.run([sys.executable, str(SCRIPT), str(source), str(destination)], capture_output=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertFalse(destination.exists())
            accepted = subprocess.run([sys.executable, str(SCRIPT), str(source), str(destination), '--allow-interrupted'], capture_output=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr.decode())
            self.assertEqual(verify_run(destination)['status'], 'interrupted')
            metadata = json.loads((destination / 'experiment.json').read_text())
            self.assertIn('not a completed three-trial result', metadata['scores_origin'])
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}, originals)
            self.assertFalse((source / 'scores.json').exists())
