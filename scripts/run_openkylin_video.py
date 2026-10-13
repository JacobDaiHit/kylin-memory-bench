"""Run both native agents from real openKylin using private local model bridges.

Core runner and this entry use only the standard library. The Ubuntu bridge
owns OAuth; this process receives only temporary loopback credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from kylin_memory_bench.common import digest, write_json
from kylin_memory_bench.runner import execute, platform_info, verify_run

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    environment = platform_info()
    if not environment['is_openkylin']:
        raise ValueError('This recording entry requires actual openKylin')
    output = args.output.resolve()
    if not str(output).startswith('/home/kmb/.local/share/kmb-live/runs/kmb-plan-'):
        raise ValueError('Use an isolated kmb-plan-* recording directory under user kmb')
    if output.exists():
        raise ValueError('Refusing to overwrite a recording run')
    control = json.loads(args.bridge_config.read_text(encoding='utf-8'))
    if control['model'] != 'gpt-5.6-luna':
        raise ValueError('Unexpected model')
    for name, value in control['environment'].items():
        if not name.startswith('KMB_KYLIN_VIDEO_KEY_'):
            raise ValueError('Unexpected environment field')
        os.environ[name] = value
    bins = Path('/home/kmb/.cache/kmb-video/bin')
    bins.mkdir(parents=True, exist_ok=True)
    for agent in ('openclaw', 'hermes'):
        wrapper = bins/(agent+'-isolated')
        shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh', wrapper)
        wrapper.chmod(0o700)
    preflight_workspace = output.with_name(output.name+'-isolation')/'workspaces/probe'
    preflight_workspace.mkdir(parents=True, exist_ok=False)
    (preflight_workspace/'allowed.txt').write_text('workspace-only', encoding='utf-8')
    checked = subprocess.run([str(bins/'openclaw-isolated'), '--isolation-probe'],
        cwd=preflight_workspace, capture_output=True, text=True, timeout=30)
    preflight = json.loads(checked.stdout)
    if checked.returncode or not all(preflight.values()):
        raise RuntimeError('Isolation preflight failed; no model calls are authorized by this entry')
    if preflight.get('installed_benchmark_data_hidden') is not True or preflight.get('installed_evaluator_material_hidden') is not True:
        raise RuntimeError('Installed evaluator isolation was not verified')
    print('ISOLATION PREFLIGHT PASS: checkout, installed answers, credentials and peer workspaces hidden', flush=True)
    cases, seen = [], set()
    for line in (ROOT/'kylin_memory_bench/data/sample.jsonl').read_text(encoding='utf-8').splitlines():
        case = json.loads(line)
        if case['dimension'] not in seen:
            seen.add(case['dimension'])
            cases.append(case)
    if len(cases) != 6 or {a['kind'] for a in control['agents']} != {'openclaw', 'hermes'}:
        raise ValueError('Expected six dimensions and both native agents')
    sources = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (
        'scripts/run_openkylin_video.py', 'scripts/serve_luna_video_bridges.py',
        'scripts/isolated_native_plan.sh', 'scripts/chatgpt_plan_bridge.py',
        'kylin_memory_bench/adapters.py', 'kylin_memory_bench/runner.py')}
    protocol = {'protocol': 'openkylin-luna-video-2', 'model': control['model'],
        'environment': environment, 'case_ids': [c['id'] for c in cases],
        'dataset_sha256': digest(cases), 'source_sha256': sources,
        'repeats': 1, 'planned_events': 56, 'jobs': 2,
        'scope': 'Real openKylin framework and native agents; Ubuntu owns only model relay and stateless embeddings.',
        'retry_policy': 'No evaluator case reruns; native recovery retained.',
        'server_output_cap': None, 'oauth_credentials_copied': False,
        'isolation_preflight': preflight}
    # Freeze public protocol outside the agent-visible workspaces before calls.
    protocol_file = bins.parent/(output.name+'-protocol.json')
    write_json(protocol_file, protocol)
    started = time.time()
    print('OPENKYLIN LIVE DEMO: '+environment['os_release']['PRETTY_NAME'], flush=True)
    print('Two native agents; six dimensions; 56 steps; Luna; one round.', flush=True)
    execute(cases, {'schema_version': '1.0', 'agents': control['agents']}, output,
            repeats=1, jobs=2,
            progress=lambda agent, trial, case: print('CASE '+agent+' '+case, flush=True))
    validation = verify_run(output)
    write_json(output/'video-protocol.json', protocol)
    write_json(output/'video-validation.json', dict(validation, elapsed_seconds=time.time()-started))
    print(json.dumps(validation, ensure_ascii=False), flush=True)
    print('Open report.html and radar.svg. Failures and unknowns remain in the report.', flush=True)


if __name__ == '__main__':
    main()
