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
from .render_history import parse_records, render_event, render_query
from .world_generator import phase_two_worlds

CHAIN_REVISION = 'actual-feedback-durable-events-1'
STAGE_LIMITS = (('learning',2),('interference',1),('transfer',1))

def feedback_records(subject, required, selected_values, stage, attempt):
    rows = []
    for key in COMPONENTS:
        if key not in required: continue
        value = required[key]
        checked = check_component({key:value},selected_values.get(key))
        rows.append({'id':'E-'+opaque(stage,attempt,key),'kind':'feedback','subject':subject,'scope':'experience',
                     'status':'accepted','label':'v'+str(attempt),'fields':{key:value},
                     'interaction':{k:v for k,v in checked.items() if k != 'required'}})
    return rows


def feedback_payload(query, rules, selected_values, artifact, feedback, stage, attempt):
    """Selection checks and observed file acceptance are two distinct observations."""
    delivery = copy.deepcopy(feedback)
    verdict = delivery['verdict']
    reason = verdict.get('reason')
    if not reason and not verdict['file_success']:
        reason = ('unobservable_file' if verdict['status'] == 'unknown' else
                  'content_and_format_mismatch' if verdict['content_correct'] is False and verdict['format_correct'] is False else
                  'content_mismatch' if verdict['content_correct'] is False else 'format_mismatch')
    delivery['reason'] = reason
    return {'component_checks':feedback_records(query['subject'],rules,selected_values or {},stage,attempt),
            'selected_values':copy.deepcopy(selected_values),'submitted_artifact':copy.deepcopy(artifact),
            'expected_artifact_path':artifact_spec(query,{'values':rules})['path'],'delivery_verdict':delivery}


def public_delivery(payload):
    return {k:payload[k] for k in ('selected_values','submitted_artifact','expected_artifact_path','delivery_verdict')}


def render_feedback(payload):
    return ('以下组件检查针对回答中选择的参数；实际文件交付结果在 DELIVERY_FEEDBACK 中单独给出。\n'+
            '\n'.join(render_event(r) for r in payload['component_checks'])+
            '\nDELIVERY_FEEDBACK='+canonical(public_delivery(payload)))


def forwarded_delivery(prompt):
    rows = [line for line in prompt.splitlines() if line.startswith('DELIVERY_FEEDBACK=')]
    if len(rows) > 1: raise BenchError('Multiple delivery feedback payloads')
    return strict_json(rows[0].split('=',1)[1]) if rows else None


