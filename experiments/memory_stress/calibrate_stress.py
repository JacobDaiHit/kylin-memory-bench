"""Offline design checks and one-answer grading, separate from native ability claims."""
import json
import random
from collections import Counter, defaultdict

from experiments.math_memory.memory_v31 import extract_answer
from .oracle import answers, evidence, resolve, validate_world
from .render_history import EXPRESSIONS, parse_event, render_event
from .world_generator import VARIANTS, transform


def grade(expected, text, error=None):
    parsed, mode, conforms = None, None, False
    reason = None
    if not error:
        try:
            parsed, mode, conforms = extract_answer(text)
        except (ValueError, TypeError, RecursionError) as exc:
            reason = str(exc)
    actual = parsed.get('answer') if parsed is not None else None
    valid = parsed is not None and 'answer' in parsed and type(actual) in (str, int, type(None))
    correct = valid and type(expected) is type(actual) and expected == actual
    # Integer spelling is a frozen content alias. A string still fails strict output typing.
    if valid and type(expected) is int and isinstance(actual, str) and len(actual)<=32:
        try:
            correct = str(int(actual)) == actual.strip() and int(actual) == expected
        except ValueError:
            correct = False
    status = 'error' if error else 'unknown' if not valid else 'pass' if correct else 'fail'
    format_ok = valid and conforms and set(parsed)=={'answer'} and type(actual) is type(expected)
    return {'status':status, 'correct':correct, 'observed':status in ('pass','fail'),
            'format_status':'error' if error else 'pass' if format_ok else 'fail',
            'content_task_success':status=='pass','strict_task_success':status=='pass' and format_ok,
            'error':error,'parse_error':reason,'envelope':mode}


def evidence_match(proof, observed_ids=None, reliable=False, complete=False):
    if not reliable or not complete or observed_ids is None or not proof['positive_evidence_observable']:
        return {'status':'unknown','sufficient':None,'required_group_recall':None}
    observed = set(observed_ids)
    groups = proof['required_groups']
    return {'status':'observed','sufficient':any(set(ids)<=observed for ids in proof['sufficient_sets']),
            'required_group_recall':sum(bool(observed.intersection(group)) for group in groups)/len(groups) if groups else None}


def quality(worlds):
    if len(worlds)!=30 or len({w['scenario_id'] for w in worlds})!=30 or len({w['seed'] for w in worlds})!=30:
        raise ValueError('Expected thirty distinct development histories')
    summary, proofs, pairs, strategies = [], {}, [], []
    for world in worlds:
        validate_world(world)
        for expression in EXPRESSIONS:
            for row in world['events']:
                if parse_event(render_event(row,expression),expression)!=row:
                    raise AssertionError('Expression changed an event')
        original = answers(world)
        q = next(q for q in world['queries'] if q['role']=='primary')
        proof = evidence(world,q)
        proofs[world['scenario_id']] = {q['id']:evidence(world,q) for q in world['queries']}
        summary.append({'scenario_id':world['scenario_id'],'family':world['family'],'tier':world['tier'],
                        'history_slots':len(world['events']),'primary_required_evidence_groups':proof['required_group_count'],
                        'primary_sufficient_raw_records':len(proof['sufficient_sets'][0]),'loads':world['loads']})
        for variant in VARIANTS[1:]:
            edited = transform(world,variant);validate_world(edited)
            changed = answers(edited)
            changing = variant in ('fact_edit','approval_swap')
            if (original[q['id']]!=changed[q['id']])!=changing:
                raise AssertionError('Paired primary answer violates its frozen relation')
            if not changing and changed!=original:
                raise AssertionError('Invariance pair changed an answer')
            pairs.append({'scenario_id':world['scenario_id'],'variant':variant,
                          'relation':'answer_changes' if changing else 'answer_invariant',
                          'base':original,'edited':changed,'split_group':world['split_group']})
        for policy in ('complete','first_state','ignore_cancel','scope_blind','accept_draft','recent_window'):
            values = answers(world,policy=policy)
            strategies.append({'scenario_id':world['scenario_id'],'family':world['family'],'tier':world['tier'],
                               'policy':policy,'primary_correct':values[q['id']]==original[q['id']],
                               'all_queries_correct':values==original})
    return {'kind':'offline_generation_and_fault_strategy_checks','paid_calls':0,'passed':True,
            'history_count':30,'expression_roundtrips':30*64*3,'paired_relations_checked':len(pairs),
            'worlds':summary,'proofs':proofs,'pairs':pairs,'strategies':strategies,
            'claim_limit':'Grammar and programmed strategy checks, not same-LLM baselines, independent human review or native ability/difficulty.'}


def grouped_summary(rows, bootstrap_seed=997):
    groups = defaultdict(list)
    for row in rows:
        key = tuple(row[k] for k in ('agent','condition','expression','variant','family','tier','query_role'))
        groups[key].append(row)
    summaries=[]
    for key, selected in sorted(groups.items()):
        scenes=defaultdict(list)
        for row in selected:scenes[row['scenario_id']].append(row)
        rates=[sum(r['grade']['content_task_success'] for r in values)/len(values) for values in scenes.values()]
        rng=random.Random(bootstrap_seed)
        draws=sorted(sum(rng.choice(rates) for _ in rates)/len(rates) for _ in range(500))
        summaries.append({**dict(zip(('agent','condition','expression','variant','family','tier','query_role'),key)),
                          'history_count':len(scenes),'scheduled_final_slots':len(selected),
                          'effective_observation_rate':sum(r['grade']['observed'] for r in selected)/len(selected),
                          'status_counts':dict(Counter(r['grade']['status'] for r in selected)),
                          'format_conformance_rate':sum(r['grade']['format_status']=='pass' for r in selected)/len(selected),
                          'content_success_history_macro':sum(rates)/len(rates),
                          'strict_task_success_rate':sum(r['grade']['strict_task_success'] for r in selected)/len(selected),
                          'cluster_bootstrap_interval':[draws[12],draws[487]] if len(scenes)>=2 else None,
                          'interval_scope':'Descriptive development interval; resample whole histories, not fields.'})
    return summaries


def paired_summary(rows):
    """Both members must pass; retain unobserved members and never pool queries."""
    index = {}
    for row in rows:
        key = tuple(row[k] for k in ('agent','trial','condition','expression','scenario_id','query_id','variant'))
        if key in index:
            raise ValueError('Duplicate paired result slot')
        index[key] = row
    grouped = defaultdict(list)
    for key, base in index.items():
        if key[-1] != 'base':
            continue
        for variant in VARIANTS[1:]:
            edited = index.get(key[:-1]+(variant,))
            if edited is None:
                continue  # Variant not scheduled; absent scheduled events already have a row.
            group = tuple(base[k] for k in ('agent','condition','expression','family','tier','query_role'))+(variant,)
            grouped[group].append((base, edited))
    return [{**dict(zip(('agent','condition','expression','family','tier','query_role','variant'),key)),
             'scheduled_pairs':len(pairs),
             'pair_content_success_rate':sum(a['grade']['content_task_success'] and b['grade']['content_task_success'] for a,b in pairs)/len(pairs),
             'pair_strict_success_rate':sum(a['grade']['strict_task_success'] and b['grade']['strict_task_success'] for a,b in pairs)/len(pairs),
             'unobserved_or_error_pairs':sum(not a['grade']['observed'] or not b['grade']['observed'] for a,b in pairs)}
            for key,pairs in sorted(grouped.items())]
