import contextlib
import gzip
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from kylin_memory_bench.cli import main
from kylin_memory_bench.common import read_json
from kylin_memory_bench.generate import generate, save_dataset
from kylin_memory_bench.runner import execute

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_generate_validate_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'data.jsonl')
            code, output, _ = self.invoke(['generate', '--output', path, '--variants', '1'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)['cases'], 6)
            self.assertEqual(self.invoke(['validate', path])[0], 0)
            self.assertEqual(self.invoke(['generate', '--output', path])[0], 2)

    def test_bad_json_is_actionable_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.jsonl'
            path.write_text('{"schema_version":"1.0","id":"a","title":"a","dimension":{},"synthetic":true}', encoding='utf-8')
            code, out, err = self.invoke(['validate', str(path)])
            self.assertEqual(code, 2)
            self.assertNotIn('Traceback', err)

    def test_doctor_does_not_claim_openkylin_without_detection(self):
        from unittest.mock import patch
        with patch('kylin_memory_bench.cli.platform_info', return_value={'is_openkylin': False}):
            code, output, _ = self.invoke(['doctor'])
        self.assertEqual(code, 0)
        self.assertIn('still required', json.loads(output)['native_validation'])

    def test_compare_rejects_different_datasets_and_writes_source_index(self):
        config = {'agents': [{'id': 'a', 'kind': 'baseline', 'policy': 'selective'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            execute(generate(variants=1), config, root/'a')
            execute(generate(variants=1, seed=9), config, root/'b')
            code, _, _ = self.invoke(['compare', str(root/'a'), str(root/'b'), '--output', str(root/'bad')])
            self.assertEqual(code, 2)
            code, _, _ = self.invoke(['compare', str(root/'a'), str(root/'a'), '--output', str(root/'good')])
            self.assertEqual(code, 0)
            self.assertTrue((root/'good/sources.json').exists())
            self.assertIn('sources.json', (root/'good/report.html').read_text(encoding='utf-8'))

    def test_native_missing_executable_returns_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            path.write_text('{"schema_version":"1.0","agents":[{"id":"absent","kind":"hermes","executable":"definitely-not-a-real-cli-19386"}]}', encoding='utf-8')
            code, out, _ = self.invoke(['doctor', '--config', str(path)])
            self.assertEqual(code, 3)
            self.assertEqual(len(json.loads(out)['missing_configured_executables']), 1)


class ReleaseTests(unittest.TestCase):
    def test_deb_is_reproducible_and_contains_runtime_data(self):
        import tarfile
        spec = importlib.util.spec_from_file_location('build_release', ROOT/'scripts/build_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            deb, archive = module.build(Path(tmp)/'a')
            again, archive_again = module.build(Path(tmp)/'b')
            self.assertEqual(deb.read_bytes(), again.read_bytes())
            self.assertEqual(archive.read_bytes(), archive_again.read_bytes())
            raw = deb.read_bytes()
            self.assertEqual(raw[:8], b'!<arch>\n')
            entries, offset = {}, 8
            while offset < len(raw):
                header = raw[offset:offset+60]
                name = header[:16].decode().strip().rstrip('/')
                length = int(header[48:58].decode().strip())
                entries[name] = raw[offset+60:offset+60+length]
                offset += 60 + length + length % 2
            self.assertEqual(entries['debian-binary'], b'2.0\n')
            with tarfile.open(fileobj=io.BytesIO(entries['data.tar.gz']), mode='r:gz') as data:
                names = data.getnames()
                from pathlib import PurePosixPath
                members = {str(PurePosixPath(member.name)): member for member in data.getmembers()}
                seen = set()
                for member in data.getmembers():
                    for parent in PurePosixPath(member.name).parents:
                        if str(parent) != '.':
                            self.assertIn(str(parent), seen, 'dpkg needs parent directories before files')
                            self.assertTrue(members[str(parent)].isdir())
                    seen.add(str(PurePosixPath(member.name)))
                self.assertIn('usr/bin/kmb', names)
                self.assertEqual(data.getmember('usr/bin/kmb').mode, 0o755)
                self.assertIn('usr/share/kylin-memory-bench/kylin_memory_bench/data/sample.jsonl', names)
                self.assertFalse(any('.local.json' in n or '__pycache__' in n or 'account-balance-final.json' in n for n in names))


if __name__ == '__main__':
    unittest.main()
