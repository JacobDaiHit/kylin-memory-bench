import json,os,shutil,uuid
from pathlib import Path
from scripts.run_plan_health import RUNTIME,ROOT
from scripts.plan_native_config import full_configurations
from kylin_memory_bench.adapters import External,process
run=RUNTIME/'runs'/('kmb-plan-vector-preflight-'+uuid.uuid4().hex[:8]);work=run/'workspaces/openclaw';work.mkdir(parents=True)
bins=run/'bin';bins.mkdir();wrapper=bins/'openclaw-isolated';shutil.copyfile(ROOT/'scripts/isolated_native_plan.sh',wrapper);wrapper.chmod(0o700)
ready=json.loads((ROOT/'tmp/local-embedding-ready.json').read_text());os.environ['KMB_PROXY_KEY']='preflight-local-placeholder'
config=full_configurations(bins,'http://127.0.0.1:1/v1',ready['base_url'])[0];adapter=External(config,work)
(work/'MEMORY.md').write_text('星桥项目客户支持联系人是周岚，服务电话分机是 317。\n',encoding='utf-8')
records=[]
for args in [['memory','index','--force','--agent','main'],['memory','status','--deep','--agent','main','--json'],['memory','search','--query','星桥项目的售后联络人是谁','--agent','main','--json']]:
 print('Running',args,flush=True)
 try:
  result=process([str(wrapper)]+args,work,adapter.env,None,180);print(result[:6500],flush=True);records.append({'args':args,'output':result})
 except Exception as e:
  print(type(e).__name__,str(e));records.append({'args':args,'error':str(e)});break
(ROOT/'tmp/local-memory-preflight.json').write_text(json.dumps({'workspace':str(work),'config':config,'results':records},ensure_ascii=False,indent=2))
