#!/usr/bin/env python3
"""Native CLI/isolation/output-cap checks against a loopback stub. Provider access is impossible."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from kylin_memory_bench.adapters import External
from live_deepseek import Service,server_for


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Output exists; preserve previous validation')
    base=Path('/home/kmb/runs/kmb-research-v31-offline-'+uuid.uuid4().hex[:10])
    base.mkdir(parents=True)
    binary=base/'bin';binary.mkdir()
    shutil.copyfile(ROOT/'scripts/isolated_native_v31.sh',binary/'isolated_native.sh')
    (binary/'isolated_native.sh').chmod(0o755)
    for name in ('openclaw','hermes'):(binary/(name+'-isolated')).symlink_to('isolated_native.sh')
    workspace=base/'workspaces/probe/sessions/current';workspace.mkdir(parents=True)
    (workspace/'allowed.txt').write_text('workspace-only')
    forbidden=workspace.parent/'forbidden';forbidden.mkdir();(forbidden/'secret.txt').write_text('old-session-not-visible')
    (workspace.parents[1]/'scorer-secret.txt').write_text('not-visible')
    sentinel=Path('/tmp/kmb-v31-private-sentinel.txt');sentinel.write_text('not-visible')
    isolation=subprocess.run([str(binary/'openclaw-isolated'),'--isolation-probe'],cwd=workspace,check=True,text=True,capture_output=True)
    isolation=json.loads(isolation.stdout)
    env=base/'stub.env';env.write_text('STUB_KEY=offline-not-a-provider-key\n')
    requests=[]
    class OfflineService(Service):
        def remote(self,path,data=None):
            if path=='/user/balance':return {'balance_infos':[{'currency':'CNY','total_balance':'100'}]}
            if path!='/chat/completions':raise AssertionError('Unsupported local-stub operation')
            requests.append({'model':data['model'],'max_tokens':data['max_tokens'],
                             'thinking':data.get('thinking'),'temperature':data.get('temperature')})
            return {'id':'offline-native-check','created':0,'object':'chat.completion','model':'deepseek-flash',
                    'choices':[{'index':0,'message':{'role':'assistant','content':'{"offline_stub":"ok"}'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    service=OfflineService(SimpleNamespace(env_file=str(env),key_name='STUB_KEY',budget_cny=10,request_limit=30,
        max_output_tokens=4096,balance_check_interval=30,audit=str(base/'stub-audit.jsonl'),ledger=str(base/'stub-ledger.json')))
    server=server_for(service);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    os.environ['KMB_PROXY_KEY']=service.token
    config=json.loads((ROOT/'configs/deepseek-research-v31.example.json').read_text().replace(
        'KMB_PROXY_BASE_URL',f'http://127.0.0.1:{server.server_port}/v1'))
    turns=[]
    try:
        for agent in config['agents']:
            agent['executable']=str(binary/(agent['id']+'-isolated'))
            if agent['id']=='hermes':agent['dependency_home']='/home/maedaily/.local/share/kmb-live/hermes-home'
            own=base/'workspaces'/agent['id'];own.mkdir()
            adapter=External(agent,own)
            for cap in (1024,4096):
                before=len(requests)
                result=adapter.turn({'session_id':str(uuid.uuid4()),'day':0,'output_tokens':cap,
                                     'prompt':'离线启动与额度验证，只返回短JSON确认，不调用工具。'})
                if json.loads(result['text'])!={'offline_stub':'ok'}:raise ValueError('Native stub response decoding failed')
                if len(requests)==before or any(r['max_tokens']!=cap for r in requests[before:]):
                    raise ValueError('Native-to-proxy output cap was not applied')
                turns.append({'agent':agent['id'],'output_cap':cap,'decoded':True,
                              'new_session':True,'requests':len(requests)-before})
    finally:
        server.shutdown();server.server_close();sentinel.unlink(missing_ok=True)
    report={'paid_calls':0,'provider_network_calls':0,'backend':'loopback_stub_with_remote_method_override',
            'wrapper_sha256':hashlib.sha256((ROOT/'scripts/isolated_native_v31.sh').read_bytes()).hexdigest(),
            'isolation':isolation,'native_stub_turns':turns,'request_controls':requests,
            'native_health_status':'not_paid_tested',
            'scope':'Filesystem/PID isolation, native CLI startup/decoding and effective per-turn caps only; no real memory behaviour, retrieval-index health or difficulty claim.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
