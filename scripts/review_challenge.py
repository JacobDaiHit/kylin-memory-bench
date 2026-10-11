#!/usr/bin/env python3
"""Recompute a disclosed annotation correction without changing raw experimental evidence."""
import argparse,copy,json,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kylin_memory_bench.common import digest,read_json,write_json,write_text
from kylin_memory_bench.generate import save_dataset
from kylin_memory_bench.runner import read_run,verify_run
from kylin_memory_bench.scoring import score_run
from kylin_memory_bench.report import render_report

NOTICE='此页为答案标注订正版：松柏与松柏项目作为显式等价答案。只修正一个检查，六次误判改为通过；全部原始提示、回答、文件、执行错误和其他检查保持原样。订正是在实测后发现问题并统一应用，不是新的模型实验。'

def calculate(root):
    verify_run(root)
    manifest,cases,events,original=read_run(root)
    if manifest['run_id']!='23b54cdd-32a1-430b-b749-e0e8adadfff4':
        raise ValueError('This published erratum applies to the pinned challenge run only.')
    corrected=copy.deepcopy(cases)
    case=next(c for c in corrected if c['id']=='challenge-episodic-join')
    rule=next(s for s in case['steps'] if s['id']=='join')['checks'][0]
    if rule['op']!='equals' or rule['value']!='松柏':raise ValueError('Unexpected original annotation')
    rule.update(op='one_of',value=['松柏','松柏项目'])
    scores=score_run(manifest,corrected,events)
    scores['run_status']='annotation_review'
    changes=[]
    for before,after in zip(original['agents'],scores['agents']):
        for old_case,new_case in zip(before['cases'],after['cases']):
            for old,new in zip(old_case['checks'],new_case['checks']):
                if old['status']!=new['status']:
                    if old_case['case_id']!='challenge-episodic-join' or old['check_id']!='join' or (old['status'],new['status'])!=('fail','pass'):
                        raise ValueError('Unexpected score change outside declared annotation correction')
                    changes.append({'agent_id':before['id'],'trial':old_case['trial'],'event_id':old['evidence_id'],'from':old['status'],'to':new['status']})
    if len(changes)!=6:raise ValueError('Expected exactly six equivalent-answer false negatives')
    review={'schema_version':'1.0','kind':'post_experiment_annotation_correction','source_run_id':manifest['run_id'],
            'original_dataset_sha256':digest(cases),'reviewed_dataset_sha256':digest(corrected),
            'evidence_chain_head':events[-1]['hash'],
            'reason':NOTICE,'changed_rule':{'case_id':'challenge-episodic-join','step_id':'join','op':'one_of','value':['松柏','松柏项目']},
            'changed_checks':changes,'agents':[{'id':a['id'],'original':o['overall'],'reviewed':a['overall']} for o,a in zip(original['agents'],scores['agents'])]}
    return manifest,corrected,scores,review

def banner(link,label,text):
    return '<aside id="annotation-review" style="padding:20px 32px;background:#fff2ce;color:#473816;font:15px/1.8 sans-serif">'+text+' <a href="'+link+'">'+label+'</a></aside>'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,default=ROOT/'examples/openkylin-challenge');p.add_argument('--check',action='store_true');args=p.parse_args()
    manifest,cases,scores,review=calculate(args.run)
    if args.check:
        if read_json(args.run/'reviewed-scores.json')!=scores or read_json(args.run/'score-review.json')!=review:
            raise SystemExit('Annotation review does not match independent recomputation')
        from kylin_memory_bench.dataset import load_dataset
        if load_dataset(args.run/'reviewed-dataset.jsonl')!=cases:raise SystemExit('Reviewed dataset mismatch')
        print('ANNOTATION REVIEW PASS: six explicit alias corrections, original run intact.');return
    save_dataset(args.run/'reviewed-dataset.jsonl',cases);write_json(args.run/'reviewed-scores.json',scores);write_json(args.run/'score-review.json',review)
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);shutil.copyfile(args.run/'evidence.jsonl',out/'evidence.jsonl');write_json(out/'manifest.json',manifest);save_dataset(out/'dataset.jsonl',cases)
        render_report(scores,out)
        for name in ('report.html','radar.svg','metrics.csv','evidence.html'):
            data=(out/name).read_text(encoding='utf-8')
            if name.endswith('.html'):
                for raw,new in [('report.html','reviewed-report.html'),('evidence.html','reviewed-evidence.html'),('scores.json','reviewed-scores.json'),('metrics.csv','reviewed-metrics.csv'),('radar.svg','reviewed-radar.svg')]:
                    data=data.replace('href="'+raw,'href="'+new)
                data=data.replace('<body>','<body>'+banner('report.html','查看原始未订正报告',NOTICE),1)
            write_text(args.run/('reviewed-'+name),data)
    # Presentation-only notice; do not mutate any raw dataset, manifest, evidence or scores.
    render_report(read_json(args.run/'scores.json'),args.run)
    for name in ('report.html','evidence.html'):
        path=args.run/name
        text=path.read_text(encoding='utf-8').replace('<body>','<body>'+banner('reviewed-report.html','打开答案标注订正版','原始报告含六次等价答案误判（松柏项目与松柏），保留用于完整审计；请结合订正版解读。'),1)
        write_text(path,text)
    print(json.dumps(review,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
