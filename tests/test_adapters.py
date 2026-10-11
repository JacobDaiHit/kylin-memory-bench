import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kylin_memory_bench.adapters import External, create_adapter, load_config, process, redact, snapshot, validate_response
from kylin_memory_bench.common import BenchError, write_json


class AdapterTests(unittest.TestCase):
    def request(self, workspace, session='s1'):
        return {'protocol_version': '1.0', 'session_id': session, 'day': 2, 'prompt': '中文 "quotes" $(noop)', 'workspace': str(workspace)}

    def test_command_protocol_is_utf8_and_has_no_shell_expansion(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            script = workspace / 'adapter.py'
            script.write_text('import sys,json\nsys.stdout.reconfigure(encoding="utf-8")\nr=json.load(sys.stdin)\nprint(json.dumps({"text":r["prompt"]},ensure_ascii=False))\n', encoding='utf-8')
            adapter = External({'kind': 'command', 'command': ['{python}', str(script)]}, workspace)
            request = self.request(workspace)
            self.assertEqual(adapter.turn(request)['text'], request['prompt'])

    def test_command_persists_workspace_state_across_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            script = workspace / 'adapter.py'
            script.write_text('from pathlib import Path\nimport json,sys\nr=json.load(sys.stdin)\np=Path("counter")\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nprint(json.dumps({"text":str(n)}))\n', encoding='utf-8')
            adapter = External({'kind': 'command', 'command': ['{python}', str(script)]}, workspace)
            self.assertEqual(adapter.turn(self.request(tmp))['text'], '1')
            self.assertEqual(adapter.turn(self.request(tmp, 'new'))['text'], '2')

    def test_timeout_and_failure_and_bounded_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            start = time.monotonic()
            with self.assertRaisesRegex(BenchError, 'timeout'):
                process([sys.executable, '-c', 'import time; time.sleep(10)'], tmp, env, '', .1)
            self.assertLess(time.monotonic()-start, 5)
            with self.assertRaisesRegex(BenchError, 'exited 7'):
                process([sys.executable, '-c', 'raise SystemExit(7)'], tmp, env, '', 5)
            with self.assertRaisesRegex(BenchError, 'limit'):
                process([sys.executable, '-c', 'print("x"*3000000)'], tmp, env, '', 5)

    def test_malformed_response_rejected(self):
        for response in ({}, {'text': 2}, {'text': '', 'memory': {'text': '', 'complete': 'yes'}},
                         {'text': '', 'actions': ['write_file']}):
            with self.subTest(response=response), self.assertRaises(BenchError):
                validate_response(response)

    def test_environment_is_isolated_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'TEST_API_KEY': 'secret-value', 'UNRELATED_PRIVATE_VALUE': 'private'}):
            adapter = External({'kind': 'command', 'command': ['echo'], 'env_allow': ['TEST_API_KEY']}, tmp)
            self.assertEqual(adapter.env['TEST_API_KEY'], 'secret-value')
            self.assertNotIn('UNRELATED_PRIVATE_VALUE', adapter.env)
            self.assertEqual(Path(adapter.env['HOME']), Path(tmp).resolve() / '.home')
            self.assertEqual(redact({'text': 'secret-value', 'api_key': 'x'}, ['secret-value']), {'text': '[REDACTED]', 'api_key': '[REDACTED]'})

    def test_config_duplicate_ids_shell_strings_and_invalid_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'c.json'
            for agents in ([{'id': 'a', 'kind': 'command', 'command': 'echo bad'}],
                           [{'id': 'a', 'kind': 'baseline', 'policy': 'selective', 'timeout': 0}],
                           [{'id': 'a', 'kind': 'baseline', 'policy': 'selective'}] * 2):
                write_json(path, {'schema_version': '1.0', 'agents': agents})
                with self.assertRaises(BenchError):
                    load_config(path)

    def test_snapshot_partial_by_default_and_unreadable_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'MEMORY.md'
            path.write_text('durable', encoding='utf-8')
            observed = snapshot(tmp, ['*.md'])
            self.assertEqual(observed['text'], 'durable')
            self.assertFalse(observed['complete'])
            path.write_bytes(b'\xff\xff')
            self.assertFalse(snapshot(tmp, ['*.md'], complete=True)['complete'])

    def test_openclaw_envelopes_and_unknown_actions(self):
        for raw in ({'ok': True, 'final': 'answer'}, {'result': {'payloads': [{'text': 'answer'}], 'meta': {}}}):
            with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.adapters.process', return_value=json.dumps(raw)) as proc:
                adapter = External({'kind': 'openclaw', 'model': 'provider/model'}, tmp)
                result = adapter.turn(self.request(tmp))
                self.assertEqual(result['text'], 'answer')
                self.assertIsNone(result['actions'])
                self.assertFalse(result['memory']['complete'])
                argv = proc.call_args[0][0]
                self.assertIn('--local', argv)
                self.assertNotIn('--deliver', argv)
                self.assertNotIn('--yolo', argv)

    def test_openclaw_errors_rejected_even_when_process_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.adapters.process', return_value='{"ok":false,"final":"fail"}'):
            with self.assertRaises(BenchError):
                External({'kind': 'openclaw'}, tmp).turn(self.request(tmp))

    def test_openclaw_malformed_envelopes_are_actionable_errors(self):
        for raw in ('[]', '{"result":null}', '{"payloads":null}', '{"meta":null}'):
            with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.adapters.process', return_value=raw):
                with self.assertRaises(BenchError):
                    External({'kind': 'openclaw'}, tmp).turn(self.request(tmp))

    def test_hermes_stream_session_resume_and_boundaries(self):
        output = '\n'.join([json.dumps({'type': 'tool_use', 'name': 'write_file', 'input': {'path': 'a'}}),
                            json.dumps({'type': 'result', 'exit_code': 0, 'text': 'answer', 'session_id': 'native-1'})])
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.adapters.process', return_value=output) as proc:
            adapter = External({'kind': 'hermes'}, tmp)
            result = adapter.turn(self.request(tmp))
            self.assertEqual(result['actions'][0]['arguments']['path'], 'a')
            self.assertNotIn('--resume', proc.call_args[0][0])
            adapter.turn(self.request(tmp))
            self.assertIn('native-1', proc.call_args[0][0])
            adapter.turn(self.request(tmp, 'different-session'))
            self.assertNotIn('--resume', proc.call_args[0][0])

    def test_hermes_requires_successful_terminal_record(self):
        for raw in ('{"type":"text","text":"hello"}', '{"type":"result","exit_code":1,"text":"error"}'):
            with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.adapters.process', return_value=raw):
                with self.assertRaises(BenchError):
                    External({'kind': 'hermes'}, tmp).turn(self.request(tmp))

    @unittest.skipIf(os.name == 'nt', 'Hermes dependency links require POSIX symlinks')
    def test_hermes_shares_only_dependency_installations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deps, work = root/'shared', root/'case'
            (deps/'installs').mkdir(parents=True)
            (deps/'tools').mkdir()
            (deps/'memories').mkdir()
            (deps/'memories'/'MEMORY.md').write_text('must not leak')
            work.mkdir()
            adapter = External({'kind': 'hermes', 'dependency_home': str(deps)}, work)
            self.assertTrue((work/'.hermes'/'installs').is_symlink())
            self.assertEqual(adapter.env['HERMES_RUNTIME_DIR'], str(deps/'tools'))
            self.assertEqual(adapter.env['HERMES_DISABLE_LAZY_INSTALLS'], '1')
            self.assertFalse((work/'.hermes'/'memories').exists())
            self.assertEqual(snapshot(work, ['.hermes/memories/*.md'])['text'], '')
            self.assertEqual((work/'.home').stat().st_mode & 0o777, 0o700)
            self.assertEqual((work/'.hermes').stat().st_mode & 0o777, 0o700)

    def test_hermes_missing_dependency_home_fails_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BenchError, 'requires installs'):
                External({'kind': 'hermes', 'dependency_home': str(Path(tmp)/'missing')}, tmp)


if __name__ == '__main__':
    unittest.main()
