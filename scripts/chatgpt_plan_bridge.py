"""Bounded, loopback-only Chat Completions -> ChatGPT plan Responses bridge.

Opt-in native compatibility protocol: requested sampling/output caps are recorded
but NOT enforced upstream. No memory/retrieval/answer assistance is added here.
"""
import hashlib
import json
import os
import secrets
import time
import threading
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from scripts import chatgpt_plan as plan

NAMESPACE = 'native_tools'
AUTH_LOCK = threading.Lock()
# Native clients send these automatically. Their absence upstream is disclosed
# in every request record; this route is NOT the DeepSeek capped protocol.
UNSUPPORTED = {'temperature', 'top_p', 'max_tokens', 'max_completion_tokens'}


def error_status(exc):
    """Keep invalid input distinct from retryable provider/transport failures."""
    if isinstance(exc, plan.ProbeError):
        match=re.match(r'^HTTP (\d{3}) /',str(exc))
        if match:return int(match.group(1))
        return 502
    if isinstance(exc,(ValueError,TypeError)):return 400
    try:
        import requests
    except ImportError:
        return 500
    if isinstance(exc,requests.Timeout):return 504
    if isinstance(exc,requests.RequestException):return 502
    return 500


def translate(body, model, replay=None):
    if body.get('model') != model: raise ValueError('model_mismatch')
    allowed = {'model','messages','tools','tool_choice','stream','stream_options',
               'parallel_tool_calls','reasoning_effort'} | UNSUPPORTED
    if set(body)-allowed: raise ValueError('unsupported_request_fields: '+','.join(sorted(set(body)-allowed)))
    inputs = []
    for message in body['messages']:
        role = message['role']; content = message.get('content')
        if isinstance(content, list):
            if any(p.get('type') != 'text' for p in content): raise ValueError('text_only')
            content = ''.join(p['text'] for p in content)
        if content is not None and not isinstance(content, str): raise ValueError('invalid_content')
        if role == 'tool':
            inputs.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':content or ''})
        elif role in ('user','assistant','developer','system'):
            if content:
                inputs.append({'role':'developer' if role == 'system' else role,'content':content})
            for call in message.get('tool_calls', []):
                if role != 'assistant' or call['type'] != 'function': raise ValueError('invalid_tool_call')
                inputs.extend((replay or {}).get(call['id'], []))
                inputs.append({'type':'function_call','call_id':call['id'],'namespace':NAMESPACE,
                               'name':call['function']['name'],'arguments':call['function']['arguments']})
        else: raise ValueError('unsupported_role')
    tools = []
    for tool in body.get('tools') or []:
        if tool.get('type') != 'function': raise ValueError('unsupported_tool')
        function = tool['function']
        tools.append(dict(function, type='function', strict=function.get('strict', False)))
    result = {'model':model,'input':inputs,'stream':True,'store':False,'reasoning':{'effort':'none'}}
    if tools:
        result['tools'] = [{'type':'namespace','name':NAMESPACE,'description':'Native agent tools.', 'tools':tools}]
    if 'tool_choice' in body:
        if body['tool_choice'] not in ('auto','none','required'): raise ValueError('unsupported_tool_choice')
        result['tool_choice'] = body['tool_choice']
    if 'parallel_tool_calls' in body: result['parallel_tool_calls'] = body['parallel_tool_calls']
    if body.get('reasoning_effort') not in (None,'none'):
        raise ValueError('reasoning_replay_not_supported')
    return result, {k:body[k] for k in sorted(UNSUPPORTED & body.keys())}


def completed_chat(result, model):
    if result.get('status') != 'completed' or result.get('model') != model:
        raise ValueError('completion_or_model_mismatch')
    calls = []
    items = result.get('output') or result.get('_probe_stream',{}).get('output_items',[])
    for item in items:
        if item['type'] == 'function_call':
            if item.get('namespace') not in (None,NAMESPACE): raise ValueError('unexpected_namespace')
            calls.append({'id':item['call_id'],'type':'function','function':{
                'name':item['name'],'arguments':item['arguments']}})
        elif item['type'] == 'reasoning':
            if not item.get('encrypted_content'): raise ValueError('missing_reasoning_replay')
        elif item['type'] != 'message': raise ValueError('unsupported_output_item')
    diagnostic = plan.text_diagnostics(result)
    if diagnostic['text_check_status'] == 'conflicting_text': raise ValueError('conflicting_text')
    text = diagnostic['reply_text']
    if text is None and not calls: raise ValueError('no_observed_output')
    msg = {'role':'assistant','content':text}
    if calls: msg['tool_calls'] = calls
    usage = result.get('usage') or {}
    return {'id':result.get('id','chatcmpl-plan'),'object':'chat.completion','created':int(time.time()),
            'model':model,'choices':[{'index':0,'message':msg,'finish_reason':'tool_calls' if calls else 'stop'}],
            'usage':{'prompt_tokens':usage.get('input_tokens',0),'completion_tokens':usage.get('output_tokens',0),
                     'total_tokens':usage.get('total_tokens',0)}}


