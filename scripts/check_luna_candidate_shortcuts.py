"""Prompt-level no-history diagnostic, separate from native agent scores."""
import copy,json,threading,time
from pathlib import Path
import requests
from scripts.chatgpt_plan_bridge import Bridge
from scripts.chatgpt_plan import atomic_private,TARGET
from experiments.memory_stress.v2.calibrate_stress import grade
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('/home/maedaily/.local/share/kmb-live/runs/kmb-plan-submission-candidates16-20261013')
OUTPUT=Path('/home/maedaily/.local/share/kmb-live/runs/kmb-plan-candidate-shortcuts-20261013')
def main():
 OUTPUT.mkdir(mode=0o700,exist_ok=False)
 cases=json.loads((SOURCE/'cases.json').read_text());catalog=json.loads((SOURCE/'catalog.json').read_text())
 rows=[(c,catalog[c['id']]) for c in cases.values() if c['id'].startswith('reader-')]
 atomic_private(OUTPUT/'protocol.json',{'scope':'Fixed Luna reader without native agent prompts/tools or historical evidence. Diagnostic only, not an agent memory score.','planned':len(rows),'model':TARGET,'retry':False,'selection':'All eight preselected candidate16 pilot worlds.'})
 session=requests.Session();original=requests.request
 def pooled(*args,**kwargs):kwargs['timeout']=(10,120);return session.request(*args,**kwargs)
 requests.request=pooled
 try:session.get('https://api.openai.com/v1/models',timeout=(10,15)).close()
 except requests.RequestException:pass
 bridge=Bridge(OUTPUT/'requests',limit=None,deadline_seconds=1200);results=[]
 for case,meta in rows:
  prompt=case['steps'][-1]['prompt'].split('\n以下是按原顺序排列的原始会话材料：')[0]
  if meta['family'] in ('collections','feedback'):prompt+='\n本题answer必须返回options中唯一匹配方案的id；provided是当前有效约束，required_fields从历史恢复。不要返回目录或文件名。transfer任务还须生成对应文件。'
  row={'scenario_id':meta['scenario_id'],'family':meta['family'],'tier':meta['tier']};bridge.context=case['id'];bridge.replay.clear()
  try:
   response=bridge.invoke({'model':TARGET,'messages':[{'role':'user','content':prompt}]});text=response['choices'][0]['message']['content']
   row.update(memory_gold_grade=grade(meta['expected'],text,output_type=meta['answer_type']),abstention_grade=grade(None,text,output_type=meta['answer_type']))
  except Exception as e:row.update(error_type=type(e).__name__)
  results.append(row);atomic_private(OUTPUT/'results.json',{'planned':8,'rows':results});print(meta['family'],meta['tier'],row.get('memory_gold_grade',{}).get('status',row.get('error_type')),flush=True)
 summary={'scope':'Prompt-level no-history diagnostic; different from native agent controls.','planned':8,'observed':sum('memory_gold_grade' in r for r in results),'gold_guesses':sum(r.get('memory_gold_grade',{}).get('content_task_success',False) for r in results),'correct_abstentions':sum(r.get('abstention_grade',{}).get('content_task_success',False) for r in results),'rows':results}
 atomic_private(OUTPUT/'summary.json',summary)
 atomic_private(ROOT/'docs/evidence/luna-candidate-shortcuts.json',summary)
 requests.request=original
if __name__=='__main__':main()
