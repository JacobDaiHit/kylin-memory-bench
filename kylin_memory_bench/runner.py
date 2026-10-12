"""Isolated execution, append-only hashed evidence and independently replayable scoring."""
import datetime
import concurrent.futures
import queue
import threading
import os
import platform
import sys
import time
import uuid
from pathlib import Path

from . import __version__
from .adapters import create_adapter, credentials, redact, validate_response
from .common import BenchError, MAX_FILE_BYTES, canonical, contained, digest, file_digest, read_json, strict_json, write_json
from .generate import save_dataset
from .dataset import load_dataset
from .scoring import score_run


def platform_info():
    os_release = {}
    if Path('/etc/os-release').is_file():
        for line in Path('/etc/os-release').read_text(encoding='utf-8').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                if key in ('ID', 'VERSION_ID', 'PRETTY_NAME'):
                    os_release[key] = value.strip('"')
    return {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine(),
            'python': platform.python_version(), 'os_release': os_release,
            'is_openkylin': os_release.get('ID', '').lower() == 'openkylin',
            'execution_context': 'container' if Path('/.dockerenv').exists() else
            ('wsl2' if 'microsoft' in platform.release().lower() else 'host-or-vm')}


def collect_artifacts(workspace, checks):
    result = {}
    for check in checks:
        if check['source'] != 'artifact' or check['path'] in result:
            continue
        relative = check['path']
        try:
            path = contained(workspace, relative)
            if not path.exists():
                result[relative] = {'exists': False}
            elif not path.is_file():
                result[relative] = {'exists': True, 'error': 'not a regular file'}
            elif path.stat().st_size > MAX_FILE_BYTES:
                result[relative] = {'exists': True, 'error': 'file exceeds size limit'}
            else:
                raw = path.read_bytes()
                result[relative] = {'exists': True, 'text': raw.decode('utf-8'),
                                    'sha256': __import__('hashlib').sha256(raw).hexdigest(), 'bytes': len(raw)}
        except (BenchError, OSError, UnicodeError) as exc:
            result[relative] = {'exists': None, 'error': str(exc)}
    return result


def case_events(agent, trial, case, output, run_id, stopped):
    workspace = output / 'workspaces' / agent['id'] / str(trial) / case['id']
    workspace.mkdir(parents=True)
    adapter, setup_error, case_error = None, None, None
    fresh_sessions = case.get('state_policy') == 'fresh_each_session'
    session_adapters = {}
    try:
        if fresh_sessions and agent['kind'] in {'openclaw', 'hermes'} and agent.get('state_isolation') != 'mount_namespace':
            raise BenchError('Native fresh_each_session requires a verified mount-namespace wrapper')
        if not fresh_sessions:
            adapter = create_adapter(agent, workspace)
    except (BenchError, OSError, ValueError, TypeError) as exc:
        setup_error = str(exc)
    for step in case['steps']:
        if stopped.is_set():
            return
        session_id = str(uuid.uuid5(uuid.UUID(run_id), f"{agent['id']}/{trial}/{case['id']}/{step['session']}"))
        active_workspace = workspace
        if fresh_sessions and not (setup_error or case_error):
            try:
                if session_id not in session_adapters:
                    active_workspace = workspace / 'sessions' / step['session']
                    active_workspace.mkdir(parents=True)
                    session_adapters[session_id] = (create_adapter(agent, active_workspace), active_workspace)
                adapter, active_workspace = session_adapters[session_id]
            except (BenchError, OSError, ValueError, TypeError) as exc:
                setup_error = str(exc)
        request = {'protocol_version': '1.0', 'session_id': session_id,
                   'day': step['day'], 'prompt': step['prompt'], 'workspace': str(active_workspace)}
        if step.get('output_tokens') is not None:
            request['output_tokens'] = step['output_tokens']
        started = time.perf_counter()
        response, error = None, setup_error or case_error
        if not error:
            try:
                response = validate_response(adapter.turn(request))
            except (BenchError, OSError, ValueError, TypeError) as exc:
                error = str(exc)
                case_error = 'Earlier step failed; remaining case steps were skipped: ' + error
        event = {'schema_version': '1.0', 
                 'agent_id': agent['id'], 'trial': trial, 'case_id': case['id'], 'step_id': step['id'],
                 'session_id': session_id, 'day': step['day'], 'kind': step['kind'],
                 'prompt': step['prompt'], 'response': response, 'error': error,
                 'duration_ms': round((time.perf_counter() - started) * 1000, 3),
                 'artifacts': collect_artifacts(active_workspace, step.get('checks', [])),
                 }
        if fresh_sessions:
            event['state_control'] = {'policy': 'fresh_each_session', 'workspace': str(active_workspace.relative_to(output)),
                                      'scope': 'Cross-session persistent-state availability; not a native memory-module-only switch.'}
        yield event


