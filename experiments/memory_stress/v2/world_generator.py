"""Four families, four controlled load labels, 160 independent offline histories."""
import copy
import itertools
import random

from experiments.memory_stress.world_generator import opaque, VARIANTS
from .environment import COMPONENTS, check_component

FAMILIES = ('multihop', 'updates', 'collections', 'feedback')
TIERS = ('low', 'medium', 'high', 'extreme')
HOPS = (1, 2, 4, 6)
UPDATES = (1, 3, 6, 10)
CONSTRAINTS = (2, 4, 6, 8)
FEEDBACK_RULES = (1, 2, 4, 6)
HISTORY_SLOTS = 128


class Builder:
    def __init__(self, seed):
        self.seed, self.rng, self.counter = seed, random.Random(seed), 0
        self.slots = [None]*HISTORY_SLOTS

    def token(self, prefix):
        self.counter += 1
        return prefix+'-'+opaque('v2', self.seed, self.counter)[:10]

    def event(self, subject, scope, fields, status='accepted', checkpoint=None):
        row = {'id': self.token('E'), 'kind': 'assert', 'subject': subject, 'scope': scope,
               'status': status, 'label': 'v'+str(self.rng.randrange(1, 1000)), 'fields': fields}
        if checkpoint is not None: row['checkpoint'] = checkpoint
        return row

    def feedback(self, client, required, submitted, status='accepted', checkpoint=None):
        row = self.event(client, 'experience', required, status, checkpoint)
        row['kind'] = 'feedback'
        # No duplicate required value in the payload: fields ARE the tool's required output.
        result = check_component(required, submitted)
        row['interaction'] = {k: v for k, v in result.items() if k != 'required'}
        return row

    def cancel(self, row, fields):
        result = self.event(row['subject'], row['scope'], {})
        result.update(kind='cancel', target_id=row['id'], fields=fields)
        return result

    def place(self, position, row):
        if self.slots[position] is not None: raise ValueError('Occupied history slot')
        self.slots[position] = row

    def spread(self, rows, end):
        rows = list(rows); self.rng.shuffle(rows)
        for position, row in zip(sorted(self.rng.sample(range(end), len(rows))), rows):
            self.place(position, row)

    def finish(self):
        for i, row in enumerate(self.slots):
            if row is None:
                self.slots[i] = {'id': self.token('E'), 'kind': 'discussion', 'status': 'accepted',
                                 'subject': self.token('ADMIN'), 'scope': 'administration',
                                 'fields': {'note': 'neutral-'+self.token('NOTE')}}
        return self.slots


def direct(subject, scope, key, role, at=None):
    q = {'role': role, 'subject': subject, 'path': [{'scope': scope, 'key': key}], 'goal': key, 'mode': 'lookup'}
    if at is not None: q['at'] = at
    return q


def build_options(builder, choices, values):
    """A balanced full product independent of the selected facts; no special hub."""
    keys = list(choices)
    vectors = [dict(zip(keys, vector)) for vector in itertools.product(*(choices[k] for k in keys))]
    options = [{'id': builder.token('OPTION'), 'values': vector} for vector in vectors]
    builder.rng.shuffle(options)
    return options


