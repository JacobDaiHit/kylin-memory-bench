"""Deterministic simulated delivery tool. Rules are benchmark data, not OS rules."""
import hashlib
from pathlib import Path

from kylin_memory_bench.common import MAX_FILE_BYTES, canonical, contained, strict_json, write_text

COMPONENTS = ('directory', 'template', 'profile', 'revision', 'redaction', 'bundle')


def check_component(required, submitted):
    """A tool rejection may disclose its rule; this is authorized learning feedback."""
    if len(required) != 1:
        raise ValueError('Component validation takes one rule')
    key, value = next(iter(required.items()))
    return {'tool': 'simulated_delivery_validator', 'component': key,
            'submitted': submitted, 'result': 'accepted' if submitted == value else 'rejected',
            'required': dict(required)}


def artifact_spec(query, option):
    values = option['values']
    if set(values) != set(COMPONENTS):
        raise ValueError('Incomplete delivery option')
    relative = values['directory']+'/'+query['project']+'.json'
    # Validate without depending on the caller's working directory.
    from kylin_memory_bench.common import relative_path
    relative_path(relative)
    content = {k: values[k] for k in COMPONENTS[1:]}
    return {'path': relative, 'content': content, 'text': canonical(content)+'\n'}


def write_delivery(workspace, spec):
    path = contained(workspace, spec['path'])
    write_text(path, spec.get('text', canonical(spec['content'])+'\n'))
    return {'name': 'write_file', 'arguments': {'path': spec['path']}, 'status': 'success'}


def inspect_delivery(workspace, spec):
    """Read an actual bounded file; never manufacture an artifact during inspection."""
    try:
        path = contained(workspace, spec['path'])
        if not path.is_file():
            return {'exists': False}
        raw = path.read_bytes() if path.stat().st_size <= MAX_FILE_BYTES else None
        if raw is None:
            return {'exists': True, 'error': 'oversized'}
        return {'exists': True, 'text': raw.decode('utf-8'), 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()}
    except (ValueError, OSError, UnicodeError):
        return {'exists': None, 'error': 'unobservable_or_invalid_file'}


def grade_delivery(artifact, spec):
    if artifact is None or artifact.get('error') or artifact.get('exists') is None:
        return {'status': 'unknown', 'content_observed': False, 'content_correct': None,
                'file_success': False, 'format_correct': None}
    if not artifact.get('exists'):
        return {'status': 'fail', 'content_observed': False, 'content_correct': None,
                'file_success': False, 'format_correct': None, 'reason': 'missing_file'}
    try:
        parsed = strict_json(artifact['text'])
    except (ValueError, TypeError):
        return {'status': 'fail', 'content_observed': False, 'content_correct': None,
                'file_success': False, 'format_correct': False, 'reason': 'invalid_json_file'}
    from kylin_memory_bench.scoring import json_equal
    content_ok = isinstance(parsed, dict) and all(json_equal(parsed.get(k), v) for k, v in spec['content'].items())
    # Exact keys, UTF-8 without BOM, and exactly one final LF. Key order is free.
    text = artifact['text']
    format_ok = isinstance(parsed, dict) and set(parsed) == set(spec['content']) and text.endswith('\n') and not text.endswith('\n\n') and '\r' not in text and not text.startswith('\ufeff')
    return {'status': 'pass' if content_ok and format_ok else 'fail', 'content_observed': True,
            'content_correct': content_ok, 'format_correct': format_ok, 'file_success': content_ok and format_ok}


def tool_feedback(required, query, artifact):
    """Actual file acceptance plus an explicit simulated contract on rejection."""
    spec = artifact_spec(query, {'values': required})
    verdict = grade_delivery(artifact, spec)
    return {'tool': 'simulated_delivery_validator', 'result': 'accepted' if verdict['file_success'] else 'rejected',
            'required': dict(required), 'verdict': verdict}