def scheduled_events(cases, config, output, run_id, repeats, jobs, progress):
    """Cases may overlap; each case's steps and private state stay strictly serial.

    Only the caller writes the evidence chain. Bounded queues preserve per-step
    evidence during a long case without retaining every pending response in RAM.
    """
    tasks = [(a, t, c) for t in range(repeats) for c in cases for a in config['agents']]
    stopped = threading.Event()
    if jobs == 1:
        for agent, trial, case in tasks:
            if progress:
                progress(agent['id'], trial, case['id'])
            yield from case_events(agent, trial, case, output, run_id, stopped)
        return
    messages = queue.Queue(maxsize=jobs * 2)

    def send(item):
        while not stopped.is_set():
            try:
                messages.put(item, timeout=.1)
                return
            except queue.Full:
                pass

    def worker(agent, trial, case):
        try:
            send(('start', (agent['id'], trial, case['id'])))
            for event in case_events(agent, trial, case, output, run_id, stopped):
                send(('event', event))
        except BaseException as exc:
            send(('error', exc))
        finally:
            send(('done', None))

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
    futures = [pool.submit(worker, *task) for task in tasks]
    try:
        remaining = len(tasks)
        while remaining:
            kind, value = messages.get()
            if kind == 'event':
                yield value
            elif kind == 'start' and progress:
                progress(*value)
            elif kind == 'error':
                raise value
            elif kind == 'done':
                remaining -= 1
    finally:
        stopped.set()
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True)


