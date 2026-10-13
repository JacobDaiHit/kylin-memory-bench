"""Software checks, exact set metrics and separated memory/action observations."""
from collections import Counter, defaultdict

from experiments.memory_stress.calibrate_stress import grouped_summary as v1_summary, paired_summary as v1_pairs
from experiments.math_memory.memory_v31 import extract_answer
from .environment import grade_delivery
from .oracle import answers, evidence, validate_world
from .render_history import EXPRESSIONS, answer_type, parse_event, render_event
from .world_generator import FAMILIES, TIERS, VARIANTS, transform


def grade(expected, text, error=None, forbidden=(), output_type='scalar_or_set'):
    if output_type not in ('string', 'integer', 'string_set', 'scalar_or_set'):
        raise ValueError('Unknown answer schema')
    parsed, mode, conforms, problem = None, None, False, None
    if not error:
        try: parsed, mode, conforms = extract_answer(text)
        except (ValueError, TypeError, RecursionError) as exc: problem = str(exc)
    actual = parsed.get('answer') if parsed is not None else None
    is_set = isinstance(actual, list) and len(actual) <= 64 and all(isinstance(v, str) for v in actual)
    valid = parsed is not None and 'answer' in parsed and (type(actual) in (str, int, type(None)) or is_set)
    wanted = set(expected) if isinstance(expected, list) else set()
    got = set(actual) if is_set else set()
    correct = valid and (is_set and isinstance(expected, list) and wanted == got or type(actual) is type(expected) and actual == expected)
    # A canonical integer spelling remains a content alias, with format judged separately.
    if valid and type(expected) is int and isinstance(actual, str) and len(actual) <= 32:
        try: correct = str(int(actual)) == actual.strip() and int(actual) == expected
        except ValueError: correct = False
    status = 'error' if error else 'unknown' if not valid else 'pass' if correct else 'fail'
    schema_ok = actual is None or output_type == 'scalar_or_set' or (output_type == 'string' and type(actual) is str) or (output_type == 'integer' and type(actual) is int) or (output_type == 'string_set' and is_set)
    set_format = not is_set or len(got) == len(actual) and actual == sorted(actual)
    format_ok = valid and schema_ok and set_format and conforms and set(parsed) == {'answer'}
    set_observed = is_set and isinstance(expected, list)
    return {'status': status, 'observed': status in ('pass','fail'), 'correct': correct,
            'content_task_success': status == 'pass', 'strict_task_success': status == 'pass' and format_ok,
            'format_status': 'error' if error else 'pass' if format_ok else 'fail', 'error': error, 'parse_error': problem, 'envelope': mode,
            'answer_type':output_type,
            'set_precision': (len(got & wanted)/len(got) if got else 1.0 if not wanted else 0.0) if set_observed else None,
            'set_recall': (len(got & wanted)/len(wanted) if wanted else 1.0) if set_observed else None,
            'forbidden_items': sorted(got & set(forbidden)) if is_set else None,
            'duplicate_count': len(actual)-len(got) if is_set else None}


def action_grade(meta, final, content_grade):
    if not meta['delivery_candidates']:
        return {'status': 'not_applicable', 'file_success': None, 'tool_trace': 'not_applicable',
                'whole_task_success': content_grade['strict_task_success']}
    if final is None or final.get('error'):
        return {'status': 'error' if final and final.get('error') else 'unknown', 'file_success': False,
                'tool_trace': 'unknown', 'whole_task_success': False}
    artifacts = final.get('artifacts', {})
    spec = meta['delivery_spec']
    actions = (final.get('response') or {}).get('actions')
    if spec is None:
        observations = [artifacts.get(path) for path in meta['delivery_candidates']]
        observable = all(a is not None and a.get('exists') is not None and not a.get('error') for a in observations)
        clean = observable and all(a.get('exists') is False for a in observations)
        return {'status': 'pass' if clean else 'fail' if observable else 'unknown', 'file_success': clean,
                'tool_trace': 'unknown' if actions is None else 'observed', 'content_observed': False,
                'scope': 'Absence only at enumerated candidate paths, not all filesystem or internal storage.',
                'whole_task_success': content_grade['strict_task_success'] and clean}
    result = grade_delivery(artifacts.get(spec['path']), spec)
    written = None if actions is None else any(a.get('name') == 'write_file' and a.get('status') != 'failed' and a.get('arguments', {}).get('path') == spec['path'] for a in actions)
    result.update(tool_trace='unknown' if actions is None else 'observed', write_action=written,
                  whole_task_success=content_grade['strict_task_success'] and result['file_success'])
    return result


