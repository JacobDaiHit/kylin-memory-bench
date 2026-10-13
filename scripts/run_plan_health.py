"""Native ChatGPT-plan compatibility and memory health; NOT stress calibration.

Run with python -m scripts.run_plan_health --output PATH [--live]. Defaults to
capture-only (no inference). Live max 24 model requests, no retries by bridge.
"""
import argparse
import hashlib
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from scripts.chatgpt_plan_bridge import Bridge, append
from scripts.chatgpt_plan import atomic_private, TARGET
from kylin_memory_bench.adapters import External

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path('/home/maedaily/.local/share/kmb-live')


def configurations(bin_dir,base):
    text=(ROOT/'configs/deepseek-research-v31.example.json').read_text()
    text=text.replace('kmb-deepseek','kmb-plan').replace('deepseek-flash',TARGET).replace('DeepSeek Flash','Luna / ChatGPT plan')
    text=text.replace('REPLACE_ISOLATED_BIN',str(bin_dir)).replace('KMB_PROXY_BASE_URL',base)
    text=text.replace('/path/to/existing/hermes-home',str(RUNTIME/'hermes-home'))
    rows=json.loads(text)['agents']
    for row in rows:
        row['per_turn_proxy_limits']=False
        row['timeout']=180
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-limit',type=int,default=24,choices=range(1,25))
    parser.add_argument('--output',type=Path,required=True); parser.add_argument('--live',action='store_true')
    args=parser.parse_args(); output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    run=RUNTIME/'runs'/('kmb-plan-'+uuid.uuid4().hex[:12]); (run/'workspaces').mkdir(parents=True,mode=0o700)
    bins=run/'bin'; bins.mkdir()
    for kind in ('openclaw','hermes'):
        target=bins/(kind+'-isolated'); shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh',target); target.chmod(0o700)
    bridge=Bridge(output/'requests',capture=not args.live,limit=args.request_limit)
    server=bridge.server(); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    os.environ['KMB_PROXY_KEY']=bridge.key
    configs=configurations(bins,'http://127.0.0.1:%d/v1'%server.server_port)
    # Freeze exact prompts and expected outcome BEFORE the first native call.
    stages=[('learn', '请按你自己的持久记忆机制保存：项目 Cedar-Q7 的对外交付编号是 MEM-47291，测试环境版本为 11。以后会在新会话询问，请现在完成保存。',None),
            ('recall','请检索历史记忆：项目 Cedar-Q7 的对外交付编号和测试环境版本是什么？只回答 JSON {"code":字符串或null,"version":整数或null}。',{'code':'MEM-47291','version':11}),
            ('isolation','请检索历史记忆：项目 Cedar-Q7 的对外交付编号和测试环境版本是什么？无依据时返回 null；只回答 JSON {"code":字符串或null,"version":整数或null}。',{'code':None,'version':None})]
    protocol={'protocol':'luna-native-health-0.1','benchmark_score':False,'model':TARGET,'live':args.live,
              'max_upstream_requests':args.request_limit,'server_output_cap':None,'run_workspace':str(run),
              'configurations':configs,'stages':stages,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                 for p in ['scripts/chatgpt_plan.py','scripts/chatgpt_plan_bridge.py','scripts/run_plan_health.py','scripts/isolated_native_plan.sh','kylin_memory_bench/adapters.py']}}
    atomic_private(output/'protocol.json',protocol)
    results=[]
    try:
        for config in configs:
            work=run/'workspaces'/config['id']; work.mkdir()
            adapter=External(config,work)
            for stage,prompt,expected in (stages if args.live else stages[:1]):
                if stage=='isolation':
                    work=run/'workspaces'/(config['id']+'-isolated'); work.mkdir(); adapter=External(config,work)
                # New process AND logical session each turn; same workspace only
                # for learn->recall. No probe result is fed into the next prompt.
                request={'session_id':str(uuid.uuid4()),'day':0,'prompt':prompt}
                bridge.context=config['id']+'/'+stage
                entry={'agent':config['id'],'stage':stage,'request':request,'workspace':str(work),'expected':expected}
                append(output/'events.jsonl',dict(entry,status='started'))
                print(config['id']+'/'+stage+' started',flush=True)
                try:
                    response=adapter.turn(request)
                    entry.update(status='completed',response=response)
                    if expected is not None:
                        try: actual=json.loads(response['text']); entry['exact_content_match']=actual==expected
                        except (ValueError,TypeError): entry['exact_content_match']=False
                    print(config['id']+'/'+stage+' completed',flush=True)
                except Exception as exc:
                    entry.update(status='execution_error',error_type=type(exc).__name__,error=str(exc)[:1500])
                    print(config['id']+'/'+stage+' execution_error',flush=True)
                append(output/'events.jsonl',entry);results.append(entry)
                if entry['status']!='completed': break
    finally:
        server.shutdown(); server.server_close(); thread.join()
        atomic_private(output/'results.json',{'benchmark_score':False,'requests_received':bridge.count,'results':results})
    print(json.dumps({'output':str(output),'requests_received':bridge.count,'stages':[
        {k:r[k] for k in ('agent','stage','status','exact_content_match') if k in r} for r in results]},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