def stage_summaries(events, incomplete=False, interrupted=False):
    """Summarize recorded attempts without filling missing slots with a rerun."""
    result = []; fatal = False
    for stage,limit in STAGE_LIMITS:
        attempts = []; accepted = False; first = None; acknowledged = False
        for event in (e for e in events if e['stage'] == stage):
            if event.get('kind') == 'feedback_delivery':
                if not accepted or acknowledged: raise BenchError('Unexpected feedback delivery')
                acknowledged = not bool(event['error']); fatal = fatal or bool(event['error'])
                continue
            if fatal or accepted or event['attempt'] != len(attempts) or len(attempts) >= limit:
                raise BenchError('Invalid task-chain attempt schedule')
            accepted = bool(event['task_success'])
            if first is None: first = accepted
            attempts.append({'attempt':event['attempt'],'status':'error' if event['error'] else 'pass' if accepted else 'fail',
                             'event_id':event['event_id']})
            fatal = fatal or bool(event['error'])
        if not accepted and len(attempts) < limit:
            if not incomplete and not fatal: raise BenchError('Task-chain evidence is incomplete')
            reason = 'Earlier execution error; stage skipped.' if fatal else 'Chain interrupted; result not recorded.' if interrupted else 'Not executed or result not recorded.'
            attempts.append({'attempt':len(attempts),'status':'unknown','reason':reason})
        if accepted and not acknowledged and not incomplete and not fatal:
            raise BenchError('Task-chain feedback delivery is incomplete')
        result.append({'stage':stage,'attempt_limit':limit,'attempts':attempts,'first_attempt_success':bool(first),
                       'stage_success':accepted and acknowledged and not fatal})
    return result


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
    pending,events = None,[]; previous = None; fatal = None; run_id = str(uuid.uuid4()); counter = 0
    status = 'running'; in_flight = None; exception_type = None; result = None
    workspace = output/'agent'; workspace.mkdir()
    journal = (output/'evidence.jsonl').open('x',encoding='utf-8',newline='\n')

    def checkpoint():
        summaries = stage_summaries(events,incomplete=status != 'completed',interrupted=status == 'interrupted')
        value = {'kind':'complete_task_chain_software_check','implementation_revision':CHAIN_REVISION,'status':status,
                 'run_id':run_id,'state_policy':state_policy,'scenario_id':world['scenario_id'],
                 'stages':summaries,'planned_stages':3,'chain_success':status == 'completed' and all(r['stage_success'] for r in summaries),
                 'transfer_first_attempt_success':summaries[-1]['first_attempt_success'],'event_count':len(events),'evidence_head':previous,
                 'in_flight':copy.deepcopy(in_flight),'exception_type':exception_type,
                 'policy_sha256':digest({'target':required,'other':other_rules}),'paid_calls':0 if adapter is None else None,
                 'claim_limit':'Separate scripted controller/software run; not part of controlled-transfer scores, not a native/model baseline.'}
        write_json(output/'results.json',value)
        return value

    def append_event(entry):
        nonlocal previous
        entry['previous_hash'] = previous; entry['hash'] = digest(entry)
        journal.write(canonical(entry)+'\n'); journal.flush(); os.fsync(journal.fileno())
        previous = entry['hash']; events.append(entry)

    try:
        journal.flush(); os.fsync(journal.fileno()); checkpoint()
        for stage,query,rules,limit in stages:
            accepted = False
            for attempt in range(limit):
                if accepted or fatal: break
                counter += 1
                active = workspace
                if state_policy == 'fresh_each_session': active = workspace/('session-'+str(counter)); active.mkdir()
                prompt = render_query(query)
                if stage == 'learning' and attempt == 0: prompt = 'TRAINING_ATTEMPT\n首次探索可先试交付一个候选方案，再根据实际验收反馈修正。\n'+prompt
                if pending: prompt += '\n本次实际工具反馈：\n'+render_feedback(pending)
                request = {'protocol_version':'1.0','session_id':str(uuid.uuid5(uuid.UUID(run_id),str(counter))),
                           'day':counter,'workspace':str(active),'prompt':prompt,'output_tokens':4096}
                in_flight = {'stage':stage,'attempt':attempt,'kind':'task','request':request}; checkpoint()
                response,error = None,None
                try: response = validate_response(agent.turn(request))
                except (ValueError,OSError) as exc: error = str(exc); fatal = error
                spec = artifact_spec(query,{'values':rules}); artifact = inspect_delivery(active,spec)
                feedback = tool_feedback(rules,query,artifact); declared = None
                if response:
                    try: declared = strict_json(response['text']).get('answer')
                    except (ValueError,AttributeError): pass
                chosen = next((o for o in query['options'] if o['id'] == declared),None)
                selected = chosen['values'] if chosen else None
                content_ok = selected is not None and selected == rules
                accepted = bool(not error and content_ok and feedback['verdict']['file_success'])
                pending = feedback_payload(query,rules,selected,artifact,feedback,stage,attempt)
                append_event({'schema_version':'chain-0.1','event_id':str(counter),'run_id':run_id,'stage':stage,'attempt':attempt,
                    'request':request,'response':response,'error':error,'artifact':artifact,'tool_feedback':feedback,
                    'feedback_payload':pending,'content_correct':content_ok,'task_success':accepted})
                in_flight = None; checkpoint()
                if accepted:
                    counter += 1; ack_workspace = workspace
                    if state_policy == 'fresh_each_session': ack_workspace = workspace/('session-'+str(counter)); ack_workspace.mkdir()
                    ack = {'protocol_version':'1.0','session_id':str(uuid.uuid5(uuid.UUID(run_id),str(counter))), 'day':counter,
                           'workspace':str(ack_workspace),'prompt':'本次实际工具反馈：\n'+render_feedback(pending),'output_tokens':1024}
                    in_flight = {'stage':stage,'kind':'feedback_delivery','request':ack}; checkpoint()
                    try: acknowledged = validate_response(agent.turn(ack)); ack_error = None
                    except (ValueError,OSError) as exc: acknowledged = None; ack_error = str(exc); fatal = ack_error
                    append_event({'schema_version':'chain-0.1','event_id':str(counter),'run_id':run_id,'stage':stage,'kind':'feedback_delivery',
                                  'request':ack,'response':acknowledged,'error':ack_error})
                    pending = None; in_flight = None; checkpoint()
        status = 'error' if fatal else 'completed'
    except BaseException as exc:
        status = 'interrupted' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'error'
        exception_type = type(exc).__name__
        raise
    finally:
        try: result = checkpoint()
        finally: journal.close()
    return result


