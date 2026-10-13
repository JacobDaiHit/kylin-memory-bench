"""Adapters only observe prompts. Expected answers and scoring rules stay in the runner."""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .baseline import Baseline
from . import native_trace
from .common import BenchError, ID_RE, MAX_FILE_BYTES, canonical, contained, positive_number, read_json, strict_json, write_json

BASE_ENV = ('PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
            'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
KINDS = {'baseline', 'command', 'openclaw', 'hermes'}


def load_config(path):
    config = read_json(path)
    if not isinstance(config, dict) or config.get('schema_version') != '1.0':
        raise BenchError('Agent config schema_version must be 1.0')
    agents = config.get('agents')
    if not isinstance(agents, list) or not agents:
        raise BenchError('agents must be a nonempty list')
    seen = set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise BenchError('agent must be an object')
        name = agent.get('id', '')
        if not isinstance(name, str) or not ID_RE.fullmatch(name) or name in seen:
            raise BenchError('Invalid/duplicate agent id')
        seen.add(name)
        if not isinstance(agent.get('kind'), str) or agent['kind'] not in KINDS:
            raise BenchError('Unknown adapter kind: ' + str(agent.get('kind')))
        if not positive_number(agent.get('timeout', 120)) or agent.get('timeout', 120) > 3600:
            raise BenchError('timeout must be in (0, 3600]')
        if agent['kind'] == 'baseline' and agent.get('policy') not in {'selective', 'naive', 'stateless'}:
            raise BenchError('Unknown baseline policy')
        if agent['kind'] == 'command':
            argv = agent.get('command')
            if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
                raise BenchError('command must be an argv list; shell strings are not supported')
        names = agent.get('env_allow', [])
        if not isinstance(names, list) or not all(isinstance(x, str) and x.isidentifier() for x in names):
            raise BenchError('env_allow must list environment variable names')
        if not isinstance(agent.get('memory_complete', False), bool):
            raise BenchError('memory_complete must be boolean')
        patterns = agent.get('memory_globs', [])
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p and not p.startswith('/') and '..' not in p.split('/') and '\\' not in p for p in patterns):
            raise BenchError('memory_globs must contain safe relative glob strings')
        for field in ('label', 'model', 'provider', 'executable', 'dependency_home'):
            if field in agent and (not isinstance(agent[field], str) or not agent[field]):
                raise BenchError(field + ' must be a nonempty string')
        if 'native_config' in agent and not isinstance(agent['native_config'], dict):
            raise BenchError('native_config must be an object')
        if 'per_turn_proxy_limits' in agent and not isinstance(agent['per_turn_proxy_limits'], bool):
            raise BenchError('per_turn_proxy_limits must be boolean')
        if agent.get('state_isolation', 'none') not in ('none', 'mount_namespace'):
            raise BenchError('state_isolation must identify a mount-namespace wrapper or none')
    return config


def redact(value, secrets=()):
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            sensitive = key.lower() in ('token', 'access_token', 'refresh_token') or any(token in key.lower() for token in ('api_key', 'apikey', 'password', 'secret', 'authorization'))
            result[key] = '[REDACTED]' if sensitive else redact(item, secrets)
        return result
    return value


