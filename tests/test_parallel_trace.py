import json
import ctypes
import ctypes.util
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from kylin_memory_bench import native_trace
from kylin_memory_bench.adapters import load_config
from kylin_memory_bench.generate import generate
from kylin_memory_bench.runner import execute, read_run, verify_run
from kylin_memory_bench.common import BenchError
from kylin_memory_bench.scoring import evaluate


class TraceTests(unittest.TestCase):
    def test_native_rows_are_session_and_turn_scoped_and_failed_calls_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / native_trace.DATABASE
            db.parent.mkdir(parents=True)
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE transcript_events(session_id TEXT,seq INTEGER,event_json TEXT,event_zstd BLOB,event_utf8_bytes INTEGER)')
            def put(session, seq, msg):
                con.execute('INSERT INTO transcript_events(session_id,seq,event_json) VALUES(?,?,?)', (session, seq, json.dumps({'message': msg})))
            call = {'role':'assistant','content':[{'type':'toolCall','id':'c','name':'write','arguments':{'path':str(Path(tmp)/'file.md'),'content':'ok'}}]}
            result = {'role':'toolResult','toolCallId':'c','isError':False,'content':[{'type':'text','text':'wrote'}]}
            put('other', 0, call)
            put('s1', 0, call); put('s1', 1, result)
            con.commit()
            before = native_trace.cursor(tmp, 's1')
            put('s1', 2, call); put('s1', 3, dict(result, isError=True)); con.commit()
            actions, trace = native_trace.collect(tmp, 's1', before)
            self.assertTrue(trace['available'])
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0]['arguments']['path'], 'file.md')
            self.assertEqual(actions[0]['native']['name'], 'write')
            self.assertEqual(actions[0]['call_seq'], 2)
            check = {'id':'write','source':'actions','op':'json_subset','value':{'name':'write_file'},'failure':'wrong_reuse'}
            score = evaluate(check, {'event_id':'1','response':{'actions':actions}})
            self.assertEqual(score['status'], 'fail')
            put('s1', 4, call); con.commit()
            self.assertIsNone(native_trace.collect(tmp, 's1', 3)[0])
            # A result with its call missing cannot become a complete empty trace.
            put('s1', 5, result); con.commit()
            self.assertIsNone(native_trace.collect(tmp, 's1', 4)[0])
            con.close()

    def test_missing_database_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(native_trace.cursor(tmp, 's'), -1)
            self.assertIsNone(native_trace.collect(tmp, 's', -1)[0])

    @unittest.skipUnless(ctypes.util.find_library('zstd'), 'Native zstd library unavailable')
    def test_native_compressed_rows_decode_and_corrupt_or_oversized_rows_fail_closed(self):
        lib = native_trace.zstd_library()
        lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        lib.ZSTD_compressBound.restype = ctypes.c_size_t
        lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        lib.ZSTD_compress.restype = ctypes.c_size_t
        raw = json.dumps({'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '记忆确认'}]}},ensure_ascii=False).encode()
        output = ctypes.create_string_buffer(lib.ZSTD_compressBound(len(raw)))
        size = lib.ZSTD_compress(output, len(output), raw, len(raw), 3)
        blob = output.raw[:size]
        self.assertEqual(native_trace.decode_event(None, blob, len(raw)), raw.decode())
        for data, expected in [(b'broken', len(raw)), (blob, len(raw)+1), (blob, native_trace.MAX_FILE_BYTES+1)]:
            with self.assertRaises(ValueError):
                native_trace.decode_event(None, data, expected)


class ParallelTests(unittest.TestCase):
    def test_parallel_cases_match_serial_scores_and_each_chain_verifies(self):
        cases = generate(variants=1, noise=1)
        root = Path(__file__).resolve().parents[1]
        config = load_config(root/'kylin_memory_bench/data/baselines.json')
        with tempfile.TemporaryDirectory() as tmp:
            serial = execute(cases, config, Path(tmp)/'one', repeats=2)
            parallel = execute(cases, config, Path(tmp)/'four', repeats=2, jobs=4)
            for a,b in zip(serial['agents'], parallel['agents']):
                self.assertEqual(a['overall'], b['overall'])
                self.assertEqual(a['categories'], b['categories'])
            self.assertTrue(verify_run(Path(tmp)/'four')['valid'])
            _,_,events,_ = read_run(Path(tmp)/'four')
            for a in config['agents']:
                for t in range(2):
                    for c in cases:
                        selected = [e['step_id'] for e in events if e['agent_id']==a['id'] and e['trial']==t and e['case_id']==c['id']]
                        self.assertEqual(selected, [s['id'] for s in c['steps']])

    def test_cases_overlap_without_overlapping_turns_of_one_adapter(self):
        lock = threading.Lock()
        state = {'active':0, 'peak':0}
        class Slow:
            def __init__(self): self.running=False
            def turn(self, request):
                assert not self.running
                self.running=True
                with lock:
                    state['active']+=1
                    state['peak']=max(state['peak'],state['active'])
                time.sleep(.03)
                with lock: state['active']-=1
                self.running=False
                return {'text':'{"answer":null}'}
        config={'agents':[{'id':'spy','kind':'command','command':['fake']}]}
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.runner.create_adapter', side_effect=lambda *_: Slow()):
            execute(generate(variants=1,noise=0),config,Path(tmp)/'run',jobs=3)
            self.assertGreater(state['peak'],1)
            self.assertLessEqual(state['peak'],3)

    def test_unexpected_worker_failure_does_not_deadlock(self):
        with tempfile.TemporaryDirectory() as tmp, patch('kylin_memory_bench.runner.create_adapter', side_effect=RuntimeError('broken worker')):
            with self.assertRaisesRegex(RuntimeError,'broken worker'):
                execute(generate(variants=1), {'agents':[{'id':'x','kind':'command','command':['fake']}]}, Path(tmp)/'run',jobs=2)
            manifest=json.loads((Path(tmp)/'run/manifest.json').read_text())
            self.assertEqual(manifest['status'],'interrupted')

if __name__=='__main__': unittest.main()