def append(path, data):
    with path.open('a', encoding='utf-8') as file:
        file.write(json.dumps(data,ensure_ascii=False)+'\n'); file.flush(); os.fsync(file.fileno())


class Bridge:
    def __init__(self, output, *, limit=24, model=plan.TARGET, capture=False, root=None, deadline_seconds=1800):
        self.output = Path(output); self.output.mkdir(parents=True,exist_ok=False,mode=0o700)
        self.limit=limit; self.model=model; self.capture=capture
        self.root = root or Path.home()/'.config/kmb-chatgpt-plan'
        self.key=secrets.token_urlsafe(32); self.count=0; self.context='unspecified'
        self.deadline=None if deadline_seconds is None else time.monotonic()+deadline_seconds
        self.replay={}

    def invoke(self, body):
        self.count += 1; number=self.count
        entry={'request':number,'context':self.context,'started_at':time.time(),
               'status':'reserved','upstream_attempted':False,'model':self.model,
               'server_output_cap':None,'capture_only':self.capture}
        if (self.limit is not None and number > self.limit) or (self.deadline is not None and time.monotonic() > self.deadline):
            raise ValueError('request_budget_exhausted')
        path=self.output/('%04d.json'%number)
        plan.atomic_private(path,entry)
        try:
            replay=self.replay.setdefault(self.context,{})
            translated, dropped=translate(body,self.model,replay)
            entry.update(native_request=body, upstream_request=translated, unsupported_parameters_omitted=dropped)
            plan.atomic_private(path,entry)
            if self.capture: raise ValueError('capture_only_no_upstream_request')
            with AUTH_LOCK:
                with plan.locked(self.root): token=plan.access(self.root,'default')
            entry['upstream_attempted']=True; plan.atomic_private(path,entry)
            with plan.request('POST',plan.API+'/responses',headers={'Authorization':'Bearer '+token},
                              json=translated,stream=True) as response:
                def lines():
                    for line in response.iter_lines():
                        # Preserve raw events (no HTTP headers/credentials) before parsing.
                        append(self.output/('%04d-stream.jsonl'%number),{'line':line.decode('utf-8')})
                        yield line
                result=plan.parse_stream(lines())
            entry['response']=result
            pending=[]
            for item in result.get('output') or result.get('_probe_stream',{}).get('output_items',[]):
                if item['type']=='reasoning': pending.append(item)
                elif item['type']=='function_call':
                    replay[item['call_id']]=pending; pending=[]
            answer=completed_chat(result,self.model)
            entry.update(status='completed',usage=result.get('usage'),reported_model=result.get('model'))
            return answer
        except BaseException as exc:
            entry.update(status='failed_or_interrupted',error_type=type(exc).__name__)
            # Only errors we control can be persisted as messages.
            if isinstance(exc,(plan.ProbeError,ValueError)): entry['error']=str(exc)
            raise
        finally:
            entry['finished_at']=time.time(); plan.atomic_private(path,entry)

    def server(self):
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                try:
                    if self.path != '/v1/chat/completions': raise ValueError('wrong_endpoint')
                    if not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+bridge.key):
                        raise ValueError('unauthorized')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0 < length <= 1_000_000: raise ValueError('input_size_limit')
                    body=json.loads(self.rfile.read(length))
                    result=bridge.invoke(body)
                    if body.get('stream'):
                        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                        choice=result['choices'][0]; delta=dict(choice['message'])
                        for i, call in enumerate(delta.get('tool_calls',[])): call['index']=i
                        chunk={k:result[k] for k in ('id','created','model')}
                        chunk.update(object='chat.completion.chunk',choices=[{'index':0,'delta':delta,'finish_reason':None}])
                        self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                        chunk['choices']=[{'index':0,'delta':{},'finish_reason':choice['finish_reason']}]
                        chunk['usage']=result['usage']
                        self.wfile.write(('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode())
                    else:
                        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
                        self.wfile.write(json.dumps(result).encode())
                except Exception as exc:
                    # Native SDK recovery is retained; every provider attempt is
                    # persisted. The evaluator does not rerun failed cases.
                    status=error_status(exc)
                    self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers()
                    kind='invalid_request_error' if status==400 else 'api_error'
                    self.wfile.write(json.dumps({'error':{'message':'Plan bridge request failed; inspect private ledger.','type':kind}}).encode())
        return HTTPServer(('127.0.0.1',0),Handler)
