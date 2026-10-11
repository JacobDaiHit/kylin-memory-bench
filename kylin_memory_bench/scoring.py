"""Deterministic evidence scoring with explicit unknowns and conservative bounds."""
import re
from collections import Counter
from statistics import mean, pstdev

from .common import BenchError, DIMENSIONS, canonical, digest, json_pointer, strict_json


def parse_answer(text):
    text = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    return strict_json(text)


def subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and subset(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(subset(x, y) for x, y in zip(expected, actual))
    return type(expected) is type(actual) and expected == actual


def evaluate(check, event):
    result = {'check_id': check['id'], 'source': check['source'], 'weight': check.get('weight', 1),
              'status': 'unknown', 'category': 'insufficient_evidence', 'reason': '', 'evidence_id': None}
    if not event:
        result['reason'] = 'No evidence event was recorded for this step.'
        return result
    result['evidence_id'] = event['event_id']
    if event.get('error'):
        result.update(status='error', category='execution_error', reason=event['error'])
        return result
    source, op = check['source'], check['op']
    response = event.get('response') or {}
    observed, complete = None, True
    if source == 'response':
        if 'text' not in response:
            result['reason'] = 'Adapter supplied no response text.'
            return result
        observed = response['text']
    elif source == 'memory':
        memory = response.get('memory')
        if memory is None:
            result['reason'] = 'Memory store is not observable through this adapter.'
            return result
        observed, complete = memory['text'], memory['complete']
    elif source == 'actions':
        observed = response.get('actions')
        if observed is None:
            result['reason'] = 'No structured action trace is available.'
            return result
    else:
        artifact = event.get('artifacts', {}).get(check['path'])
        if artifact is None or artifact.get('error'):
            result['reason'] = 'Artifact was not observed or could not be read safely.'
            return result
        if op in ('exists', 'absent'):
            passed = artifact['exists'] == (op == 'exists')
            return finish(result, check, passed, 'File existence verified in the case workspace.')
        if not artifact['exists']:
            return finish(result, check, False, 'Required artifact does not exist.')
        observed = artifact['text']
    if check.get('pointer'):
        try:
            observed = json_pointer(parse_answer(observed), check['pointer'])
        except (BenchError, KeyError, IndexError, TypeError):
            result.update(status='fail', category='invalid_response',
                          reason='Evidence is not the requested structured JSON, or its field is missing.')
            return result
    expected = check.get('value')
    if op == 'equals':
        passed = type(observed) is type(expected) and observed == expected
    elif op == 'one_of':
        passed = any(type(observed) is type(value) and observed == value for value in expected)
    elif op in ('contains', 'excludes'):
        if not isinstance(observed, str):
            return finish(result, check, False, 'Text matcher received non-text evidence.')
        found = expected in observed
        if source == 'memory' and not complete and not found:
            result['reason'] = 'Value absent from a partial snapshot; absence cannot establish store contents.'
            return result
        passed = found if op == 'contains' else not found
    elif op == 'json_subset':
        if source == 'actions':
            passed = any(action.get('status') != 'failed' and subset(expected, action) for action in observed)
        else:
            try:
                actual = parse_answer(observed) if isinstance(observed, str) else observed
                passed = subset(expected, actual)
            except BenchError:
                passed = False
    elif op == 'exists':
        passed = observed is not None
    else:
        passed = not observed
    result = finish(result, check, passed, f'Deterministic {op} check on {source} evidence.')
    if not passed and source == 'response' and observed is None and expected is not None:
        result['category'] = 'omission'
    elif not passed and source == 'response' and result['category'] == 'omission':
        result['category'] = 'confusion'
    return result


def finish(result, check, passed, reason):
    result.update(status='pass' if passed else 'fail', category='correct' if passed else check['failure'], reason=reason)
    return result


def metric(checks):
    total = sum(c['weight'] for c in checks)
    passed = sum(c['weight'] for c in checks if c['status'] == 'pass')
    observed = sum(c['weight'] for c in checks if c['status'] in ('pass', 'fail'))
    return {'score': round(passed / observed, 6) if observed else None,
            'coverage': round(observed / total, 6) if total else 0,
            'lower_bound': round(passed / total, 6) if total else None,
            'upper_bound': round((passed + total - observed) / total, 6) if total else None,
            'check_count': len(checks), 'statuses': dict(Counter(c['status'] for c in checks))}


def aggregate(items):
    """Equal case/trial weight inside each dimension; never reward a missing dimension."""
    def avg(key):
        values = [item[key] for item in items if item[key] is not None]
        return round(mean(values), 6) if values else None
    return {key: avg(key) for key in ('score', 'coverage', 'lower_bound', 'upper_bound')}


def score_run(manifest, cases, events):
    indexed = {}
    expected_steps = {(c['id'], s['id']) for c in cases for s in c['steps']}
    agent_ids = {a['id'] for a in manifest['agents']}
    for event in events:
        key = (event['agent_id'], event['trial'], event['case_id'], event['step_id'])
        if key in indexed:
            raise BenchError('Duplicate evidence step: ' + str(key))
        if event['agent_id'] not in agent_ids or (event['case_id'], event['step_id']) not in expected_steps:
            raise BenchError('Evidence does not belong to the manifest/dataset')
        if type(event['trial']) is not int or not 0 <= event['trial'] < manifest['repeats']:
            raise BenchError('Invalid evidence trial')
        indexed[key] = event
    agents = []
    for agent in manifest['agents']:
        rows, dimensions = [], {}
        for trial in range(manifest['repeats']):
            for case in cases:
                checks = []
                for step in case['steps']:
                    event = indexed.get((agent['id'], trial, case['id'], step['id']))
                    for check in step.get('checks', []):
                        checks.append({'step_id': step['id'], **evaluate(check, event)})
                rows.append({'case_id': case['id'], 'title': case['title'], 'dimension': case['dimension'],
                             'trial': trial, 'checks': checks, **metric(checks)})
        for dimension in DIMENSIONS:
            selected = [r for r in rows if r['dimension'] == dimension]
            dimensions[dimension] = {**aggregate(selected), 'cases': len(selected)}
        trial_scores = []
        for trial in range(manifest['repeats']):
            per_dim = [aggregate([r for r in rows if r['trial'] == trial and r['dimension'] == d]) for d in DIMENSIONS]
            trial_scores.append(aggregate(per_dim)['lower_bound'])
        valid_scores = [s for s in trial_scores if s is not None]
        agent_events = [e for e in events if e['agent_id'] == agent['id']]
        latencies = sorted(e.get('duration_ms', 0) for e in agent_events)
        checks = [c for row in rows for c in row['checks']]
        agents.append({'id': agent['id'], 'label': agent.get('label', agent['id']), 'kind': agent['kind'],
                       'is_baseline': agent['kind'] == 'baseline', 'dimensions': dimensions,
                       'overall': aggregate(list(dimensions.values())), 'evaluated_dimensions': sum(d['cases'] > 0 for d in dimensions.values()),
                       'categories': dict(Counter(c['category'] for c in checks)), 'cases': rows,
                       'stability': {'repeats': manifest['repeats'], 'trial_lower_bounds': trial_scores,
                                     'stddev': round(pstdev(valid_scores), 6) if len(valid_scores) > 1 else None},
                       'runtime': {'steps': len(agent_events), 'errors': sum(bool(e.get('error')) for e in agent_events),
                                   'latency_p50_ms': latencies[len(latencies)//2] if latencies else None,
                                   'latency_p95_ms': latencies[min(len(latencies)-1, int(len(latencies)*0.95))] if latencies else None}})
    return {'schema_version': '1.0', 'scorer_version': '1.0', 'run_id': manifest['run_id'],
            'dataset_sha256': digest(cases), 'run_status': manifest['status'], 'agents': agents,
            'method': 'Equal dimension macro average of equal case/trial weighted-check scores; unknown/error remain in coverage bounds.'}
