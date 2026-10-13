"""Standalone ChatGPT-plan authorization probe, NOT a benchmark provider.

Official protocol: https://developers.openai.com/siwc/token-sharing-open-source
Optional dependencies: scripts/chatgpt-plan-requirements.txt. No Codex credential import.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
import uuid
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

AUTH = 'https://auth.openai.com'
API = 'https://api.openai.com/v1'
SCOPE = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
TARGET = 'gpt-5.6-luna'


class ProbeError(Exception):
    pass


def atomic_private(path, value):
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def read_json(path):
    if path.is_symlink(): raise ProbeError('Refusing a symlink in credential storage.')
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


@contextmanager
def locked(root):
    if os.name != 'posix': raise ProbeError('Run this credential helper inside WSL/Linux.')
    if root.is_symlink(): raise ProbeError('Credential directory must not be a symlink.')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    lock = root/'active.lock'
    try: fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError: raise ProbeError('Another command is active (active.lock). Do not run concurrent logins or refreshes.')
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally: lock.unlink()


def request(method, url, **kwargs):
    import requests
    # Fixed official hosts only; never redirect a bearer credential.
    if urlsplit(url).scheme != 'https' or urlsplit(url).netloc not in {'auth.openai.com', 'api.openai.com'}:
        raise ProbeError('Unexpected service endpoint.')
    try:
        response = requests.request(method, url, timeout=(10, 30), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise ProbeError('Network request failed; no automatic retry. Check connectivity.') from None
    if not 200 <= response.status_code < 300:
        code = ''
        try:
            error = response.json().get('error', '')
            code = error.get('code', '') if isinstance(error, dict) else error
        except (ValueError, AttributeError): pass
        # Never print arbitrary server messages, callback URLs or token contents.
        code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,80}', code) else 'request_rejected'
        status = response.status_code; response.close()
        raise ProbeError('HTTP %s / %s' % (status, code))
    return response


def remote_json(method, url, **kwargs):
    with request(method, url, **kwargs) as response: return response.json()


def authorization(host, redirect, registration=None):
    verifier, state, nonce = [secrets.token_urlsafe(48) for _ in range(3)]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    params = {'client_id': (registration or {}).get('client_id', 'dynamic_agent_client'),
              'ext_agent_host_id': host, 'response_type': 'code', 'redirect_uri': redirect,
              'scope': SCOPE, 'resource': API, 'state': state, 'nonce': nonce,
              'code_challenge_method': 'S256', 'code_challenge': challenge}
    if not registration: params['agent_name_hint'] = 'Kylin Memory Bench'
    return AUTH+'/api/accounts/authorize?'+urlencode(params), verifier, state, nonce


def callback_values(path, state, registration=None):
    parsed = urlsplit(path)
    if parsed.path != '/auth/callback': raise ProbeError('Wrong callback path.')
    values = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(v) != 1 for v in values.values()): raise ProbeError('Repeated callback parameter.')
    values = {k: v[0] for k, v in values.items()}
    if not secrets.compare_digest(values.get('state', '').encode(), state.encode()): raise ProbeError('OAuth state mismatch.')
    if values.get('error'): raise ProbeError('Authorization was declined or unavailable.')
    client = values.get('client_id') or (registration or {}).get('client_id')
    if not client or client == 'dynamic_agent_client' or not values.get('code'):
        raise ProbeError('Authorization callback is incomplete.')
    if registration and client != registration['client_id']: raise ProbeError('Registered client changed.')
    return client, values['code']


def validate_identity(token, client, nonce, jwks):
    import jwt
    header = jwt.get_unverified_header(token)
    if header.get('alg') not in ('RS256', 'ES256'): raise ProbeError('Unsupported ID-token signature algorithm.')
    matches = [k for k in jwks['keys'] if k.get('kid') == header.get('kid') and k.get('use', 'sig') == 'sig']
    if len(matches) != 1: raise ProbeError('ID-token signing key is missing or ambiguous.')
    key = jwt.PyJWK.from_dict(matches[0]).key
    claims = jwt.decode(token, key, algorithms=[header['alg']], audience=client, issuer=AUTH,
                        leeway=5, options={'require': ['sub', 'exp', 'iat', 'iss', 'aud', 'nonce']})
    if claims['nonce'] != nonce or not isinstance(claims['sub'], str) or not claims['sub']:
        raise ProbeError('ID-token identity/nonce validation failed.')
    if isinstance(claims['aud'], list) and len(claims['aud']) > 1 and claims.get('azp') != client:
        raise ProbeError('ID-token authorized party mismatch.')
    return claims


def credential_record(tokens, client, host, claims, previous=None):
    previous = previous or {}
    scopes = tokens.get('scope', ' '.join(previous.get('scopes', []))).split()
    if not {'chatgpt.tokens.use.direct', 'resource.invoke'}.issubset(scopes):
        raise ProbeError('Login succeeded, but ChatGPT plan inference permission was not granted.')
    if not tokens.get('access_token') or str(tokens.get('token_type', '')).lower() != 'bearer':
        raise ProbeError('Invalid token response.')
    expires = tokens.get('expires_in')
    if type(expires) not in (int, float) or not 0 < expires < 365*86400:
        raise ProbeError('Invalid token expiry.')
    if previous.get('subject') and claims['sub'] != previous['subject']:
        raise ProbeError('Different account: use a separate --profile name.')
    return {'client_id': client, 'ext_agent_host_id': host, 'subject': claims['sub'],
            'access_token': tokens['access_token'], 'refresh_token': tokens.get('refresh_token', previous.get('refresh_token')),
            'id_token': tokens.get('id_token', previous.get('id_token')), 'scopes': scopes,
            'expires_at': time.time()+expires}


def login(root, profile, port, no_browser):
    state_file = root/(profile+'.json'); old = read_json(state_file)
    host_file = root/'host.json'; host = read_json(host_file)
    if not host:
        host = {'id': 'urn:uuid:'+str(uuid.uuid4())}; atomic_private(host_file, host)
    received = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            try:
                values = callback_values(self.path, pending_state, old or None)
                received['values'] = values
                message, status = b'Authorization received. Return to your terminal for validation.', 200
            except ProbeError:
                values = parse_qs(urlsplit(self.path).query)
                if values.get('state') == [pending_state] and values.get('error'):
                    received['denied'] = True
                # Invalid/unsolicited callbacks cannot terminate a valid pending attempt.
                message, status = b'Authorization callback rejected. Check the terminal or restart login.', 400
            self.send_response(status); self.send_header('Content-Type', 'text/plain')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers(); self.wfile.write(message)
    class CallbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address
    with CallbackServer(('127.0.0.1', port), Handler) as server:
        server.timeout = 1
        redirect = 'http://127.0.0.1:%d/auth/callback' % server.server_port
        url, verifier, pending_state, nonce = authorization(host['id'], redirect, old or None)
        print('Continue with ChatGPT: open this URL in the browser on THIS computer.\n'+url, flush=True)
        if not no_browser: webbrowser.open(url)
        deadline = time.monotonic()+300
        while not received and time.monotonic() < deadline: server.handle_request()
    if not received: raise ProbeError('Login timed out after 5 minutes; run login again.')
    if received.get('denied'): raise ProbeError('Authorization was declined or unavailable; no token exchange made.')
    client, code = received['values']
    tokens = remote_json('POST', AUTH+'/api/accounts/oauth/token', data={
        'grant_type': 'authorization_code', 'client_id': client, 'code': code,
        'code_verifier': verifier, 'redirect_uri': redirect, 'resource': API})
    jwks = remote_json('GET', AUTH+'/.well-known/jwks.json')
    claims = validate_identity(tokens['id_token'], client, nonce, jwks)
    atomic_private(state_file, credential_record(tokens, client, host['id'], claims, old))
    print('Authorized. Credentials saved outside the repository. Next: models')


def access(root, profile):
    path = root/(profile+'.json'); saved = read_json(path)
    if not saved: raise ProbeError('Run login first.')
    if saved['expires_at'] < time.time()+60:
        if not saved.get('refresh_token'): raise ProbeError('Session expired; run login again.')
        tokens = remote_json('POST', AUTH+'/api/accounts/oauth/token', data={
            'grant_type': 'refresh_token', 'client_id': saved['client_id'],
            'refresh_token': saved['refresh_token'], 'resource': API})
        # Identity stays bound to the verified registration; a refresh ID token
        # is not used as new account identity or as a subsequent login hint.
        tokens.pop('id_token', None)
        saved = credential_record(tokens, saved['client_id'], saved['ext_agent_host_id'],
                                  {'sub': saved['subject']}, saved)
        atomic_private(path, saved)
    return saved['access_token']


def models(token):
    data = remote_json('GET', API+'/models', headers={'Authorization': 'Bearer '+token})
    if not isinstance(data.get('models'), list): raise ProbeError('Unexpected plan model-catalog format.')
    return [{'slug': r['slug'], 'display_name': r.get('display_name', r['slug'])}
            for r in data['models'] if r.get('visibility') == 'list' and isinstance(r.get('slug'), str)]


def parse_stream(lines):
    completed, buffer, size = None, [], 0
    deltas, event_counts, items = [], {}, {}
    def event(data):
        obj = json.loads('\n'.join(data)); kind = obj.get('type')
        event_counts[kind] = event_counts.get(kind, 0)+1
        if kind == 'response.output_item.done':
            index = obj.get('output_index')
            if type(index) is not int or index in items: raise ProbeError('Duplicate or invalid output item index.')
            items[index] = obj['item']
        if kind == 'response.output_text.delta':
            if not isinstance(obj.get('delta'), str): raise ProbeError('Invalid text delta.')
            deltas.append(obj['delta'])
        if kind in ('error', 'response.failed', 'response.incomplete'):
            raise ProbeError('Inference failed or incomplete; no retry was made.')
        if kind == 'response.completed':
            response = obj.get('response', {})
            if response.get('status') != 'completed': raise ProbeError('Invalid completion event.')
            return response
        return None
    for raw in lines:
        line = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        size += len(line)
        if size > 2_000_000: raise ProbeError('Probe stream exceeded local size limit; completion unknown.')
        if not line:
            if buffer:
                if buffer != ['[DONE]']:
                    found = event(buffer)
                    if found is not None:
                        if completed is not None: raise ProbeError('Duplicate completion event.')
                        completed = found
                buffer = []
        elif line.startswith('data:'): buffer.append(line[5:].lstrip(' '))
    if buffer: raise ProbeError('Truncated SSE event; completion unknown.')
    if completed is None: raise ProbeError('Stream ended without completed inference.')
    completed['_probe_stream'] = {'event_counts': event_counts,
                                  'delta_text': ''.join(deltas) if deltas else None,
                                  'output_items': [items[i] for i in sorted(items)]}
    return completed


def text_diagnostics(result):
    """Keep transport completion separate from observing the expected reply."""
    parts = [c['text'] for item in (result.get('output') or [])
             for c in (item.get('content') or [])
             if c.get('type') == 'output_text' and isinstance(c.get('text'), str)]
    final = ''.join(parts) if parts else None
    stream = result.get('_probe_stream', {})
    delta = stream.get('delta_text')
    conflict = final is not None and delta is not None and final != delta
    text = None if conflict else (final if final is not None else delta)
    status = 'conflicting_text' if conflict else ('unobserved' if text is None else ('pass' if text.strip() == 'OK' else 'mismatch'))
    return {'connectivity_ok': True, 'text_check_status': status,
            'text_is_ok': None if text is None else text.strip() == 'OK',
            'reply_text': text, 'text_source': None if text is None else ('completed_output' if final is not None else 'stream_deltas'),
            'completed_output_text': final, 'stream_delta_text': delta,
            'stream_event_counts': stream.get('event_counts', {})}


def smoke(root, profile, model, allowed):
    if not allowed: raise ProbeError('This consumes ChatGPT plan usage. Add --allow-one-request to run once.')
    token = access(root, profile)
    if model not in {r['slug'] for r in models(token)}: raise ProbeError('Requested model is absent from the live account catalog.')
    log = root/('probe-'+str(uuid.uuid4())+'.json')
    record = {'requested_model': model, 'status': 'started', 'attempts': 1,
              'started_at': time.time(), 'benchmark_score': False, 'server_output_cap': None}
    atomic_private(log, record)
    try:
        body = {'model': model, 'input': [{'role': 'user', 'content': 'Reply with exactly OK.'}],
                'store': False, 'stream': True}
        with request('POST', API+'/responses', headers={'Authorization': 'Bearer '+token}, json=body, stream=True) as response:
            result = parse_stream(response.iter_lines())
        record.update(status='completed', reported_model=result.get('model'), usage=result.get('usage'),
                      **text_diagnostics(result))
    except BaseException:
        record['status'] = 'failed_or_interrupted'; raise
    finally:
        record['finished_at'] = time.time(); atomic_private(log, record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['login', 'models', 'smoke'])
    parser.add_argument('--profile', default='default')
    parser.add_argument('--port', type=int, default=1455)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--model', default=TARGET)
    parser.add_argument('--allow-one-request', action='store_true')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}', args.profile): parser.error('Invalid profile name')
    root = Path.home()/'.config/kmb-chatgpt-plan'
    try:
        import jwt, requests  # noqa: F401; optional dependencies only for this helper
        with locked(root):
            if args.command == 'login': login(root, args.profile, args.port, args.no_browser)
            elif args.command == 'models':
                rows = models(access(root, args.profile))
                print(json.dumps({'models': rows, 'requested_model': args.model,
                                  'available': args.model in {r['slug'] for r in rows}}, ensure_ascii=False, indent=2))
            else:
                result = smoke(root, args.profile, args.model, args.allow_one_request)
                if result['text_is_ok'] is not True: return 2
    except ProbeError as exc: print(str(exc), file=sys.stderr); return 1
    except ImportError: print('Install scripts/chatgpt-plan-requirements.txt in a virtual environment.', file=sys.stderr); return 1
    except KeyboardInterrupt: print('Stopped. No automatic retry.', file=sys.stderr); return 130
    except Exception as exc:
        print(type(exc).__name__+': operation failed; sensitive error details suppressed.', file=sys.stderr); return 1
    return 0


if __name__ == '__main__': sys.exit(main())
