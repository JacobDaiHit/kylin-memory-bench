"""Deterministic event replay, sufficient raw evidence and group-level ablations."""
import itertools
from copy import deepcopy


def validate_world(world):
    seen = {}
    for row in world['events']:
        if row['id'] in seen or row['status'] not in ('accepted', 'draft'):
            raise ValueError('Duplicate event or invalid approval status')
        if row['kind'] == 'cancel':
            target = seen.get(row['target_id'])
            if not target or target['kind'] != 'assert' or target['status'] != 'accepted':
                raise ValueError('Cancellation must reference a prior accepted assertion')
            if (target['subject'], target['scope']) != (row['subject'], row['scope']):
                raise ValueError('Cancellation cannot cross subjects or scopes')
            if not row['fields'] or not set(row['fields']) <= set(target['fields']):
                raise ValueError('Cancellation must name existing fields')
        elif row['kind'] not in ('assert', 'discussion'):
            raise ValueError('Unknown event operation')
        seen[row['id']] = row
    if len({q['id'] for q in world['queries']}) != len(world['queries']):
        raise ValueError('Duplicate question')
    return world


def _cutoff(events, checkpoint):
    if checkpoint is None:
        return events, None
    found = next((i for i, row in enumerate(events) if row.get('checkpoint') == checkpoint), None)
    return (events[:found+1], events[found]['id']) if found is not None else ([], None)


def field_decision(events, subject, scope, key, policy='complete'):
    admitted = [row for row in events if row['status'] == 'accepted' or policy == 'accept_draft']
    matches = lambda row: row['subject'] == subject and (row['scope'] == scope or policy == 'scope_blind')
    cancelled = {}
    if policy != 'ignore_cancel':
        for row in admitted:
            if row['kind'] == 'cancel' and matches(row) and key in row['fields']:
                cancelled.setdefault(row['target_id'], []).append(row['id'])
    candidates = [row for row in admitted if row['kind'] == 'assert' and matches(row) and key in row['fields']]
    active = [row for row in candidates if row['id'] not in cancelled]
    if not active:
        return None, [], [], []
    winner = active[0] if policy == 'first_state' else active[-1]
    value = winner['fields'][key]
    # All same-valued surviving sources since the last different value are valid alternatives.
    alternatives = []
    for row in reversed(active):
        if type(row['fields'][key]) is not type(value) or row['fields'][key] != value:
            break
        alternatives.append(row['id'])
    if policy == 'first_state':
        alternatives = [winner['id']]
    positions = {row['id']: i for i, row in enumerate(events)}
    defeated = [row['id'] for row in candidates if row['id'] in cancelled and positions[row['id']] > positions[winner['id']]]
    blockers = [cid for eid in defeated for cid in cancelled[eid]]
    return value, alternatives, defeated, blockers


def resolve(world, query, events=None, policy='complete'):
    source = world['events'] if events is None else events
    if policy == 'recent_window':
        source = source[-12:]
    source, checkpoint_id = _cutoff(source, query.get('at'))
    if query.get('at') and checkpoint_id is None:
        return {'value': None, 'support_sets': [list(row['id'] for row in source)], 'groups': [], 'read_nodes': []}
    choices, groups, fixed, read_nodes = [], [], set(), []
    if checkpoint_id is not None:
        fixed.add(checkpoint_id);groups.append([checkpoint_id])
    subject = query['subject']
    value = None
    for part in query['path']:
        read_nodes.append([subject, part['scope']])
        value, alternatives, defeated, blockers = field_decision(source, subject, part['scope'], part['key'], policy)
        if value is None:
            # An empty oracle context is an answerability cue. Negative probes use raw history.
            return {'value': None, 'support_sets': [[row['id'] for row in source]], 'groups': [], 'read_nodes': read_nodes}
        choices.append(alternatives);groups.append(alternatives)
        fixed.update(defeated);fixed.update(blockers)
        if blockers:
            groups.append(list(dict.fromkeys(blockers)))
        subject = str(value)
    sets = []
    for selection in itertools.product(*choices):
        ids = fixed | set(selection)
        sets.append([row['id'] for row in source if row['id'] in ids])
        if len(sets) > 64:
            raise ValueError('Too many evidence alternatives; do not silently truncate')
    unique = {tuple(group): group for group in groups}
    return {'value': value, 'support_sets': sets, 'groups': list(unique.values()), 'read_nodes': read_nodes}


def answers(world, events=None, policy='complete'):
    return {q['id']: resolve(world, q, events, policy)['value'] for q in world['queries']}


def evidence(world, query):
    resolved = resolve(world, query)
    known = resolved['value'] is not None
    required = []
    for group in resolved['groups']:
        remaining = [row for row in world['events'] if row['id'] not in group]
        value = resolve(world, query, remaining)['value']
        if value != resolved['value'] or type(value) is not type(resolved['value']):
            required.append(group)
    sufficient = []
    for support in resolved['support_sets']:
        selected = [row for row in world['events'] if row['id'] in support]
        actual = resolve(world, query, selected)['value']
        if actual != resolved['value'] or type(actual) is not type(resolved['value']):
            raise AssertionError('Raw evidence is not sufficient')
        sufficient.append(support)
    return {'answer': resolved['value'], 'sufficient_sets': sufficient, 'required_groups': required,
            'required_group_count': len(required), 'positive_evidence_observable': known,
            'negative_policy': 'Full raw history for negative probes; no compact negative evidence claim.',
            'explanatory_ids': sorted(set(sufficient[0])-set(itertools.chain.from_iterable(required))) if known else []}


def oracle_records(world, query=None):
    selected = set()
    for item in [query] if query is not None else world['queries']:
        proof = evidence(world, item)
        selected.update(proof['sufficient_sets'][0])
    return [deepcopy(row) for row in world['events'] if row['id'] in selected]


def without_query_history(world):
    nodes = set()
    for query in world['queries']:
        nodes.update(tuple(node) for node in resolve(world, query)['read_nodes'])
    result = []
    for row in world['events']:
        if (row['subject'], row['scope']) in nodes:
            result.append({'id': row['id'], 'kind': 'discussion', 'status': 'accepted',
                           'subject': 'ADMIN-'+row['id'], 'scope': 'administration',
                           'fields': {'note': 'neutral-replacement-'+row['id']}})
        else:
            result.append(deepcopy(row))
    if any(value is not None for value in answers(world, result).values()):
        raise AssertionError('No-history condition still contains target evidence')
    return result
