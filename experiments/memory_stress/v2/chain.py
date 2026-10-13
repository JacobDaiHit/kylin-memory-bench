"""Separate closed-loop software controller; all attempts remain in the evidence."""
import copy
import json
import os
import sys
import uuid
from pathlib import Path

from kylin_memory_bench.adapters import BASE_ENV, process, validate_response
from kylin_memory_bench.common import BenchError, canonical, digest, strict_json, write_json, write_text
from experiments.memory_stress.world_generator import opaque
from experiments.memory_stress.oracle import field_decision
from .environment import COMPONENTS, artifact_spec, check_component, grade_delivery, inspect_delivery, tool_feedback
from .oracle import normalized, resolve
from .render_history import render_event, render_query
from .world_generator import phase_two_worlds


def feedback_records(subject, required, submitted, stage, attempt):
    rows = []
    for key,value in required.items():
        checked = check_component({key:value},submitted.get(key))
        rows.append({'id':'E-'+opaque(stage,attempt,key),'kind':'feedback','subject':subject,'scope':'experience',
                     'status':'accepted','label':'v'+str(attempt),'fields':{key:value},
                     'interaction':{k:v for k,v in checked.items() if k != 'required'}})
    return rows


class SubprocessReference:
    def turn(self,request):
        env = {k:os.environ[k] for k in BASE_ENV if k in os.environ}
        argv = [sys.executable,'-X','utf8',str(Path(__file__).parent/'reference_adapter.py')]
        return validate_response(strict_json(process(argv,Path(request['workspace']),env,canonical(request),30)))


