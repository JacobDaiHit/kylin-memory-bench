"""Ubuntu-side local Luna bridges for a genuine openKylin recording run.

Keep this process alive. OAuth stays here; only ephemeral loopback credentials
are written into the private control file. No benchmark memory is added.
"""
import argparse
import json
import os
from pathlib import Path
import threading
import time

from scripts.chatgpt_plan import atomic_private, TARGET
from scripts.chatgpt_plan_bridge import Bridge
from scripts.plan_native_config import full_configurations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=False, mode=0o700)
    import requests
    local = threading.local()
    def transport(*positional, **kwargs):
        kwargs['timeout'] = (10, 120)
        if not hasattr(local, 'session'):
            local.session = requests.Session()
        return local.session.request(*positional, **kwargs)
    requests.request = transport
    servers, configs, environment = [], [], {}
    for agent in ('openclaw', 'hermes'):
        bridge = Bridge(state/'requests'/agent, limit=None, deadline_seconds=7200)
        bridge.context = 'openkylin-video/'+agent
        server = bridge.server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        key = 'KMB_KYLIN_VIDEO_KEY_'+agent.upper()
        rows = full_configurations('/home/kmb/.cache/kmb-video/bin',
            'http://127.0.0.1:%d/v1'%server.server_port, 'http://127.0.0.1:18789/v1')
        config = next(row for row in rows if row['id'] == agent)
        configs.append(json.loads(json.dumps(config).replace('KMB_PROXY_KEY', key)))
        environment[key] = bridge.key
        servers.append((bridge, server, thread))
    atomic_private(state/'control.local.json', {'model': TARGET, 'agents': configs, 'environment': environment})
    print('BRIDGES READY: '+str(state/'control.local.json'), flush=True)
    print('OAuth remains in Ubuntu. Start run_openkylin_video from the openKylin desktop.', flush=True)
    try:
        while True:
            time.sleep(5)
    finally:
        for bridge, server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join()
        atomic_private(state/'service-summary.json', {'model': TARGET,
            'requests': {bridge.context: bridge.count for bridge, _, _ in servers}})


if __name__ == '__main__':
    main()
