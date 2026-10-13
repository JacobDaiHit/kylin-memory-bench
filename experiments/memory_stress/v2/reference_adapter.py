"""Finite grammar software adapter with actual file writes; never a model baseline."""
import json
import sys
from pathlib import Path

if __package__ in (None, ''): sys.path.insert(0,str(Path(__file__).resolve().parents[3]))

from kylin_memory_bench.common import strict_json, write_json
from experiments.memory_stress.reference_adapter import parse_question as v1_question
from experiments.memory_stress.v2.oracle import normalized
from experiments.memory_stress.oracle import field_decision
from experiments.memory_stress.v2.render_history import parse_records
from experiments.memory_stress.v2.environment import write_delivery


def parse_question(prompt):
    for line in prompt.splitlines():
        if line.startswith('TASK='):
            value = strict_json(line[5:])
            fields = value['option_fields']
            value['options'] = [dict(o,values=dict(zip(fields,o['values']))) for o in value['options']]
            return value
    value = v1_question(prompt)
    if value is not None: value['mode'] = 'lookup'
    return value


def short_answer(rows, query):
    rows = normalized(rows)
    if query.get('at'):
        end = next((i for i,r in enumerate(rows) if r.get('checkpoint') == query['at']),None)
        if end is None: return None
        rows = rows[:end+1]
    subject, scope, field = query['subject'], query['scope'], query['field']
    if query.get('mode','lookup') != 'lookup':
        values = dict(query['provided'])
        for key in query['required_fields']:
            value = field_decision(rows,subject,scope,key)[0]
            if value is None: return None
            values[key] = value
        if field == 'files': return sorted(values.values())
        selected = [o for o in query['options'] if o['values'] == values]
        return selected[0]['id'] if len(selected) == 1 else None
    if field != 'directory': return field_decision(rows,subject,scope,field)[0]
    for _ in range(12):
        value = field_decision(rows,subject,scope,'directory')[0]
        if value is not None: return value
        keys = ('ref',) if scope == 'naming' else ('customer','profile','template','bundle','route','d1')
        next_values = [(k,field_decision(rows,subject,scope,k)[0]) for k in keys]
        next_values = [(k,v) for k,v in next_values if v is not None]
        if len(next_values) != 1: return None
        key, value = next_values[0]; subject = str(value); scope = 'client' if key == 'ref' else 'registry'
    raise ValueError('Cyclic relation chain')


def turn(request):
    workspace = Path(request['workspace']); path = workspace/'stress-v2-reference-state.json'
    rows = strict_json(path.read_text(encoding='utf-8')) if path.is_file() else []
    incoming = parse_records(request['prompt']); query = parse_question(request['prompt'])
    if query is None:
        rows.extend(incoming); write_json(path,rows)
        return {'text':'会话材料已接收。','actions':[]}
    if incoming:
        rows.extend(incoming); write_json(path,rows)
    answer = short_answer(incoming if incoming else rows,query)
    if answer is None and request['prompt'].startswith('TRAINING_ATTEMPT\n'):
        answer = query['options'][0]['id']
    actions = []
    if answer is not None and query.get('mode') == 'transfer': actions.append(write_delivery(workspace,query['deliveries'][answer]))
    return {'text':json.dumps({'answer':answer},ensure_ascii=False),'actions':actions,'memory':{'text':'','complete':False}}


def main():
    print(json.dumps(turn(strict_json(sys.stdin.read())),ensure_ascii=False))


if __name__ == '__main__': main()
