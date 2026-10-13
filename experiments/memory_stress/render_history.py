"""Three bounded grammars over identical facts; no LLM paraphrasing or hidden JSON."""
import json
import re

from kylin_memory_bench.common import strict_json

EXPRESSIONS = ('structured', 'statement', 'dialogue')
RULES = '''档案规则：按收到记录的先后顺序处理，accepted表示批准，draft表示未批准；只使用已批准登记。
assert仅修改列出的字段，其他字段和其他对象／范围保持不变。label是编号，不能按数字大小确定有效版本。
cancel只撤销同对象、同范围的target_id记录中列出的字段；按剩余批准修改重新恢复值。未撤销字段继续有效。
checkpoint标记该记录刚处理完的状态；查询该时刻时不使用后续修改。discussion不改变档案事实。
directory可能直接登记，也可能需沿customer、profile、template关系找到directory；后续实体的关系登记在registry范围。
命名别名的ref在naming范围。D1/d1只是已给出的登记键：需要目录时沿d1对应键、profile、template、directory登记查找，不计算。
这里只恢复原文事实与有效状态，不计算数学量、不猜约定。无法由提供的登记确定时返回null。
'''


def literal(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def render_event(row, expression='structured'):
    if expression not in EXPRESSIONS:
        raise ValueError('Unknown expression')
    if expression == 'structured':
        return 'EVENT='+literal(row)
    values = [row['id'], row['subject'], row['scope'], row['status'], row.get('label'), row.get('checkpoint')]
    if expression == 'statement':
        head = '记录%s；对象%s；范围%s；状态%s；编号%s；检查点%s。'%tuple(literal(v) for v in values)
    else:
        head = '用户：这次只谈对象%s的%s范围。\n用户：记作%s，状态%s，编号%s，检查点%s。'%tuple(literal(v) for v in [values[1],values[2],values[0],*values[3:]])
    if row['kind'] == 'cancel':
        body = '只撤销记录%s的字段%s；其他字段保留。'%(literal(row['target_id']), literal(row['fields']))
    else:
        assignments = '；'.join(literal(k)+'='+literal(v) for k,v in row['fields'].items())
        body = ('讨论，不改变任何登记：' if row['kind']=='discussion' else '仅将这些字段登记为：')+assignments+'。'
    return head+'\n'+body


def parse_event(text, expression='structured'):
    """Independent grammar readback for consistency, not a general NLP baseline."""
    if expression == 'structured':
        return strict_json(text.removeprefix('EVENT='))
    quoted = r'("(?:\\.|[^"\\])*"|null)'
    if expression == 'statement':
        pattern = r'^记录%s；对象%s；范围%s；状态%s；编号%s；检查点%s。\n(.*)$'%((quoted,)*6)
        match = re.fullmatch(pattern, text, re.DOTALL)
        if not match:
            raise ValueError('Invalid statement grammar')
        values = [strict_json(v) for v in match.groups()[:6]]
    else:
        pattern = r'^用户：这次只谈对象%s的%s范围。\n用户：记作%s，状态%s，编号%s，检查点%s。\n(.*)$'%((quoted,)*6)
        match = re.fullmatch(pattern, text, re.DOTALL)
        if not match:
            raise ValueError('Invalid dialogue grammar')
        raw = [strict_json(v) for v in match.groups()[:6]]
        values = [raw[2], raw[0], raw[1], *raw[3:]]
    row = dict(zip(('id','subject','scope','status','label','checkpoint'), values))
    row = {k:v for k,v in row.items() if v is not None}
    body = match[7]
    cancel = re.fullmatch(r'只撤销记录('+quoted+r')的字段(\[.*\])；其他字段保留。', body)
    if cancel:
        row.update(kind='cancel',target_id=strict_json(cancel[1]),fields=strict_json(cancel[3]))
        return row
    row['kind'] = 'discussion' if body.startswith('讨论，不改变任何登记：') else 'assert'
    prefix = '讨论，不改变任何登记：' if row['kind']=='discussion' else '仅将这些字段登记为：'
    if not body.startswith(prefix) or not body.endswith('。'):
        raise ValueError('Invalid field clause')
    row['fields'] = {}
    for assignment in body[len(prefix):-1].split('；'):
        key, value = assignment.split('=',1)
        row['fields'][strict_json(key)] = strict_json(value)
    return row


def render_query(query, expression='structured'):
    subject, scope, goal = query['subject'], query['path'][0]['scope'], query['goal']
    when = '当前' if not query.get('at') else '检查点'+literal(query['at'])+'时'
    if expression == 'structured':
        text = '查询：'+literal({'subject':subject,'scope':scope,'field':goal,'at':query.get('at')})
    elif expression == 'statement':
        text = '对象%s的%s范围，在%s登记的%s是什么？'%(literal(subject),literal(scope),when,literal(goal))
    else:
        text = '用户：回到对象%s的%s范围。我要确认%s的%s，请按批准记录回答。'%(literal(subject),literal(scope),when,literal(goal))
    return RULES+'\n'+text+'\n只返回一个JSON对象{"answer":实际短值}，未知值为null。不附解释。'