def credentials(config):
    # Only explicitly allowlisted environment variables; never inspect credential files.
    return [os.environ[name] for agent in config['agents'] for name in agent.get('env_allow', [])
            if name in os.environ and any(t in name.upper() for t in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]


def process(argv, cwd, env, stdin, timeout):
    """Bounded output and timeout. POSIX timeout terminates the owned process group."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            child = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                                     stdout=out, stderr=err, start_new_session=(os.name != 'nt'))
        except OSError as exc:
            raise BenchError('Cannot start adapter executable: ' + str(exc)) from exc
        start = time.monotonic()
        timed_out, oversized = False, False
        try:
            # Requests have a validated bounded length. communicate supplies stdin safely.
            payload = stdin.encode('utf-8') if stdin is not None else b''
            while True:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    child.communicate(input=payload, timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    payload = None
                if os.fstat(out.fileno()).st_size > MAX_FILE_BYTES or os.fstat(err.fileno()).st_size > MAX_FILE_BYTES:
                    oversized = True
                    break
        except BaseException:
            _stop(child)
            raise
        finally:
            if child.poll() is None:
                _stop(child)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(MAX_FILE_BYTES + 1), err.read(MAX_FILE_BYTES + 1)
        if timed_out:
            raise BenchError(f'Adapter timeout after {timeout}s')
        if oversized or len(stdout) > MAX_FILE_BYTES or len(stderr) > MAX_FILE_BYTES:
            raise BenchError('Adapter output exceeds 2 MiB limit')
        if child.returncode != 0:
            # Do not persist arbitrary stderr, which might contain provider credentials.
            raise BenchError(f'Adapter exited {child.returncode}; stderr SHA256 is ' + __import__('hashlib').sha256(stderr).hexdigest())
        try:
            return stdout.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise BenchError('Adapter stdout is not UTF-8') from exc


def _stop(child):
    if os.name != 'nt':
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        child.kill()
    child.wait(timeout=10)


def validate_response(response):
    if not isinstance(response, dict) or not isinstance(response.get('text'), str):
        raise BenchError('Adapter response requires text:string')
    if len(canonical(response).encode('utf-8')) > MAX_FILE_BYTES:
        raise BenchError('Adapter response exceeds 2 MiB')
    memory = response.get('memory')
    if memory is not None:
        if not isinstance(memory, dict) or not isinstance(memory.get('text'), str) or type(memory.get('complete')) is not bool:
            raise BenchError('memory must be null or {text:string, complete:boolean}')
    actions = response.get('actions')
    if actions is not None:
        if not isinstance(actions, list) or any(not isinstance(a, dict) or not isinstance(a.get('name'), str) for a in actions):
            raise BenchError('actions must be null or a list of named objects')
    return response


def snapshot(workspace, patterns, complete=False):
    files, text, errors = [], [], []
    root = Path(workspace)
    for pattern in patterns:
        if pattern.startswith('/') or '..' in pattern.split('/') or '\\' in pattern:
            raise BenchError('Unsafe memory glob')
        for path in sorted(root.glob(pattern)):
            relative = path.relative_to(root).as_posix()
            if relative in files:
                continue
            try:
                safe = contained(root, relative)
                if not safe.is_file():
                    continue
                if safe.stat().st_size > MAX_FILE_BYTES or sum(len(x.encode('utf-8')) for x in text) + safe.stat().st_size > MAX_FILE_BYTES:
                    errors.append(relative + ': size limit')
                    continue
                text.append(safe.read_text(encoding='utf-8'))
                files.append(relative)
            except (OSError, UnicodeError, BenchError):
                errors.append(relative + ': unreadable or unsafe')
    return {'text': '\n'.join(text), 'complete': complete and not errors, 'files': files,
            'errors': errors, 'scope': 'configured native memory files only'}


class External:
    def __init__(self, config, workspace):
        self.config = config
        self.workspace = Path(workspace).resolve()
        self.sessions = {}
        self.env = {name: os.environ[name] for name in (*BASE_ENV, *config.get('env_allow', [])) if name in os.environ}
        self.env['PYTHONIOENCODING'] = 'utf-8'
        self.env['PYTHONUTF8'] = '1'
        private_home = self.workspace / '.home'
        private_home.mkdir(mode=0o700, exist_ok=True)
        self.env['HOME'] = self.env['USERPROFILE'] = str(private_home)
        self.env['XDG_CONFIG_HOME'] = str(private_home / '.config')
        self.env['XDG_DATA_HOME'] = str(private_home / '.local/share')
        self.env['XDG_CACHE_HOME'] = str(private_home / '.cache')
        if config['kind'] == 'openclaw':
            state = self.workspace / '.openclaw'
            state.mkdir(mode=0o700, exist_ok=True)
            native = self._native_config()
            write_json(state / 'openclaw.json', native)
            self.env.update(OPENCLAW_HOME=str(private_home), OPENCLAW_STATE_DIR=str(state),
                            OPENCLAW_CONFIG_PATH=str(state / 'openclaw.json'), OPENCLAW_WORKSPACE_DIR=str(self.workspace))
        if config['kind'] == 'hermes':
            home = self.workspace / '.hermes'
            home.mkdir(mode=0o700, exist_ok=True)
            self.env['HERMES_HOME'] = str(home)
            if config.get('dependency_home'):
                # Hermes PM stores immutable dependency generations under its home.
                # Share only installed runtimes; never link memory, config or auth.
                dependencies = Path(config['dependency_home']).resolve()
                for name in ('installs', 'tools'):
                    if not (dependencies / name).is_dir():
                        raise BenchError('Hermes dependency_home requires installs/ and tools/')
                (home / 'installs').symlink_to(dependencies / 'installs', target_is_directory=True)
                self.env['HERMES_RUNTIME_DIR'] = str(dependencies / 'tools')
                self.env['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
            # JSON is a YAML subset; Hermes consumes config.yaml.
            write_json(home / 'config.yaml', config.get('native_config', {}))

    def _native_config(self):
        # Rebuild from the template so per-turn caps never accumulate; always
        # reapply case bindings before writing a native configuration.
        native = strict_json(canonical(self.config.get('native_config', {})))
        if self.config['kind'] == 'openclaw':
            agents = native.setdefault('agents', {})
            if agents.get('list') or agents.get('entries'):
                raise BenchError('Native OpenClaw config must not override per-agent workspaces')
            defaults = agents.setdefault('defaults', {})
            defaults['workspace'] = str(self.workspace)
            if self.config.get('model'):
                defaults['model'] = self.config['model']
        return native

    def turn(self, request):
        kind = self.config['kind']
        timeout = self.config.get('timeout', 120)
        if kind == 'command':
            replacements = {'{python}': sys.executable, '{workspace}': str(self.workspace)}
            argv = [replacements.get(arg, arg) for arg in self.config['command']]
            return validate_response(strict_json(process(argv, self.workspace, self.env, canonical(request) + '\n', timeout)))
        # Time is simulated and explicitly supplied, never represented as real elapsed time.
        prompt = f"[Benchmark simulated day: {request['day']}]\n" + request['prompt']
        prompt_file = self.workspace / '.turn-prompt.txt'
        prompt_file.write_text(prompt, encoding='utf-8')
        if self.config.get('per_turn_proxy_limits'):
            from urllib.parse import urlsplit
            limit = request.get('output_tokens', 1024)
            if type(limit) is not int or not 256 <= limit <= 8192:
                raise BenchError('Invalid per-turn output limit')
            native = self._native_config()
            providers = native.get('models', {}).get('providers', {}) if kind == 'openclaw' else native.get('providers', {})
            settings = list(providers.values()) + ([native['model']] if kind == 'hermes' and 'model' in native else [])
            for setting in settings:
                for key in ('baseUrl', 'base_url'):
                    if key in setting:
                        url = setting[key].rstrip('/')
                        if urlsplit(url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
                            raise BenchError('Per-turn proxy limits require a loopback budget proxy')
                        setting[key] = url + '/cap/' + str(limit)
                for model in setting.get('models', []):
                    model['maxTokens'] = limit
            write_json(self.workspace / ('.openclaw/openclaw.json' if kind == 'openclaw' else '.hermes/config.yaml'), native)
        if kind == 'openclaw':
            before = native_trace.cursor(self.workspace, request['session_id'])
            argv = [self.config.get('executable', 'openclaw'), 'agent', '--local', '--session-id',
                    request['session_id'], '--message-file', str(prompt_file), '--json', '--timeout', str(int(timeout))]
            raw = strict_json(process(argv, self.workspace, self.env, None, timeout))
            if not isinstance(raw, dict):
                raise BenchError('OpenClaw JSON must be an object')
            body = raw.get('result', raw)
            if not isinstance(body, dict) or not isinstance(body.get('meta', {}), dict):
                raise BenchError('Invalid OpenClaw result/meta envelope')
            meta = body.get('meta', {})
            if raw.get('ok') is False or raw.get('status') in ('error', 'timeout', 'cancelled') or body.get('error') or meta.get('error') or meta.get('aborted'):
                raise BenchError('OpenClaw reported an unsuccessful run')
            text = body.get('final')
            if text is None:
                payloads = body.get('payloads', [])
                if not isinstance(payloads, list):
                    raise BenchError('OpenClaw payloads must be an array')
                text = '\n'.join(p['text'] for p in payloads if isinstance(p, dict) and isinstance(p.get('text'), str))
            if not isinstance(text, str) or not text:
                raise BenchError('OpenClaw JSON contains no final text; check CLI version')
            memory = snapshot(self.workspace, self.config.get('memory_globs', ['MEMORY.md', 'USER.md', 'memory/**/*.md']),
                              self.config.get('memory_complete', False))
            actions, trace = native_trace.collect(self.workspace, request['session_id'], before)
            return validate_response({'text': text, 'memory': memory, 'actions': actions,
                                      'trace': trace, 'usage': body.get('usage', {}), 'provenance': 'openclaw-cli'})
        argv = [self.config.get('executable', 'hermes'), 'chat', '--query-file', str(prompt_file), '--format', 'stream-json']
        if request['session_id'] in self.sessions:
            argv += ['--resume', self.sessions[request['session_id']]]
        if self.config.get('model'):
            argv += ['--model', self.config['model']]
        if self.config.get('provider'):
            argv += ['--provider', self.config['provider']]
        raw = process(argv, self.workspace, self.env, None, timeout)
        events = [strict_json(line) for line in raw.splitlines() if line.strip()]
        results = [event for event in events if isinstance(event, dict) and event.get('type') == 'result']
        if len(results) != 1 or results[0].get('exit_code') != 0 or results[0].get('error'):
            raise BenchError('Hermes stream must have one successful result event')
        result = results[0]
        if not isinstance(result.get('session_id'), str) or not result['session_id']:
            raise BenchError('Hermes returned no session_id')
        self.sessions[request['session_id']] = result['session_id']
        actions = [native_trace.normalized_action(e.get('name'), e.get('input', {}), self.workspace) for e in events
                   if isinstance(e, dict) and e.get('type') == 'tool_use']
        memory = snapshot(self.workspace, self.config.get('memory_globs', ['.hermes/memories/*.md']),
                          self.config.get('memory_complete', False))
        return validate_response({'text': result.get('text'), 'memory': memory, 'actions': actions,
                                  'usage': result.get('tokens', {}), 'provenance': 'hermes-cli'})


def create_adapter(config, workspace):
    if config['kind'] == 'baseline':
        return Baseline(config['policy'], workspace)
    return External(config, workspace)
