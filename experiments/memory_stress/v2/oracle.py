"""Replay raw evidence, selection constraints and controlled feedback transfer."""
import copy
import itertools

from experiments.memory_stress import oracle as v1
from .environment import check_component, artifact_spec


def normalized(events):
    rows = []
    for row in events:
        item = dict(row, kind='assert') if row['kind'] == 'feedback' else row
        rows.append(item)
    return rows


def validate_world(world):
    v1.validate_world(dict(world, events=normalized(world['events'])))
    for row in world['events']:
        if row['kind'] == 'feedback':
            actual = check_component(row['fields'], row['interaction']['submitted'])
            if {k: v for k, v in actual.items() if k != 'required'} != row['interaction']:
                raise ValueError('Tool feedback does not match the simulated validation')
    for query in world['queries']:
        if query.get('mode') in ('selection', 'transfer'):
            keys = set(query['choices'])
            if set(query['required_fields']) & set(query['provided']) or set(query['required_fields']) | set(query['provided']) != keys:
                raise ValueError('Historical and current constraints must partition the rules')
            if len({o['id'] for o in query['options']}) != len(query['options']):
                raise ValueError('Duplicate option ID')
            if any(set(o['values']) != keys or any(o['values'][k] not in query['choices'][k] for k in keys) for o in query['options']):
                raise ValueError('Invalid candidate option')
    return world


def resolve(world, query, events=None, policy='complete'):
    source = world['events'] if events is None else events
    if query.get('mode', 'lookup') == 'lookup':
        return v1.resolve(dict(world, events=normalized(source)), query, policy=policy)
    if policy == 'recent_window': source = source[-12:]
    values = dict(query['provided']); choices, groups, fixed, nodes = [], [], set(), []
    for key in query['required_fields']:
        probe = {'subject': query['subject'], 'path': [{'scope': query['path'][0]['scope'], 'key': key}]}
        state = v1.resolve(dict(world, events=normalized(source)), probe, policy=policy)
        nodes.extend(state['read_nodes'])
        if state['value'] is None:
            return {'value': None, 'support_sets': [[r['id'] for r in source]], 'groups': [], 'read_nodes': nodes}
        values[key] = state['value']; choices.append(state['support_sets']); groups.extend(state['groups'])
    matches = [o for o in query['options'] if o['values'] == values]
    value = sorted(values.values()) if query['goal'] == 'files' else matches[0]['id'] if len(matches) == 1 else None
    if policy != 'complete':
        # Fault strategies supply values only; they make no sufficient-evidence claim.
        return {'value':value,'support_sets':[],'groups':[],'read_nodes':nodes,'diagnostic_only':True}
    supports = []
    for combination in itertools.product(*choices):
        ids = set(itertools.chain.from_iterable(combination))
        supports.append([r['id'] for r in source if r['id'] in ids])
        if len(supports) > 64: raise ValueError('Too many equivalent evidence sets')
    return {'value': value, 'support_sets': supports if value is not None else [[r['id'] for r in source]],
            'groups': list({tuple(g): g for g in groups}.values()), 'read_nodes': nodes}


def answers(world, events=None, policy='complete'):
    return {q['id']: resolve(world, q, events, policy)['value'] for q in world['queries']}


def evidence(world, query):
    state = resolve(world, query)
    required = []
    for group in state['groups']:
        remaining = [r for r in world['events'] if r['id'] not in group]
        if resolve(world, query, remaining)['value'] != state['value']: required.append(group)
    supports = []
    for ids in state['support_sets']:
        if resolve(world, query, [r for r in world['events'] if r['id'] in ids])['value'] != state['value']:
            raise AssertionError('Insufficient raw Oracle evidence')
        supports.append(ids)
    known = state['value'] is not None
    return {'answer': state['value'], 'sufficient_sets': supports, 'required_groups': required,
            'required_group_count': len(required), 'positive_evidence_observable': known,
            'negative_policy': 'Unknown probes receive full raw history; no compact negative recall claim.',
            'explanatory_ids': sorted(set(supports[0])-set(itertools.chain.from_iterable(required))) if known else []}


def oracle_records(world, query):
    selected = set(evidence(world, query)['sufficient_sets'][0])
    return [copy.deepcopy(r) for r in world['events'] if r['id'] in selected]


def without_query_history(world):
    nodes = set()
    for query in world['queries']: nodes.update(tuple(n) for n in resolve(world, query)['read_nodes'])
    rows = []
    for row in world['events']:
        if (row['subject'], row['scope']) in nodes:
            rows.append({'id': row['id'], 'kind': 'discussion', 'status': 'accepted', 'subject': 'ADMIN-'+row['id'],
                         'scope': 'administration', 'fields': {'note': 'neutral-replacement-'+row['id']}})
        else: rows.append(copy.deepcopy(row))
    if any(v is not None for v in answers(world, rows).values()): raise AssertionError('Target facts remain in no_history')
    return rows


def delivery_spec(world, query):
    if query.get('mode') != 'transfer': return None
    value = resolve(world, query)['value']
    if value is None: return None
    option = next(o for o in query['options'] if o['id'] == value)
    return artifact_spec(query, option)