def generate_world(family, tier, seed, split='development'):
    if family not in FAMILIES or tier not in TIERS or split not in ('development', 'reserved'):
        raise ValueError('Unknown selection')
    b = Builder(seed); level = TIERS.index(tier)
    target, other, ghost, checkpoint = [b.token(prefix) for prefix in ('PROJECT', 'PROJECT', 'PROJECT', 'CP')]
    if family == 'multihop':
        count = HOPS[level]
        keys = {1: ['directory'], 2: ['profile', 'directory'], 4: ['customer', 'profile', 'template', 'directory'],
                6: ['customer', 'profile', 'template', 'bundle', 'route', 'directory']}[count]
        projects = [target, other, b.token('PROJECT'), b.token('PROJECT')]
        foundations, roots, first = [], [], []
        for project in projects:
            nodes = [project]+[b.token('ENTITY') for _ in range(count-1)]
            values = nodes[1:]+['exports/'+b.token('OUT')]
            first.append(values[0]); roots.append(b.event(project, 'client', {keys[0]: values[0]}))
            foundations.extend(b.event(nodes[i], 'registry', {keys[i]: values[i]}) for i in range(1, count))
        b.spread(foundations, 70)
        for position, row in zip((76, 80, 84, 88), roots): b.place(position, row)
        roots[0]['checkpoint'] = checkpoint
        effective = b.event(target, 'client', dict(roots[0]['fields'])); b.place(96, effective)
        alias = b.token('ALIAS'); b.place(104, b.event(alias, 'naming', {'ref': target}))
        draft = b.event(target, 'client', {keys[0]: first[1]}, 'draft'); b.place(112, draft)
        path = [{'scope': 'client' if i == 0 else 'registry', 'key': k} for i, k in enumerate(keys)]
        queries = [{'role': 'primary', 'subject': target, 'path': path, 'goal': 'directory', 'mode': 'lookup'},
                   {'role': 'alias', 'subject': alias, 'path': [{'scope': 'naming', 'key': 'ref'}]+path, 'goal': 'directory', 'mode': 'lookup'},
                   {'role': 'historical', 'subject': target, 'path': path, 'goal': 'directory', 'at': checkpoint, 'mode': 'lookup'},
                   {'role': 'other_scope', 'subject': other, 'path': path, 'goal': 'directory', 'mode': 'lookup'},
                   direct(target, 'client', keys[0], 'direct'),
                   {'role': 'abstention', 'subject': ghost, 'path': path, 'goal': 'directory', 'mode': 'lookup'}]
        field, alternative = keys[0], first[1]
        loads = {'hop_count': count, 'candidate_chains': 4}
    elif family == 'updates':
        count = UPDATES[level]
        numbers = b.rng.sample(range(101, 998), max(UPDATES)+5)
        original, revised = numbers[0], numbers[1:1+count]
        temporary, proposed, prod_old, prod_current = numbers[-4:]
        foundations = []
        for number in numbers:
            profile, template = b.token('PROFILE'), b.token('TEMPLATE')
            foundations.extend([b.event(str(number), 'registry', {'profile': profile}), b.event(profile, 'registry', {'template': template}),
                                b.event(template, 'registry', {'directory': 'exports/'+b.token('OUT')})])
        b.spread(foundations, 60)
        b.place(72, b.event(target, 'test', {'d1': original, 'branch': b.token('BRANCH')}, checkpoint=checkpoint))
        b.place(73, b.event(target, 'production', {'d1': prod_old}))
        for i, number in enumerate(revised):
            effective = b.event(target, 'test', {'d1': number}); b.place(93-2*(count-1-i), effective)
        temp = b.event(target, 'test', {'d1': temporary, 'branch': b.token('BRANCH')}); b.place(100, temp)
        b.place(102, b.cancel(temp, ['d1']))
        b.place(106, b.event(target, 'production', {'d1': prod_current}))
        draft = b.event(target, 'test', {'d1': proposed}, 'draft'); b.place(112, draft)
        path = [{'scope': 'test', 'key': 'd1'}]+[{'scope': 'registry', 'key': k} for k in ('profile', 'template', 'directory')]
        queries = [{'role': 'primary', 'subject': target, 'path': path, 'goal': 'directory', 'mode': 'lookup'},
                   direct(target, 'test', 'd1', 'current'), direct(target, 'test', 'branch', 'preservation'),
                   direct(target, 'test', 'd1', 'historical', checkpoint), direct(target, 'production', 'd1', 'other_scope'),
                   direct(ghost, 'test', 'd1', 'abstention')]
        field, alternative = 'd1', proposed
        loads = {'same_field_updates': count, 'downstream_depth': 3, 'registry_keys': len(numbers), 'scopes': 2, 'selective_cancels': 1,
                 'last_effective_update_position':94,'inputs_after_effective_update':34}
    elif family == 'collections':
        count = CONSTRAINTS[level]
        choices = {'pair'+str(i): [b.token('FILE'), b.token('FILE')] for i in range(8)}
        selected = {k: b.rng.choice(v) for k, v in choices.items()}
        opposite = {k: next(v for v in choices[k] if v != value) for k, value in selected.items()}
        b.place(4, b.event(target, 'client', opposite, checkpoint=checkpoint))
        b.place(6, b.event(target, 'production', opposite))
        rows = [b.event(target, 'client', {k: v}) for k, v in selected.items()]
        for position, row in zip(sorted(b.rng.sample(range(20, 88), 8)), rows): b.place(position, row)
        temp = b.event(target, 'client', {'pair0': opposite['pair0']}); b.place(96, temp)
        b.place(98, b.cancel(temp, ['pair0']))
        effective = next(r for r in rows if 'pair0' in r['fields'])
        draft = b.event(target, 'client', {'pair0': opposite['pair0']}, 'draft'); b.place(112, draft)
        options = build_options(b, choices, selected)
        keys = list(choices)
        common = {'subject': target, 'path': [{'scope': 'client', 'key': 'pair0'}], 'mode': 'selection',
                  'required_fields': keys[:count], 'provided': {k: selected[k] for k in keys[count:]},
                  'choices': choices, 'options': options}
        queries = [dict(common, role='primary', goal='plan'), dict(common, role='files', goal='files'),
                   direct(target, 'client', 'pair0', 'current'), direct(target, 'client', 'pair0', 'historical', checkpoint),
                   direct(target, 'production', 'pair0', 'other_scope'), dict(common, subject=ghost, role='abstention', goal='plan')]
        field, alternative = 'pair0', opposite['pair0']
        loads = {'historical_constraints': count, 'current_constraints': 8-count, 'candidate_plans': 256,
                 'file_pairs': 8, 'allowed_file_count': 8, 'selective_cancels': 1}
    else:
        count = FEEDBACK_RULES[level]
        clients = [target, other]+[b.token('CLIENT') for _ in range(6)]
        choices = {k: [('delivery/'+b.token('DIR')) if k == 'directory' else b.token(k.upper()) for _ in range(2)] for k in COMPONENTS}
        values = {k: b.rng.choice(v) for k, v in choices.items()}
        opposite = {k: next(v for v in choices[k] if v != value) for k, value in values.items()}
        units = []
        for client in clients:
            for key in COMPONENTS:
                value = opposite[key] if client == target and key == 'directory' else values[key] if client == target else (('delivery/'+b.token('DIR')) if key == 'directory' else b.token(key.upper()))
                bad = b.feedback(client, {key: value}, 'invalid-'+b.token('TRY'))
                good = b.feedback(client, {key: value}, value, checkpoint=checkpoint if client == target and key == 'directory' else None)
                units.append((bad, good))
        b.rng.shuffle(units)
        for i, (bad, good) in enumerate(units): b.place(2*i, bad); b.place(2*i+1, good)
        b.place(100, b.feedback(target, {'directory': values['directory']}, 'invalid-'+b.token('TRY')))
        effective = b.feedback(target, {'directory': values['directory']}, 'invalid-'+b.token('TRY')); b.place(102, effective)
        draft = b.feedback(target, {'directory': opposite['directory']}, 'invalid-'+b.token('TRY'), 'draft'); b.place(112, draft)
        options = build_options(b, choices, values)
        common = {'subject': target, 'path': [{'scope': 'experience', 'key': 'directory'}], 'mode': 'transfer',
                  'required_fields': list(COMPONENTS[:count]), 'provided': {k: values[k] for k in COMPONENTS[count:]},
                  'choices': choices, 'options': options, 'project': b.token('NEWPROJECT')}
        queries = [dict(common, role='primary', goal='recipe'), direct(target, 'experience', 'directory', 'current'),
                   direct(target, 'experience', 'directory', 'historical', checkpoint), direct(target, 'experience', 'template', 'preservation'),
                   direct(other, 'experience', 'directory', 'other_scope'), dict(common, subject=ghost, role='abstention', goal='recipe')]
        field, alternative = 'directory', opposite['directory']
        loads = {'historical_rules': count, 'current_rules': 6-count, 'candidate_recipes': 64, 'clients': 8,
                 'feedback_interactions': 99, 'evaluation_track': 'controlled_transfer'}
    b.rng.shuffle(queries)
    for i, query in enumerate(queries): query['id'] = 'q'+str(i+1).zfill(2)
    sid = opaque('stress-v2', family, tier, seed)
    return {'schema_version': 'stress-world-0.2', 'scenario_id': sid, 'split_group': sid, 'split': split,
            'family': family, 'tier': tier, 'seed': seed, 'events': b.finish(), 'queries': queries,
            'loads': dict(loads, history_slots=HISTORY_SLOTS), 'variant': 'base',
            'edit_plan': {'effective_id': effective['id'], 'draft_id': draft['id'], 'field': field, 'alternative_value': alternative}}


