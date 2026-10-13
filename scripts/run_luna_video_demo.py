"""Fixed six-dimensional native Luna demonstration; not a ranking experiment.

Run as a module from the repository with the optional ChatGPT-plan environment.
OAuth remains in the bridge; agents receive only local ephemeral credentials.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time

from kylin_memory_bench.common import digest
from kylin_memory_bench.runner import execute, verify_run
from scripts.chatgpt_plan import TARGET, atomic_private
from scripts.chatgpt_plan_bridge import Bridge
from scripts.plan_native_config import full_configurations

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--embedding-url', default='http://127.0.0.1:18789/v1')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    cases, seen = [], set()
    for line in (ROOT/'kylin_memory_bench/data/sample.jsonl').read_text(encoding='utf-8').splitlines():
        case = json.loads(line)
        if case['dimension'] not in seen:
            seen.add(case['dimension'])
            cases.append(case)
    if len(cases) != 6:
        raise ValueError('Expected all six dimensions')
    bins = output/'bin'
    bins.mkdir()
    for agent in ('openclaw', 'hermes'):
        wrapper = bins/(agent+'-isolated')
        shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh', wrapper)
        wrapper.chmod(0o700)
    sources = {}
    for folder in ('kylin_memory_bench', 'scripts', 'configs'):
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and (path.suffix in ('.py', '.sh') or path.name.endswith('.example.json')):
                relative = path.relative_to(ROOT)
                destination = output/'source'/relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                sources[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    atomic_private(output/'protocol.json', {
        'protocol': 'luna-six-dimension-video-1', 'model': TARGET,
        'cases': [c['id'] for c in cases], 'dataset_sha256': digest(cases),
        'case_count': 6, 'agents': ['openclaw', 'hermes'], 'repeats': 1,
        'agent_turns': 2*sum(len(c['steps']) for c in cases), 'source_sha256': sources,
        'retry_policy': 'No evaluator case reruns; native SDK recovery is retained in request logs.',
        'scope': 'Operational demonstration on WSL Ubuntu; historical openKylin statistics remain separate.',
        'server_output_cap': None, 'cumulative_request_cap': None,
    })
    import requests
    local = threading.local()
    def transport(*positional, **kwargs):
        kwargs['timeout'] = (10, 120)
        if not hasattr(local, 'session'):
            local.session = requests.Session()
        return local.session.request(*positional, **kwargs)
    requests.request = transport
    started = time.time()
    def run(agent):
        bridge = Bridge(output/'requests'/agent, limit=None, deadline_seconds=3600)
        server = bridge.server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        key = 'KMB_VIDEO_KEY_'+agent.upper()
        os.environ[key] = bridge.key
        configs = full_configurations(bins, 'http://127.0.0.1:%d/v1'%server.server_port, args.embedding_url)
        config = next(c for c in configs if c['id'] == agent)
        config = json.loads(json.dumps(config).replace('KMB_PROXY_KEY', key))
        try:
            print('START '+agent, flush=True)
            execute(cases, {'schema_version': '1.0', 'agents': [config]}, output/agent,
                    repeats=1, jobs=1, progress=lambda aid, trial, cid: print('CASE '+aid+' '+cid, flush=True))
            result = verify_run(output/agent)
            print('END '+agent+' '+result['status'], flush=True)
            return result
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {agent: pool.submit(run, agent) for agent in ('openclaw', 'hermes')}
        results = {agent: future.result() for agent, future in futures.items()}
    atomic_private(output/'validation.json', {'elapsed_seconds': time.time()-started, 'results': results})
    print('DEMO FINISHED: original scores and all errors preserved', flush=True)


if __name__ == '__main__':
    main()
