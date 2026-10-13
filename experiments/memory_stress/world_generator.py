"""Generate worlds and edits, never answers, model calls or natural-language gold."""
import copy
import hashlib
import random

TIERS = ('low', 'medium', 'high')
HOPS = (1, 2, 4)
UPDATES = (1, 3, 6)
HISTORY_SLOTS = 64
VARIANTS = ('base', 'fact_edit', 'approval_swap', 'label_renumber', 'irrelevant_edit', 'paraphrase')


def opaque(*parts):
    return hashlib.sha256('/'.join(map(str, parts)).encode('utf-8')).hexdigest()[:18]


def generate_world(family, tier, seed):
    if family not in ('multihop', 'updates') or tier not in TIERS:
        raise ValueError('Unknown family or tier')
    rng = random.Random(seed)
    sid = opaque('stress', family, tier, seed)
    counter = [0]

    def token(prefix):
        counter[0] += 1
        return prefix+'-'+opaque(seed, counter[0])[:10]

    def event(subject, scope, fields, status='accepted', checkpoint=None):
        row = {'id': token('E'), 'kind': 'assert', 'subject': subject, 'scope': scope,
               'status': status, 'label': 'v'+str(rng.randrange(1, 1000)), 'fields': fields}
        if checkpoint is not None:
            row['checkpoint'] = checkpoint
        return row

    slots = [None]*HISTORY_SLOTS
    target = token('PROJECT')
    other = token('PROJECT')
    ghost = token('PROJECT')
    checkpoint = token('CP')
    edits = {}
    if family == 'multihop':
        hops = HOPS[TIERS.index(tier)]
        keys = {1: ['directory'], 2: ['profile', 'directory'],
                4: ['customer', 'profile', 'template', 'directory']}[hops]
        projects = [target, other, token('PROJECT'), token('PROJECT')]
        foundations, roots = [], []
        destinations, first_values = [], []
        for project in projects:
            destination = 'exports/client-'+token('OUT').split('-')[1]
            nodes = [project]+[token('ENTITY') for _ in range(hops-1)]
            values = nodes[1:]+[destination]
            roots.append(event(project, 'client', {keys[0]: values[0]}))
            first_values.append(values[0]);destinations.append(destination)
            foundations.extend(event(nodes[i], 'registry', {keys[i]: values[i]}) for i in range(1, hops))
        # Foundation evidence is spread through a fixed region, not adjacent to the query.
        positions = sorted(rng.sample(range(0, 44), len(foundations)))
        rng.shuffle(foundations)
        for position, row in zip(positions, foundations):
            slots[position] = row
        for position, row in zip((46, 48, 50, 52), roots):
            slots[position] = row
        roots[0]['checkpoint'] = checkpoint
        duplicate = event(target, 'client', dict(roots[0]['fields']))
        slots[54] = duplicate
        alias = token('ALIAS')
        slots[56] = event(alias, 'naming', {'ref': target})
        draft = event(target, 'client', {keys[0]: first_values[1]}, 'draft')
        slots[60] = draft
        path = [{'key': key, 'scope': 'client' if i == 0 else 'registry'} for i, key in enumerate(keys)]
        queries = [
            {'role': 'primary', 'subject': target, 'path': path, 'goal': 'directory'},
            {'role': 'alias', 'subject': alias, 'path': [{'key': 'ref', 'scope': 'naming'}]+path, 'goal': 'directory'},
            {'role': 'historical', 'subject': target, 'path': path, 'at': checkpoint, 'goal': 'directory'},
            {'role': 'other_scope', 'subject': other, 'path': path, 'goal': 'directory'},
            {'role': 'direct', 'subject': target, 'path': path[:1], 'goal': keys[0]},
            {'role': 'abstention', 'subject': ghost, 'path': path, 'goal': 'directory'},
        ]
        edits = {'effective_id': duplicate['id'], 'draft_id': draft['id'],
                 'field': keys[0], 'alternative_value': first_values[1]}
        loads = {'hop_count': hops, 'candidate_chains': 4, 'same_field_updates': 0}
    else:
        revisions = UPDATES[TIERS.index(tier)]
        # Keep the registry size fixed across update tiers; only revision load changes.
        numbers = rng.sample(range(101, 998), max(UPDATES)+5)
        original, changed = numbers[0], numbers[1:1+revisions]
        temporary, proposed, prod_old, prod_current = numbers[-4:]
        foundations = []
        for number in numbers:
            profile, template = token('PROFILE'), token('TEMPLATE')
            foundations.extend([event(str(number), 'registry', {'profile': profile}),
                                event(profile, 'registry', {'template': template}),
                                event(template, 'registry', {'directory': 'exports/client-'+token('OUT').split('-')[1]})])
        positions = sorted(rng.sample(range(0, 35), len(foundations)))
        rng.shuffle(foundations)
        for position, row in zip(positions, foundations):
            slots[position] = row
        initial_branch, preserved_branch = token('BRANCH'), token('BRANCH')
        slots[36] = event(target, 'test', {'d1': original, 'branch': initial_branch}, checkpoint=checkpoint)
        slots[37] = event(target, 'production', {'d1': prod_old, 'branch': token('BRANCH')})
        active = []
        for i, number in enumerate(changed):
            row = event(target, 'test', {'d1': number})
            active.append(row);slots[39+i*2] = row
        # Cancel only D1: the branch from the same temporary patch stays active.
        temp = event(target, 'test', {'d1': temporary, 'branch': preserved_branch})
        slots[52] = temp
        slots[54] = {'id': token('E'), 'kind': 'cancel', 'subject': target, 'scope': 'test',
                     'status': 'accepted', 'label': 'v'+str(rng.randrange(1, 1000)),
                     'target_id': temp['id'], 'fields': ['d1']}
        slots[56] = event(target, 'production', {'d1': prod_current})
        draft = event(target, 'test', {'d1': proposed}, 'draft')
        slots[60] = draft
        path = [{'scope': 'test', 'key': 'd1'}]+[{'scope': 'registry', 'key': key} for key in ('profile', 'template', 'directory')]
        queries = [
            {'role': 'primary', 'subject': target, 'path': path, 'goal': 'directory'},
            {'role': 'current', 'subject': target, 'path': path[:1], 'goal': 'd1'},
            {'role': 'preservation', 'subject': target, 'path': [{'scope': 'test', 'key': 'branch'}], 'goal': 'branch'},
            {'role': 'historical', 'subject': target, 'path': path[:1], 'at': checkpoint, 'goal': 'd1'},
            {'role': 'other_scope', 'subject': target, 'path': [{'scope': 'production', 'key': 'd1'}], 'goal': 'd1'},
            {'role': 'abstention', 'subject': ghost, 'path': path[:1], 'goal': 'd1'},
        ]
        edits = {'effective_id': active[-1]['id'], 'draft_id': draft['id'],
                 'field': 'd1', 'alternative_value': proposed}
        loads = {'hop_count': 4, 'downstream_depth': 3, 'same_field_updates': revisions,
                 'temporary_updates': 1, 'selective_cancels': 1, 'scopes': 2}
    for i, row in enumerate(slots):
        if row is None:
            slots[i] = {'id': token('E'), 'kind': 'discussion', 'status': 'accepted',
                        'subject': token('ADMIN'), 'scope': 'administration',
                        'fields': {'note': 'neutral-'+token('NOTE')}}
    rng.shuffle(queries)
    for i, query in enumerate(queries):
        query['id'] = 'q'+str(i+1).zfill(2)
    return {'schema_version': 'stress-world-0.1', 'scenario_id': sid, 'split_group': sid,
            'split': 'development', 'family': family, 'tier': tier, 'seed': seed,
            'events': slots, 'queries': queries, 'loads': dict(loads, history_slots=HISTORY_SLOTS),
            'edit_plan': edits, 'variant': 'base'}