def execute(cases, config, output, repeats=1, progress=None, jobs=1):
    if type(jobs) is not int or not 1 <= jobs <= 16:
        raise BenchError('jobs must be in 1..16')
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise BenchError('repeats must be in 1..100')
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise BenchError('Output directory is not empty; choose a new run directory')
    output.mkdir(parents=True, exist_ok=True)
    secrets = credentials(config)
    safe_config = redact(config, secrets)
    run_id = str(uuid.uuid4())
    manifest = {'schema_version': '1.0', 'run_id': run_id, 'version': __version__, 'status': 'running',
                'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'environment': platform_info(), 'dataset_sha256': digest(cases),
                'config_sha256': digest(safe_config), 'agents': safe_config['agents'], 'repeats': repeats,
                'implementation_sha256': digest({p.name: p.read_text(encoding='utf-8') for p in sorted(Path(__file__).parent.glob('*.py'))}),
                'clock': 'simulated integer days; no real-time ageing claim', 'event_count': 0,
                'evidence_head': None, 'execution_errors': 0, 'jobs': jobs}
    save_dataset(output / 'dataset.jsonl', cases)
    write_json(output / 'config.json', safe_config)
    write_json(output / 'manifest.json', manifest)
    events = []
    previous = None
    try:
        with (output / 'evidence.jsonl').open('w', encoding='utf-8', newline='\n') as log:
            for event in scheduled_events(cases, config, output, run_id, repeats, jobs, progress):
                event = redact(event, secrets)
                event.update(event_id=str(len(events) + 1), previous_hash=previous)
                # Fingerprints describe the recorded, possibly redacted bytes.
                for artifact in event['artifacts'].values():
                    if 'text' in artifact:
                        raw = artifact['text'].encode('utf-8')
                        artifact['sha256'] = __import__('hashlib').sha256(raw).hexdigest()
                        artifact['bytes'] = len(raw)
                event['hash'] = digest(event)
                previous = event['hash']
                log.write(canonical(event) + '\n')
                log.flush()
                os.fsync(log.fileno())
                events.append(event)
                manifest.update(event_count=len(events), evidence_head=previous,
                                execution_errors=manifest['execution_errors'] + int(bool(event['error'])))
                write_json(output / 'manifest.json', manifest)
        manifest['status'] = 'completed_with_errors' if manifest['execution_errors'] else 'completed'
    except BaseException:
        manifest['status'] = 'interrupted'
        raise
    finally:
        manifest.update(event_count=len(events), evidence_head=previous,
                        finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write_json(output / 'manifest.json', manifest)
    report = score_run(manifest, cases, events)
    write_json(output / 'scores.json', report)
    from .report import render_report
    render_report(report, output)
    return report


def read_run(directory):
    directory = Path(directory)
    manifest = read_json(directory / 'manifest.json')
    cases = load_dataset(directory / 'dataset.jsonl')
    if manifest.get('schema_version') != '1.0' or manifest.get('dataset_sha256') != digest(cases):
        raise BenchError('Manifest schema or dataset fingerprint mismatch')
    config = read_json(directory / 'config.json')
    if manifest.get('config_sha256') != digest(config) or manifest['agents'] != config['agents']:
        raise BenchError('Configuration fingerprint mismatch')
    if type(manifest.get('repeats')) is not int or not 1 <= manifest['repeats'] <= 100:
        raise BenchError('Invalid repeat count in manifest')
    expected_steps = {(c['id'], s['id']): s for c in cases for s in c['steps']}
    events, previous = [], None
    for line_no, line in enumerate((directory / 'evidence.jsonl').read_text(encoding='utf-8').splitlines(), 1):
        event = strict_json(line)
        if not isinstance(event, dict) or event.get('schema_version') != '1.0':
            raise BenchError(f'Invalid evidence event at line {line_no}')
        step = expected_steps.get((event.get('case_id'), event.get('step_id')))
        if step is None or any(event.get(k) != step[k] for k in ('kind', 'day', 'prompt')):
            raise BenchError('Evidence request does not match dataset step')
        expected_session = str(uuid.uuid5(uuid.UUID(manifest['run_id']), f"{event.get('agent_id')}/{event.get('trial')}/{event['case_id']}/{step['session']}"))
        if event.get('session_id') != expected_session:
            raise BenchError('Evidence session does not match declared isolation protocol')
        expected_hash = event.get('hash')
        payload = {k: v for k, v in event.items() if k != 'hash'}
        if digest(payload) != expected_hash or event.get('previous_hash') != previous or event.get('event_id') != str(line_no):
            raise BenchError(f'Evidence hash chain mismatch at line {line_no}')
        if event.get('response') is not None:
            validate_response(event['response'])
        for artifact in event.get('artifacts', {}).values():
            if 'text' in artifact:
                raw = artifact['text'].encode('utf-8')
                if __import__('hashlib').sha256(raw).hexdigest() != artifact.get('sha256') or len(raw) != artifact.get('bytes'):
                    raise BenchError('Artifact content fingerprint mismatch')
        previous = expected_hash
        events.append(event)
    if manifest['event_count'] != len(events) or manifest['evidence_head'] != previous:
        raise BenchError('Manifest event count or evidence head mismatch')
    errors = sum(bool(e.get('error')) for e in events)
    if errors != manifest.get('execution_errors'):
        raise BenchError('Manifest execution error count mismatch')
    if manifest['status'] == 'completed' and errors:
        raise BenchError('Completed status contradicts execution errors')
    expected_count = sum(len(c['steps']) for c in cases) * manifest['repeats'] * len(manifest['agents'])
    if manifest['status'] in ('completed', 'completed_with_errors') and len(events) != expected_count:
        raise BenchError('Completed run is missing evidence steps')
    # Validate identity and duplicate constraints even when the caller only verifies hashes.
    report = score_run(manifest, cases, events)
    return manifest, cases, events, report


def verify_run(directory):
    manifest, cases, events, recomputed = read_run(directory)
    saved = read_json(Path(directory) / 'scores.json')
    if canonical(saved) != canonical(recomputed):
        raise BenchError('Saved scores differ from independent replay')
    return {'valid': True, 'events': len(events), 'cases': len(cases), 'run_id': manifest['run_id'],
            'status': manifest['status'], 'note': 'Checks integrity and scoring consistency; hashes are not a signature or proof of honest adapter behavior.'}
