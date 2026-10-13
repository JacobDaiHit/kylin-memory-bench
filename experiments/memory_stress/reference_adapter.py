"""Offline grammar/replay adapter, NOT an LLM memory baseline. No gold-file access."""
import json
import sys
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from kylin_memory_bench.common import strict_json, write_json
from experiments.memory_stress.oracle import field_decision
from experiments.memory_stress.render_history import parse_event


def parse_records(prompt):
    markers=('EVENT=','记录"','用户：这次只谈对象')
    lines=prompt.splitlines()
    rows=[]
    i=0
    while i<len(lines):
        if lines[i].startswith(markers[0]):
            rows.append(parse_event(lines[i],'structured'));i+=1
        elif lines[i].startswith(markers[1]):
            rows.append(parse_event('\n'.join(lines[i:i+2]),'statement'));i+=2
        elif lines[i].startswith(markers[2]):
            rows.append(parse_event('\n'.join(lines[i:i+3]),'dialogue'));i+=3
        else:
            i+=1
    return rows


def parse_question(prompt):
    import re
    for line in prompt.splitlines():
        if line.startswith('查询：'):
            return strict_json(line[len('查询：'):])
        literal=r'("(?:\\.|[^"\\])*"|null)'
        pattern=r'^对象%s的%s范围，在(当前|检查点%s时)登记的%s是什么？$'%((literal,)*4)
        match=re.fullmatch(pattern,line)
        if match:
            return {'subject':strict_json(match[1]),'scope':strict_json(match[2]),
                    'at':strict_json(match[4]) if match[4] else None,'field':strict_json(match[5])}
        pattern=r'^用户：回到对象%s的%s范围。我要确认(当前|检查点%s时)的%s，请按批准记录回答。$'%((literal,)*4)
        match=re.fullmatch(pattern,line)
        if match:
            return {'subject':strict_json(match[1]),'scope':strict_json(match[2]),
                    'at':strict_json(match[4]) if match[4] else None,'field':strict_json(match[5])}
    return None


def short_answer(rows, question):
    """Resolve the public record convention without reading evaluator query paths."""
    if question['at'] is not None:
        end=next((i for i,r in enumerate(rows) if r.get('checkpoint')==question['at']),None)
        if end is None:return None
        rows=rows[:end+1]
    subject,scope,field=question['subject'],question['scope'],question['field']
    if field!='directory':
        return field_decision(rows,subject,scope,field)[0]
    for _ in range(10):
        direct=field_decision(rows,subject,scope,'directory')[0]
        if direct is not None:return direct
        keys=('ref',) if scope=='naming' else ('customer','profile','template','d1')
        candidates=[(key,field_decision(rows,subject,scope,key)[0]) for key in keys]
        candidates=[(k,v) for k,v in candidates if v is not None]
        if len(candidates)!=1:return None
        key,value=candidates[0]
        subject=str(value);scope='client' if key=='ref' else 'registry'
    raise ValueError('Cyclic reference chain')


def turn(request):
    workspace=Path(request['workspace'])
    state=workspace/'stress-reference-state.json'
    rows=json.loads(state.read_text(encoding='utf-8')) if state.is_file() else []
    incoming=parse_records(request['prompt'])
    question=parse_question(request['prompt'])
    if question is None:
        rows.extend(incoming);write_json(state,rows)
        return {'text':'登记已接收。'}
    # The fresh final workspace is empty for open_book and oracle_evidence.
    material=incoming if incoming else rows
    return {'text':json.dumps({'answer':short_answer(material,question)},ensure_ascii=False),
            'actions':[],'memory':{'text':'','complete':False}}


def main():
    request=strict_json(sys.stdin.read())
    print(json.dumps(turn(request),ensure_ascii=False))


if __name__=='__main__':
    main()
