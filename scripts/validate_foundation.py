#!/usr/bin/env python3
"""Validate offline replay and reference process state in a network namespace.

Run as an unprivileged user via unshare --net and env -i; this does not assess
real agents' memory algorithms, TTL, bare-metal boot or complete deletion.
"""
import argparse
import datetime
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kylin_memory_bench.adapters import External
from kylin_memory_bench.common import BenchError, file_digest, write_json
from kylin_memory_bench.runner import platform_info, verify_run


def validate():
    assert platform_info()['is_openkylin'], 'Requires openKylin'
    interfaces = sorted(name for _, name in socket.if_nameindex())
    assert interfaces == ['lo'], 'Requires isolated network namespace'
    assert not any(any(s in name.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PROXY', 'PASSWORD'))
                   for name in os.environ), 'Requires credential-free environment'
    original = []
    for name in ('openkylin-core', 'openkylin-challenge'):
        directory = ROOT / 'examples' / name
        original.append({'suite': name, **verify_run(directory),
                         'evidence_sha256': file_digest(directory / 'evidence.jsonl')})
    with tempfile.TemporaryDirectory(prefix='kmb-foundation-') as temp:
        temp = Path(temp)
        copy = temp / 'tampered'
        copy.mkdir()
        source = ROOT / 'examples/openkylin-core'
        for name in ('manifest.json', 'config.json', 'dataset.jsonl', 'evidence.jsonl', 'scores.json'):
            shutil.copyfile(source / name, copy / name)
        lines = (copy / 'evidence.jsonl').read_text().splitlines()
        row = json.loads(lines[0])
        row['prompt'] += ' TAMPERED'
        lines[0] = json.dumps(row, ensure_ascii=False)
        (copy / 'evidence.jsonl').write_text('\n'.join(lines) + '\n')
        try:
            verify_run(copy)
        except BenchError as exc:
            rejection = str(exc)
        else:
            raise AssertionError('Tampered copy was accepted')
        script = temp / 'reference.py'
        script.write_text('import json,sys,os\nfrom pathlib import Path\nr=json.load(sys.stdin)\np=Path("state.json")\nn=json.loads(p.read_text())["count"]+1 if p.exists() else 1\np.write_text(json.dumps({"count":n}))\nprint(json.dumps({"text":json.dumps({"count":n,"pid":os.getpid()})}))\n')
        config = {'kind': 'command', 'command': ['{python}', str(script)]}
        a, b = temp / 'a', temp / 'b'
        a.mkdir(); b.mkdir()
        def turn(workspace, session):
            request = {'protocol_version': '1.0', 'session_id': session,
                       'day': 0, 'prompt': 'reference count', 'workspace': str(workspace)}
            return json.loads(External(config, workspace).turn(request)['text'])
        observations = [turn(a, 'session-a'), turn(a, 'new-session'), turn(b, 'session-b')]
        assert [r['count'] for r in observations] == [1, 2, 1]
        assert len({r['pid'] for r in observations}) == 3
    return {'schema_version': '1.0', 'passed': True,
            'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'environment': platform_info(), 'network_interfaces': interfaces,
            'credential_environment_absent': True, 'original_runs': original,
            'tampered_copy_rejected': True, 'rejection_reason': rejection,
            'reference_process_observations': observations,
            'scope': 'Offline replay in a new credential-free network namespace; reference subprocess persistence and workspace isolation only. Not real-agent TTL, complete deletion or bare-metal validation.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Refusing to overwrite validation evidence')
    result = validate()
    write_json(args.output, result)
    print('FOUNDATION PASS: offline originals, rejected tampering, reference counts 1/2/1 in three processes.')


if __name__ == '__main__':
    main()
