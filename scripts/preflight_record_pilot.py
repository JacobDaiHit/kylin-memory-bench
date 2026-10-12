#!/usr/bin/env python3
"""Offline native startup and filesystem isolation checks; no provider calls."""
import contextlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench.adapters import External
from live_deepseek import sse


def main():
    base=Path('/home/kmb/runs/kmb-research-v3-preflight')
    if base.exists(): raise ValueError('Preflight directory exists; do not reuse state')
    base.mkdir(parents=True)
    binary=base/'bin';binary.mkdir()
    shutil.copyfile(ROOT/'scripts/isolated_native.sh',binary/'isolated_native.sh')
    (binary/'isolated_native.sh').chmod(0o700)
    for agent in ('openclaw','hermes'):(binary/(agent+'-isolated')).symlink_to('isolated_native.sh')
    probe=base/'workspaces'/'probe';probe.mkdir(parents=True)
    (probe/'allowed.txt').write_text('workspace-only')
    forbidden=probe.parent/'forbidden';forbidden.mkdir()
    (forbidden/'secret.txt').write_text('must-not-be-visible')
    (base/'scorer-secret.txt').write_text('must-not-be-visible')
    Path('/tmp/kmb-v3-private-sentinel.txt').write_text('must-not-be-visible')
    isolation=subprocess.run([str(binary/'openclaw-isolated'),'--isolation-probe'],cwd=probe,
                             text=True,capture_output=True,check=True)
    isolation=json.loads(isolation.stdout)
    requests=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,body,kind='application/json'):
            raw=body if isinstance(body,bytes) else json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(raw)));self.end_headers()
            with contextlib.suppress(BrokenPipeError):self.wfile.write(raw)
        def do_GET(self):
            self.send(200,{'object':'list','data':[{'id':'deepseek-flash','object':'model','owned_by':'offline-stub'}]})
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path':self.path,'model':body.get('model'),'stream':body.get('stream')})
            result={'id':'offline-check','created':0,'object':'chat.completion',
                    'model':'deepseek-flash','choices':[{'index':0,'message':{'role':'assistant','content':'{"offline_stub":"ok"}'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
            self.send(200,sse(result) if body.get('stream') else result,
                      'text/event-stream' if body.get('stream') else 'application/json')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    os.environ['KMB_PROXY_KEY']='offline-stub-public-token'
    config=json.loads((ROOT/'configs/deepseek-live.example.json').read_text().replace(
        'KMB_PROXY_BASE_URL',f'http://127.0.0.1:{server.server_port}/v1'))
    turns=[]
    try:
        for agent in config['agents']:
            agent['executable']=str(binary/(agent['id']+'-isolated'))
            if agent['id']=='hermes':agent['dependency_home']='/home/maedaily/.local/share/kmb-live/hermes-home'
            workspace=base/'workspaces'/agent['id'];workspace.mkdir()
            adapter=External(agent,workspace)
            for i in range(2):
                result=adapter.turn({'session_id':str(uuid.uuid4()),'day':i,
                                     'prompt':'只回答一个短JSON确认，不调用工具。此为本地离线启动检查。'})
                if json.loads(result['text']) != {'offline_stub':'ok'}:
                    raise ValueError('Native response differs from the local stub')
                turns.append({'agent':agent['id'],'separate_session':i,'decoded':True,
                              'provenance':result.get('provenance')})
    finally:
        server.shutdown();server.server_close()
    report={'paid_calls':0,'provider_network_calls':0,'isolation':isolation,'native_stub_turns':turns,
            'local_stub_requests':requests,
            'scope':'Filesystem/PID visibility and native startup/response decoding only; stub does not test memory capacity.'}
    target=ROOT/'docs/evidence/research-v3-native-preflight.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