def quality(worlds):
    revised = all(w.get('contract') == 'memory-stress-0.1.1' for w in worlds)
    count = 30 if revised else 160
    if len(worlds) != count or len({w['scenario_id'] for w in worlds}) != count or len({w['seed'] for w in worlds}) != count:
        raise ValueError('Unexpected history count or duplicate scenario/seed')
    cells = Counter((w['family'], w['tier'], w['split']) for w in worlds)
    for family in (FAMILIES[:2] if revised else FAMILIES):
        for tier in (TIERS[:3] if revised else TIERS):
            if cells[(family,tier,'development')] != (5 if revised else 8) or cells[(family,tier,'reserved')] != (0 if revised else 2):
                raise ValueError('Split cell size mismatch')
    summary, proofs, pairs, strategies = [], {}, [], []
    for world in worlds:
        validate_world(world)
        for expression in EXPRESSIONS:
            for row in world['events']:
                if parse_event(render_event(row,expression),expression) != row: raise AssertionError('Expression changed facts')
        original = answers(world); primary = next(q for q in world['queries'] if q['role'] == 'primary')
        proof = evidence(world,primary)
        summary.append({k:world[k] for k in ('scenario_id','family','tier','split','seed','loads')})
        summary[-1].update(primary_required_evidence_groups=proof['required_group_count'], primary_sufficient_raw_records=len(proof['sufficient_sets'][0]))
        proofs[world['scenario_id']] = {q['id']:evidence(world,q) for q in world['queries']}
        for variant in VARIANTS[1:]:
            edited = transform(world,variant); validate_world(edited); changed = answers(edited)
            changing = variant in ('fact_edit','approval_swap')
            if (original[primary['id']] != changed[primary['id']]) != changing: raise AssertionError('Primary counterfactual failed')
            if not changing and original != changed: raise AssertionError('Invariance failed')
            pairs.append({'scenario_id':world['scenario_id'],'split_group':world['split_group'],'split':world['split'],
                          'variant':variant,'relation':'answer_changes' if changing else 'answer_invariant', 'base':original,'edited':changed})
        for policy in ('complete','first_state','ignore_cancel','scope_blind','accept_draft','recent_window'):
            predicted = answers(world,policy=policy)
            strategies.append({'scenario_id':world['scenario_id'],'family':world['family'],'tier':world['tier'],'split':world['split'],
                               'policy':policy,'primary_correct':predicted[primary['id']] == original[primary['id']], 'all_queries_correct':predicted == original})
    return {'kind':'offline_world_grammar_and_fault_checks','passed':True,'paid_calls':0,'history_count':count,
            'split_counts':dict(Counter(w['split'] for w in worlds)),'expression_roundtrips':sum(len(w['events'])*3 for w in worlds),'paired_relations_checked':len(pairs),
            'worlds':summary,'proofs':proofs,'pairs':pairs,'strategies':strategies,
            'claim_limit':'Synthetic grammar and fault checks only. No LLM baseline, model difficulty, blind test or independent human review.'}


def grouped_summary(rows):
    batches = defaultdict(list)
    for row in rows: batches[(row['split'], row['evaluation_track'])].append(row)
    summaries = []
    for (split, track), values in sorted(batches.items()):
        for item in v1_summary(values):
            selected = [r for r in values if all(r[k] == item[k] for k in ('agent','condition','expression','variant','family','tier','query_role'))]
            item.update(split=split,evaluation_track=track,
                        whole_task_success_rate=sum(r['action']['whole_task_success'] for r in selected)/len(selected),
                        file_status_counts=dict(Counter(r['action']['status'] for r in selected)),
                        action_count_visible=sum(r['action_count_visible'] for r in selected),
                        action_trace_visibility_rate=sum(r['action_trace_observed_steps'] for r in selected)/sum(r['planned_steps'] for r in selected),
                        interval_scope='Whole-history resampling; development and reserved groups kept separate, no generalization/significance claim.')
            summaries.append(item)
    return summaries


def paired_summary(rows):
    batches = defaultdict(list)
    for row in rows: batches[(row['split'],row['evaluation_track'])].append(row)
    return [dict(item,split=split,evaluation_track=track) for (split,track),values in sorted(batches.items()) for item in v1_pairs(values)]