def phase_two_worlds(seed=20261100):
    return [generate_world(family, tier, seed+10000*f+100*t+i, 'development' if i < 8 else 'reserved')
            for f, family in enumerate(FAMILIES) for t, tier in enumerate(TIERS) for i in range(10)]


def revised_phase_one_worlds(seed=20261013):
    """Versioned recency correction; retain the original worlds and their grouping."""
    from experiments.memory_stress.world_generator import development_worlds
    worlds = development_worlds(seed)
    for world in worlds:
        world.update(schema_version='stress-world-0.1.1', contract='memory-stress-0.1.1',
                     source_revision='memory-stress-0.1')
        if world['family'] != 'updates': continue
        primary = next(q for q in world['queries'] if q['role'] == 'primary')
        rows = [(i,r) for i,r in enumerate(world['events']) if r['kind'] == 'assert' and r['subject'] == primary['subject']
                and r['scope'] == 'test' and r['status'] == 'accepted' and set(r['fields']) == {'d1'}]
        count = world['loads']['same_field_updates']
        if len(rows) != count: raise ValueError('Unexpected original update layout')
        for position,_ in rows:
            world['events'][position] = {'id':'E-'+opaque('revision-011',world['scenario_id'],position), 'kind':'discussion',
                'status':'accepted','subject':'ADMIN-'+opaque('revision-011-admin',world['scenario_id'],position),
                'scope':'administration','fields':{'note':'neutral-recency-control'}}
        for i,(_,row) in enumerate(rows): world['events'][49-2*(count-1-i)] = row
        world['loads'].update(last_effective_update_position=50, inputs_after_effective_update=14)
    return worlds


def transform(world, variant):
    if variant not in VARIANTS: raise ValueError('Unknown variant')
    result = copy.deepcopy(world); result['variant'] = variant
    by_id = {r['id']: r for r in result['events']}; plan = result['edit_plan']
    if variant == 'fact_edit': by_id[plan['effective_id']]['fields'][plan['field']] = plan['alternative_value']
    elif variant == 'approval_swap':
        by_id[plan['effective_id']]['status'] = 'draft'; by_id[plan['draft_id']]['status'] = 'accepted'
    elif variant == 'label_renumber':
        for i, row in enumerate(result['events']):
            if 'label' in row: row['label'] = 'v'+str(10000-i*17)
    elif variant == 'irrelevant_edit':
        row = next(r for r in result['events'] if r['kind'] == 'discussion')
        row['fields']['note'] = 'unrelated-'+opaque(result['scenario_id'], variant)
    return result