def run_chain(world,output,state_policy='persistent',adapter=None):
    """Learning allows two declared attempts; transfer allows exactly one. No retry erasure."""
    if world['family'] != 'feedback' or state_policy not in ('persistent','fresh_each_session'): raise ValueError('Invalid chain selection')
    output = Path(output).resolve()
    if output.exists(): raise BenchError('Refuse to overwrite task-chain evidence')
    output.mkdir(parents=True); agent = adapter or SubprocessReference()
    initial = copy.deepcopy(next(q for q in world['queries'] if q['role'] == 'primary'))
    official = normalized(world['events'])
    required = {k:field_decision(official,initial['subject'],'experience',k)[0] for k in COMPONENTS}
    initial.update(project='LEARN-'+opaque(world['scenario_id']),required_fields=list(COMPONENTS),provided={})
    other = next(q['subject'] for q in world['queries'] if q['role'] == 'other_scope')
    other_rules = {k:field_decision(official,other,'experience',k)[0] for k in COMPONENTS}
    other_options = [{'id':'OTHER-'+opaque(world['scenario_id'],i),'values':dict(other_rules,**({key:value+'-alternative'} if key is not None else {}))}
                     for i,(key,value) in enumerate([(None,'')]+list(other_rules.items()))]
    interference = dict(initial,subject=other,project='OTHERPROJECT-'+opaque(world['scenario_id']),
                        required_fields=[],provided=other_rules,options=other_options,
                        choices={k:[v,v+'-alternative'] for k,v in other_rules.items()})
    transfer = copy.deepcopy(next(q for q in world['queries'] if q['role'] == 'primary'))
    transfer['project'] = 'TRANSFER-'+opaque(world['scenario_id'])
    stages = [('learning',initial,required,2),('interference',interference,other_rules,1),('transfer',transfer,required,1)]
    records,events,results = [],[],[]; previous = None; fatal = None; run_id = str(uuid.uuid4()); counter = 0
    workspace = output/'agent'; workspace.mkdir()
    for stage,query,rules,limit in stages:
        accepted = False; first = None; attempts = []
        for attempt in range(limit):
            if accepted: break
            if fatal:
                attempts.append({'attempt':attempt,'status':'unknown','reason':'Earlier execution error; stage skipped.'})
                break
            counter += 1
            active = workspace
            if state_policy == 'fresh_each_session': active = workspace/('session-'+str(counter)); active.mkdir()
            prompt = render_query(query)
            if stage == 'learning' and attempt == 0: prompt = 'TRAINING_ATTEMPT\n首次探索可先试交付一个候选方案，再根据实际验收反馈修正。\n'+prompt
            if records: prompt += '\n本次实际工具反馈：\n'+'\n'.join(render_event(r) for r in records)
            request = {'protocol_version':'1.0','session_id':str(uuid.uuid5(uuid.UUID(run_id),str(counter))),
                       'day':counter,'workspace':str(active),'prompt':prompt,'output_tokens':4096}
            response,error = None,None
            try: response = validate_response(agent.turn(request))
            except (ValueError,OSError) as exc: error = str(exc); fatal = error
            spec = artifact_spec(query,{'values':rules}); artifact = inspect_delivery(active,spec)
            feedback = tool_feedback(rules,query,artifact)
            declared = None
            if response:
                try: declared = strict_json(response['text']).get('answer')
                except (ValueError,AttributeError): pass
            chosen = next((o for o in query['options'] if o['id'] == declared),None)
            content_ok = chosen is not None and chosen['values'] == rules
            accepted = bool(not error and content_ok and feedback['verdict']['file_success'])
            if first is None: first = accepted
            entry = {'schema_version':'chain-0.1','event_id':str(counter),'run_id':run_id,'stage':stage,'attempt':attempt,
                     'request':request,'response':response,'error':error,'artifact':artifact,'tool_feedback':feedback,
                     'content_correct':content_ok,'task_success':accepted,'previous_hash':previous}
            entry['hash'] = digest(entry); previous = entry['hash']; events.append(entry)
            attempts.append({'attempt':attempt,'status':'error' if error else 'pass' if accepted else 'fail','event_id':entry['event_id']})
            # All six rules come from the actual deterministic tool, never a corrected silent replay.
            records = feedback_records(query['subject'],rules,chosen['values'] if chosen else {},stage,attempt)
            if accepted:
                # Deliver the actual feedback in a separate session before the next task.
                counter += 1; ack_workspace = workspace
                if state_policy == 'fresh_each_session': ack_workspace = workspace/('session-'+str(counter)); ack_workspace.mkdir()
                ack = {'protocol_version':'1.0','session_id':str(uuid.uuid5(uuid.UUID(run_id),str(counter))), 'day':counter,
                       'workspace':str(ack_workspace),'prompt':'本次实际工具反馈：\n'+'\n'.join(render_event(r) for r in records),'output_tokens':1024}
                try: acknowledged = validate_response(agent.turn(ack)); ack_error = None
                except (ValueError,OSError) as exc: acknowledged = None; ack_error = str(exc); fatal = ack_error
                acknowledgement = {'schema_version':'chain-0.1','event_id':str(counter),'run_id':run_id,'stage':stage,'kind':'feedback_delivery',
                                   'request':ack,'response':acknowledged,'error':ack_error,'previous_hash':previous}
                acknowledgement['hash'] = digest(acknowledgement); previous = acknowledgement['hash']; events.append(acknowledgement)
                records = []
        results.append({'stage':stage,'attempt_limit':limit,'attempts':attempts,'first_attempt_success':bool(first), 'stage_success':accepted and not fatal})
    write_text(output/'evidence.jsonl',''.join(canonical(e)+'\n' for e in events))
    result = {'kind':'complete_task_chain_software_check','run_id':run_id,'state_policy':state_policy,'scenario_id':world['scenario_id'],
              'stages':results,'planned_stages':3,'chain_success':all(r['stage_success'] for r in results),
              'transfer_first_attempt_success':results[-1]['first_attempt_success'],'event_count':len(events),'evidence_head':previous,
              'policy_sha256':digest({'target':required,'other':other_rules}),'paid_calls':0 if adapter is None else None,
              'claim_limit':'Separate scripted controller/software run; not part of controlled-transfer scores, not a native/model baseline.'}
    write_json(output/'results.json',result); return result