def development_worlds(seed=20261013):
    # Each tier has distinct seeds and histories; expressions/edits remain in its group.
    return [generate_world(family, tier, seed+1000*f+100*t+i)
            for f, family in enumerate(('multihop', 'updates'))
            for t, tier in enumerate(TIERS) for i in range(5)]


def transform(world, variant):
    if variant not in VARIANTS:
        raise ValueError('Unknown paired variant')
    result = copy.deepcopy(world)
    result['variant'] = variant
    by_id = {row['id']: row for row in result['events']}
    plan = result['edit_plan']
    if variant == 'fact_edit':
        by_id[plan['effective_id']]['fields'][plan['field']] = plan['alternative_value']
    elif variant == 'approval_swap':
        by_id[plan['effective_id']]['status'] = 'draft'
        by_id[plan['draft_id']]['status'] = 'accepted'
    elif variant == 'label_renumber':
        for i, row in enumerate(result['events']):
            if 'label' in row:
                row['label'] = 'v'+str(9999-i*17)
    elif variant == 'irrelevant_edit':
        row = next(row for row in result['events'] if row['kind'] == 'discussion')
        row['fields']['note'] = 'unrelated-'+opaque(world['scenario_id'], variant)
    # Paraphrase changes only the presentation in render_history, never the world.
    return result
