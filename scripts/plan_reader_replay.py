"""Independent one-turn reader replay; the core memory schema still needs 2 sessions.

The exact case must come from the pre-call frozen reader catalog. This verifier
checks the recorded data, config, session, artifacts, evidence chain and scoring,
without changing or rerunning the model response.
"""
import hashlib
import uuid
from pathlib import Path
from kylin_memory_bench.common import BenchError,canonical,digest,read_json,strict_json
from kylin_memory_bench.adapters import validate_response
from kylin_memory_bench.scoring import score_run


def read_reader(directory,expected_case):
    directory=Path(directory)
    def require(value,message):
        if not value: raise BenchError('Reader replay: '+message)
    require(expected_case['id'].startswith('reader-') and len(expected_case['steps'])==1,'not a frozen one-turn reader')
    manifest=read_json(directory/'manifest.json');config=read_json(directory/'config.json')
    cases=[strict_json(line) for line in (directory/'dataset.jsonl').read_text().splitlines() if line.strip()]
    require(cases==[expected_case],'case differs from pre-call frozen input')
    require(manifest['schema_version']=='1.0' and manifest['dataset_sha256']==digest(cases),'dataset fingerprint')
    require(manifest['config_sha256']==digest(config) and manifest['agents']==config['agents'],'configuration fingerprint')
    require(manifest['repeats']==1 and len(manifest['agents'])==1,'reader schedule changed')
    events=[strict_json(line) for line in (directory/'evidence.jsonl').read_text().splitlines() if line.strip()]
    require(len(events)==1 and manifest['event_count']==1,'reader event count')
    event=events[0];step=expected_case['steps'][0];agent=manifest['agents'][0]['id']
    require(event['event_id']=='1' and event['previous_hash'] is None,'initial chain link')
    require(event['hash']==digest({k:v for k,v in event.items() if k!='hash'})==manifest['evidence_head'],'evidence chain')
    require(event['case_id']==expected_case['id'] and event['agent_id']==agent and event['trial']==0,'event identity')
    require(event['step_id']==step['id'] and all(event[k]==step[k] for k in ('kind','day','prompt')),'prompt or step changed')
    session=str(uuid.uuid5(uuid.UUID(manifest['run_id']),f"{agent}/0/{expected_case['id']}/{step['session']}"))
    require(event['session_id']==session,'session isolation identity')
    require(event.get('state_control',{}).get('policy')=='fresh_each_session','reader workspace policy')
    if event['response'] is not None:validate_response(event['response'])
    for artifact in event['artifacts'].values():
        if 'text' in artifact:
            raw=artifact['text'].encode('utf-8')
            require(artifact['sha256']==hashlib.sha256(raw).hexdigest() and artifact['bytes']==len(raw),'artifact fingerprint')
    errors=int(bool(event['error']));require(manifest['execution_errors']==errors,'error count')
    require(manifest['status']==('completed_with_errors' if errors else 'completed'),'completion status')
    recomputed=score_run(manifest,cases,events)
    require(canonical(recomputed)==canonical(read_json(directory/'scores.json')),'score differs from independent replay')
    return manifest,cases,events,recomputed


def verify_reader(directory,expected_case):
    manifest,cases,events,score=read_reader(directory,expected_case)
    return {'valid':True,'events':len(events),'cases':1,'run_id':manifest['run_id'],
            'status':manifest['status'],'protocol':'luna-native-reader-only-1',
            'note':'One-turn reader control, not a core multi-session memory dataset.'}