def verify_chain(directory):
    from kylin_memory_bench.common import read_json
    directory = Path(directory); result = read_json(directory/'results.json'); previous = None; events = []
    for i,line in enumerate((directory/'evidence.jsonl').read_text(encoding='utf-8').splitlines(),1):
        event = strict_json(line); payload = {k:v for k,v in event.items() if k != 'hash'}
        if event['event_id'] != str(i) or event['previous_hash'] != previous or digest(payload) != event['hash']: raise BenchError('Task-chain evidence hash mismatch')
        previous = event['hash']; events.append(event)
    if len(events) != result['event_count'] or previous != result['evidence_head']: raise BenchError('Task-chain manifest mismatch')
    from .reference_adapter import parse_question
    reconstructed = []; fatal = False
    for stage,limit in (('learning',2),('interference',1),('transfer',1)):
        selected = [e for e in events if e['stage'] == stage]
        attempts = []; accepted = False; first = None
        for e in selected:
            if e.get('kind') == 'feedback_delivery':
                fatal = fatal or bool(e['error']); continue
            if e['attempt'] != len(attempts) or len(attempts) >= limit: raise BenchError('Invalid task-chain attempt schedule')
            query = parse_question(e['request']['prompt']); required = e['tool_feedback']['required']
            spec = artifact_spec(query,{'values':required})
            recomputed = tool_feedback(required,query,e['artifact'])
            if recomputed != e['tool_feedback']: raise BenchError('Task-chain validation feedback differs from replay')
            declared = None
            if e['response']:
                try: declared = strict_json(e['response']['text']).get('answer')
                except (ValueError,AttributeError): pass
            chosen = next((o for o in query['options'] if o['id'] == declared),None)
            content = chosen is not None and chosen['values'] == required
            accepted = bool(not e['error'] and content and grade_delivery(e['artifact'],spec)['file_success'])
            if e['content_correct'] != content or e['task_success'] != accepted: raise BenchError('Task-chain score differs from replay')
            if first is None: first = accepted
            attempts.append({'attempt':e['attempt'],'status':'error' if e['error'] else 'pass' if accepted else 'fail','event_id':e['event_id']})
            fatal = fatal or bool(e['error'])
        if not accepted and len(attempts) < limit:
            if not fatal: raise BenchError('Task-chain evidence is incomplete')
            attempts.append({'attempt':len(attempts),'status':'unknown','reason':'Earlier execution error; stage skipped.'})
        reconstructed.append({'stage':stage,'attempt_limit':limit,'attempts':attempts,'first_attempt_success':bool(first),'stage_success':accepted and not fatal})
    if result['stages'] != reconstructed or result['chain_success'] != all(s['stage_success'] for s in reconstructed) or result['transfer_first_attempt_success'] != reconstructed[-1]['first_attempt_success']:
        raise BenchError('Task-chain summary differs from independent replay')
    return {'valid':True,'events':len(events),'scope':'Recorded hash chain, tool validation and score replay; not a signature or native isolation proof.'}


def smoke(output):
    output = Path(output)
    if output.exists(): raise BenchError('Refuse to overwrite chain smoke')
    world = next(w for w in phase_two_worlds() if w['family'] == 'feedback' and w['tier'] == 'extreme' and w['split'] == 'development')
    a = run_chain(world,output/'persistent'); b = run_chain(world,output/'stateless','fresh_each_session')
    verify_chain(output/'persistent'); verify_chain(output/'stateless')
    if not a['chain_success'] or not a['transfer_first_attempt_success'] or b['transfer_first_attempt_success']:
        raise BenchError('Unexpected chain workspace control behavior')
    value = {'passed':True,'paid_calls':0,'kind':'separate_complete_chain_software_smoke','persistent':a,'stateless':b}
    write_json(output/'smoke.json',value); return value