def verify_chain(directory):
    from kylin_memory_bench.common import read_json
    directory = Path(directory); result = read_json(directory/'results.json'); previous = None; events = []
    status = result.get('status','completed')
    if status not in ('running','completed','interrupted','error'): raise BenchError('Invalid task-chain status')
    revised = result.get('implementation_revision') == CHAIN_REVISION
    if result.get('implementation_revision') and not revised: raise BenchError('Unknown task-chain implementation')
    truncated = False
    lines = (directory/'evidence.jsonl').read_text(encoding='utf-8').splitlines(keepends=True)
    for i,line in enumerate(lines,1):
        if not line.endswith('\n'):
            if status == 'completed' or i != len(lines): raise BenchError('Truncated task-chain evidence')
            truncated = True; break
        event = strict_json(line); payload = {k:v for k,v in event.items() if k != 'hash'}
        if event['event_id'] != str(i) or event['previous_hash'] != previous or digest(payload) != event['hash'] or event['run_id'] != result['run_id']:
            raise BenchError('Task-chain evidence hash mismatch')
        previous = event['hash']; events.append(event)
    saved_count = result['event_count']
    if type(saved_count) is not int or not 0 <= saved_count <= len(events): raise BenchError('Task-chain manifest mismatch')
    saved_head = events[saved_count-1]['hash'] if saved_count else None
    if result['evidence_head'] != saved_head or status == 'completed' and (saved_count != len(events) or truncated):
        raise BenchError('Task-chain manifest mismatch')
    from .reference_adapter import parse_question
    pending = None; replayed = []; prior_stage = -1

    def verify_forwarded(request):
        expected = public_delivery(pending) if pending else None
        if forwarded_delivery(request['prompt']) != expected or parse_records(request['prompt']) != (pending['component_checks'] if pending else []):
            raise BenchError('Task-chain forwarded feedback differs from actual validation')

    for event in events:
        stage_index = next((i for i,(name,_) in enumerate(STAGE_LIMITS) if name == event['stage']),-1)
        if stage_index < prior_stage or stage_index < 0: raise BenchError('Invalid task-chain stage order')
        prior_stage = stage_index
        if revised: verify_forwarded(event['request'])
        if event.get('kind') == 'feedback_delivery':
            pending = None; replayed.append(event); continue
        query = parse_question(event['request']['prompt']); required = event['tool_feedback']['required']
        spec = artifact_spec(query,{'values':required})
        recomputed = tool_feedback(required,query,event['artifact'])
        if recomputed != event['tool_feedback']: raise BenchError('Task-chain validation feedback differs from replay')
        declared = None
        if event['response']:
            try: declared = strict_json(event['response']['text']).get('answer')
            except (ValueError,AttributeError): pass
        chosen = next((o for o in query['options'] if o['id'] == declared),None)
        selected_values = chosen['values'] if chosen else None
        content = selected_values is not None and selected_values == required
        accepted = bool(not event['error'] and content and grade_delivery(event['artifact'],spec)['file_success'])
        if event['content_correct'] is not content or event['task_success'] is not accepted:
            raise BenchError('Task-chain score differs from replay')
        if revised:
            pending = feedback_payload(query,required,selected_values,event['artifact'],recomputed,event['stage'],event['attempt'])
            if pending != event['feedback_payload']: raise BenchError('Task-chain feedback payload differs from actual validation')
        replayed.append(dict(event,content_correct=content,task_success=accepted))
    reconstructed = stage_summaries(replayed,incomplete=status != 'completed',interrupted=status == 'interrupted')
    completed_success = status == 'completed' and all(s['stage_success'] for s in reconstructed)
    if result['chain_success'] is not completed_success:
        raise BenchError('Task-chain summary differs from independent replay')
    if saved_count == len(events) and (result['stages'] != reconstructed or result['transfer_first_attempt_success'] != reconstructed[-1]['first_attempt_success']):
        raise BenchError('Task-chain summary differs from independent replay')
    flight = result.get('in_flight')
    if revised and flight and flight['request']['day'] > len(events): verify_forwarded(flight['request'])
    return {'valid':True,'events':len(events),'status':status,'complete':status == 'completed',
            'truncated_tail':truncated,'uncheckpointed_events':len(events)-saved_count,'replayed_stages':reconstructed,
            'scope':'Recorded hash prefix, actual tool feedback and score replay; incomplete stays incomplete. Not a signature or native isolation proof.'}


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
