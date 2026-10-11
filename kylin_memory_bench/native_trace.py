"""Read owned OpenClaw transcript rows, never aggregate telemetry or personal state."""
import sqlite3
import ctypes
import ctypes.util
import functools
from pathlib import Path

from .common import BenchError, MAX_FILE_BYTES, contained, digest, strict_json

DATABASE = '.openclaw/agents/main/agent/openclaw-agent.sqlite'


def connection(workspace):
    path = contained(workspace, DATABASE)
    if not path.is_file():
        return None
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)


def cursor(workspace, session):
    try:
        con = connection(workspace)
        if con is None:
            return -1
        try:
            row = con.execute('SELECT max(seq) FROM transcript_events WHERE session_id=?', (session,)).fetchone()
            return row[0] if row[0] is not None else -1
        finally:
            con.close()
    except (sqlite3.Error, OSError, BenchError):
        return None


def normalized_action(name, arguments, workspace):
    args = dict(arguments)
    # Preserve the native call alongside normalization, including its original path.
    if isinstance(args.get('path'), str):
        path = Path(args['path'])
        if path.is_absolute():
            try:
                args['path'] = path.resolve().relative_to(Path(workspace).resolve()).as_posix()
            except ValueError:
                pass
    return {'name': {'write': 'write_file', 'read': 'read_file'}.get(name, name),
            'arguments': args, 'native': {'name': name, 'arguments': arguments}}


@functools.lru_cache(maxsize=1)
def zstd_library():
    name = ctypes.util.find_library('zstd')
    if not name:
        raise ValueError('Native libzstd unavailable')
    lib = ctypes.CDLL(name)
    lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    lib.ZSTD_decompress.restype = ctypes.c_size_t
    lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
    lib.ZSTD_isError.restype = ctypes.c_uint
    return lib


def decode_event(raw, compressed, expected_bytes):
    if raw is not None:
        return raw
    if type(expected_bytes) is not int or not 0 < expected_bytes <= MAX_FILE_BYTES:
        raise ValueError('Compressed event exceeds limit')
    if not isinstance(compressed, bytes) or len(compressed) > MAX_FILE_BYTES:
        raise ValueError('Invalid compressed event')
    lib = zstd_library()
    output = ctypes.create_string_buffer(expected_bytes)
    size = lib.ZSTD_decompress(output, expected_bytes, compressed, len(compressed))
    if lib.ZSTD_isError(size) or size != expected_bytes:
        raise ValueError('Invalid zstd event')
    return output.raw.decode('utf-8')


def collect(workspace, session, after):
    unavailable = {'source': 'openclaw-sqlite', 'available': False,
                   'reason': 'Transcript missing, unsupported, incomplete or unreadable.'}
    if after is None:
        return None, unavailable
    try:
        con = connection(workspace)
        if con is None:
            return None, unavailable
        try:
            rows, total = [], 0
            source = con.execute('SELECT seq,event_json,event_zstd,event_utf8_bytes FROM transcript_events '
                                 'WHERE session_id=? AND seq>? ORDER BY seq', (session, after))
            for seq, raw, blob, size in source:
                raw = decode_event(raw, blob, size)
                total += len(raw.encode('utf-8'))
                if total > MAX_FILE_BYTES:
                    return None, unavailable
                rows.append((seq, raw))
        finally:
            con.close()
        if not rows:
            return None, unavailable
        calls, actions, hashes = {}, [], []
        for seq, raw in rows:
            entry = strict_json(raw)
            hashes.append({'seq': seq, 'sha256': digest(entry)})
            msg = entry.get('message', {})
            for item in msg.get('content', []) if isinstance(msg.get('content'), list) else []:
                if isinstance(item, dict) and item.get('type') == 'toolCall':
                    if item['id'] in calls:
                        return None, unavailable
                    calls[item['id']] = (seq, item)
            if msg.get('role') == 'toolResult' and msg.get('toolCallId') not in calls:
                return None, unavailable
            if msg.get('role') == 'toolResult' and msg.get('toolCallId') in calls:
                call_seq, call = calls.pop(msg['toolCallId'])
                action = normalized_action(call['name'], call['arguments'], workspace)
                action.update(call_id=msg['toolCallId'], call_seq=call_seq, result_seq=seq,
                              status='failed' if msg.get('isError') else 'success',
                              result=msg.get('content', []))
                actions.append(action)
        # An unmatched call prevents a complete trace claim.
        if calls:
            return None, unavailable
        return actions, {'source': 'openclaw-sqlite', 'available': True, 'session_id': session,
                         'database': DATABASE, 'after_seq': after, 'rows': hashes}
    except (sqlite3.Error, OSError, BenchError, KeyError, TypeError, ValueError, AttributeError):
        return None, unavailable
